"""Approved backlog admission into the existing Fleet (INV-FLEET-BACKLOG-001).

A thin coordinator, not a second executor or scheduler. It owns two buckets over the existing
store - `fleet_backlog_plans` (one registered Git-pinned plan per plan id, with the pin and its
digest) and `fleet_backlog_intents` (one durable intent per plan item) - and it reaches the fleet
only through `Fleet.enqueue`. Admission, concurrency, lane and path exclusion, pause, the machine
ledger, dispatch and finalization all stay exactly where they are.

One tick is three short store transactions with the external work strictly between them:

1. select: read the plan, the intents, the authoritative `fleet_jobs` rows and the fleet control
   row in ONE transaction, settle any open intent against the job that may already exist, and
   write the durable intent for the item this tick will work on.
2. resolve: read and validate the pinned manifest and bind its goal OUTSIDE every transaction
   (that is Git and file I/O), then record the exact job identity on the intent.
3. enqueue: call the idempotent `Fleet.enqueue`, which opens its OWN transaction, and confirm.

No transaction is ever open while another one is taken. The real `PostgresStore.transaction`
connects and takes `pg_advisory_xact_lock` per transaction, so a nested call would deadlock until
`lock_timeout`; keeping the git read, the manifest validation and the enqueue outside the
selection transaction is the contract, not a style choice.

Idempotence follows the durable-intent rule: the intent exists before the enqueue, the job id is
the operation id, and a replay after a lost response reconciles the already created job instead of
creating a second one. An equal job id under another manifest or goal is a `conflict` for the
owner, never evidence that the enqueue succeeded. Accepted, failed, unknown and pending stay
distinct, a selection receipt is never a completion or release receipt, and an idle poll writes
nothing.
"""
from __future__ import annotations

import logging

from codex_harness.application.fleet import BUCKET_CONTROL, BUCKET_JOBS, CONTROL_KEY, Fleet
from codex_harness.domain.fleet import FleetRefused
from codex_harness.domain.fleet_backlog import (
    AUTHORITY,
    BLOCKED,
    CONFLICT,
    ENQUEUED,
    INTENDED,
    MAX_ATTEMPTS,
    OUTCOME_CONFLICT,
    OUTCOME_ENQUEUED,
    OUTCOME_REFUSED,
    OUTCOME_SELECTED,
    OUTCOME_UNAVAILABLE,
    OUTCOME_UNREGISTERED,
    STATUS_SCHEMA,
    TICK_SCHEMA,
    BacklogRefused,
    intent_pin,
    item_pin,
    new_intent,
    plan_digest,
    plan_next_action,
    plan_status,
    reconcile_intent,
    select,
    validate_pin,
    validate_plan,
)
from codex_harness.domain.model import utcnow
from codex_harness.domain.operation import manifest_digest

BUCKET_PLANS, BUCKET_INTENTS = "fleet_backlog_plans", "fleet_backlog_intents"
LOGGER = logging.getLogger("zeus.fleet.backlog")


class FleetBacklog:
    """Owner-approved backlog plans over one store and one existing `Fleet`.

    `loader` is supplied per tick by the adapter: it reads the pinned manifest from Git, validates
    it with the existing operation validator and binds its goal. It is called outside every store
    transaction and its definite refusals arrive as `BacklogRefused`.
    """

    def __init__(self, store, fleet: Fleet | None = None, clock=utcnow):
        self.store, self.clock = store, clock
        self.fleet = Fleet(store) if fleet is None else fleet

    # ----- registry -----------------------------------------------------------------------
    @staticmethod
    def _intents(tx, plan_id: str) -> dict:
        return {row["item_id"]: row for row in tx.scan(BUCKET_INTENTS) if row.get("plan_id") == plan_id}

    def register(self, document, pin) -> dict:
        """Register one validated plan read at an explicit commit; the identical plan at the
        identical pin is cached.

        A later registration may add items and may flip `enabled`, because those are owner
        decisions expressed in Git. It may NOT move an item that already carries a durable intent:
        a changed lane or manifest pin, or a removed item, refuses the whole registration and
        writes nothing, so a queued manifest is never edited under an admitted job.
        """
        plan = validate_plan(document)
        pin = validate_pin(pin)
        sha, now = plan_digest(plan), self.clock()
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_PLANS, plan["plan_id"])
            if old is not None:
                if old["plan_sha256"] == sha and old["pin"] == pin:
                    return {"registered": True, "cached": True, "plan_id": plan["plan_id"],
                            "plan_sha256": sha, "pin": pin, "items": len(plan["items"]),
                            "enabled": plan["enabled"], "authority": AUTHORITY}
                if old["plan"]["repository"] != plan["repository"]:
                    raise BacklogRefused("repository_conflict", "repository")
                items = {item["id"]: item for item in plan["items"]}
                for item_id, intent in sorted(self._intents(tx, plan["plan_id"]).items()):
                    item = items.get(item_id)
                    if item is None:
                        raise BacklogRefused("item_removed", "items[].id")
                    if item_pin(item) != intent_pin(intent):
                        raise BacklogRefused("item_pin_changed", "items[].manifest_revision")
            row = {"id": plan["plan_id"], "plan_id": plan["plan_id"], "plan": plan, "plan_sha256": sha,
                   "pin": pin, "repository": plan["repository"],
                   "registered_at": (old or {}).get("registered_at") or now, "updated_at": now}
            tx.put(BUCKET_PLANS, plan["plan_id"], row)
        return {"registered": True, "cached": False, "plan_id": plan["plan_id"], "plan_sha256": sha,
                "pin": pin, "items": len(plan["items"]), "enabled": plan["enabled"], "authority": AUTHORITY}

    def plan(self, plan_id: str) -> dict | None:
        with self.store.transaction() as tx:
            return tx.get(BUCKET_PLANS, plan_id)

    # ----- one tick -----------------------------------------------------------------------
    def tick(self, plan_id: str, loader) -> dict:
        """Select and admit at most one eligible successor; every other outcome is recorded."""
        decision = self._select(plan_id)
        if decision["outcome"] != OUTCOME_SELECTED:
            return self._result(decision)
        item, intent = decision["item"], decision["intent"]
        try:
            loaded = loader(item)
        except BacklogRefused as exc:
            return self._result(decision, **self._attempt_failed(intent, exc.reason_code))
        except Exception as exc:
            # The pinned input could not be read at all. Unavailable is not a failure of this item
            # and is not counted as an attempt; nothing is written and nothing is invented.
            return self._result(decision, outcome=OUTCOME_UNAVAILABLE, reason_code="input_unavailable",
                                error_type=type(exc).__name__)
        manifest, goal = loaded["manifest"], loaded["goal"]
        intent = self._intend(intent, manifest, goal)
        if intent["state"] == CONFLICT:
            return self._result(decision, outcome=OUTCOME_CONFLICT, reason_code=intent["reason_code"],
                                job_id=intent.get("job_id"))
        # Selection already required every dependency's Fleet job to be `accepted`; the ids are
        # relayed so Fleet keeps its own predeclared dependency record for this job.
        dependencies = [(decision["intents"].get(d) or {}).get("job_id") for d in item["dependencies"]]
        if any(job_id is None for job_id in dependencies):
            return self._result(decision, **self._attempt_failed(intent, "dependency_job_missing"))
        try:
            enqueued = self.fleet.enqueue(item["lane"], manifest, goal, dependencies)
        except FleetRefused as exc:
            if exc.reason_code == "binding_conflict":
                # An equal job id carrying another binding: a conflict for the owner, never a
                # successful enqueue and never an overwrite of the already queued job.
                return self._result(decision, **self._conflict(intent, "binding_conflict"))
            return self._result(decision, **self._attempt_failed(intent, "enqueue_" + exc.reason_code))
        job = enqueued["job"]
        confirmed = self._confirm(intent, job)
        if confirmed["state"] == CONFLICT:
            return self._result(decision, outcome=OUTCOME_CONFLICT, reason_code=confirmed["reason_code"],
                                job_id=job["id"])
        LOGGER.info("fleet backlog admitted plan=%s item=%s job=%s lane=%s cached=%s",
                    plan_id, item["id"], job["id"], job["lane"], bool(enqueued["cached"]))
        return self._result(decision, outcome=OUTCOME_ENQUEUED, job_id=job["id"],
                            cached=bool(enqueued["cached"]), job_status=job["status"])

    def _select(self, plan_id: str) -> dict:
        """Transaction 1: reconcile open intents against the authoritative Fleet rows, choose the
        next item deterministically and write its durable intent. Idle outcomes write nothing."""
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_PLANS, plan_id)
            if row is None:
                return {"plan_id": plan_id, "outcome": OUTCOME_UNREGISTERED, "item": None,
                        "intent": None, "intents": {}, "blocked": {}, "at": now}
            intents = self._intents(tx, plan_id)
            jobs = {job["id"]: job for job in tx.scan(BUCKET_JOBS)}
            control = tx.get(BUCKET_CONTROL, CONTROL_KEY) or {}
            for item_id, intent in sorted(intents.items()):
                settled = reconcile_intent(intent, jobs, now)
                if settled is not None:
                    tx.put(BUCKET_INTENTS, settled["id"], settled)
                    intents[item_id] = settled
            decision = select(row["plan"], intents, jobs, bool(control.get("paused")))
            item = decision["item"]
            if item is not None and item["id"] not in intents:
                intent = new_intent(plan_id, item, now)
                tx.put(BUCKET_INTENTS, intent["id"], intent)
                intents[item["id"]] = intent
        return {"plan_id": plan_id, "outcome": decision["outcome"], "item": item,
                "intent": None if item is None else intents[item["id"]], "intents": intents,
                "blocked": decision["blocked"], "at": now}

    def _intend(self, intent: dict, manifest: dict, goal: dict) -> dict:
        """Transaction 2: record the exact job identity this intent will enqueue."""
        job_id, sha = manifest["id"], manifest_digest(manifest)
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INTENTS, intent["id"]) or intent
            if row["state"] == ENQUEUED:
                return row
            recorded = (row.get("job_id"), row.get("job_manifest_sha256"))
            if recorded != (None, None) and recorded != (job_id, sha):
                settled = {**row, "state": CONFLICT, "reason_code": "intent_identity_conflict",
                           "updated_at": now}
                tx.put(BUCKET_INTENTS, settled["id"], settled)
                return settled
            settled = {**row, "state": INTENDED, "job_id": job_id, "job_manifest_sha256": sha,
                       "goal_sha256": goal["sha256"], "base_revision": goal["base_revision"],
                       "reason_code": None, "updated_at": now}
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        return settled

    def _confirm(self, intent: dict, job: dict) -> dict:
        """Transaction 3: the authoritative job row settles the intent."""
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INTENTS, intent["id"]) or intent
            if (job.get("id"), job.get("manifest_sha256")) != (row.get("job_id"), row.get("job_manifest_sha256")):
                settled = {**row, "state": CONFLICT, "reason_code": "job_binding_conflict", "updated_at": now}
            else:
                settled = {**row, "state": ENQUEUED, "reason_code": None,
                           "enqueued_at": row.get("enqueued_at") or now, "updated_at": now}
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        return settled

    def _attempt_failed(self, intent: dict, reason_code: str) -> dict:
        """One definite refusal of this item. Two distinct attempts block the item and hand it to
        the owner: no infinite retry, and every other eligible item keeps moving."""
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INTENTS, intent["id"]) or intent
            attempts = int(row.get("attempts", 0)) + 1
            state = BLOCKED if attempts >= MAX_ATTEMPTS else row["state"]
            settled = {**row, "attempts": attempts, "state": state, "reason_code": reason_code,
                       "updated_at": now}
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        LOGGER.warning("fleet backlog item refused plan=%s item=%s reason=%s attempts=%d state=%s",
                       row["plan_id"], row["item_id"], reason_code, attempts, state)
        return {"outcome": OUTCOME_REFUSED, "reason_code": reason_code, "attempts": attempts,
                "item_state": state}

    def _conflict(self, intent: dict, reason_code: str) -> dict:
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INTENTS, intent["id"]) or intent
            settled = {**row, "state": CONFLICT, "reason_code": reason_code, "updated_at": now}
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        LOGGER.warning("fleet backlog conflict plan=%s item=%s job=%s reason=%s",
                       row["plan_id"], row["item_id"], row.get("job_id"), reason_code)
        return {"outcome": OUTCOME_CONFLICT, "reason_code": reason_code, "job_id": row.get("job_id"),
                "item_state": CONFLICT}

    @staticmethod
    def _result(decision: dict, **overrides) -> dict:
        """The bounded tick receipt: identities, one outcome, a fixed reason code and a next
        action. It is a selection receipt, never a completion, review or release receipt."""
        item = decision.get("item")
        result = {"schema": TICK_SCHEMA, "plan_id": decision["plan_id"], "outcome": decision["outcome"],
                  "item_id": None if item is None else item["id"],
                  "lane": None if item is None else item["lane"],
                  "job_id": None, "job_status": None, "cached": None, "reason_code": None,
                  "error_type": None, "item_state": None, "blocked": dict(decision.get("blocked") or {}),
                  "at": decision["at"], "authority": AUTHORITY}
        result.update(overrides)
        result["next_action"] = plan_next_action(result["outcome"])
        return result

    # ----- read-only ----------------------------------------------------------------------
    def status(self, plan_id: str | None = None) -> dict:
        """The durable bounded status of one plan, or of every registered plan. Store reads only:
        no git, process, provider or fleet admission happens here."""
        with self.store.transaction() as tx:
            rows = tx.scan(BUCKET_PLANS) if plan_id is None else [r for r in [tx.get(BUCKET_PLANS, plan_id)] if r]
            intents = tx.scan(BUCKET_INTENTS)
            jobs = {job["id"]: job for job in tx.scan(BUCKET_JOBS)}
            fleet_paused = bool((tx.get(BUCKET_CONTROL, CONTROL_KEY) or {}).get("paused"))
        if plan_id is not None and not rows:
            return {"schema": STATUS_SCHEMA, "plan_id": plan_id, "registered": False,
                    "outcome": OUTCOME_UNREGISTERED, "next_action": plan_next_action(OUTCOME_UNREGISTERED),
                    "fleet_paused": fleet_paused, "plans": [], "authority": AUTHORITY}
        plans = [plan_status(row, {i["item_id"]: i for i in intents if i.get("plan_id") == row["plan_id"]},
                             jobs, fleet_paused) for row in sorted(rows, key=lambda r: r["plan_id"])]
        # `registered` says whether this read found a plan; an empty list is an honest empty read,
        # never a registered plan and never a failure of the store.
        return {"schema": STATUS_SCHEMA, "registered": bool(plans), "fleet_paused": fleet_paused,
                "plans": plans, "authority": AUTHORITY}


__all__ = ["BUCKET_INTENTS", "BUCKET_PLANS", "FleetBacklog", "LOGGER"]
