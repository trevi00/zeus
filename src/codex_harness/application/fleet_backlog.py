"""Approved backlog admission into the existing Fleet (INV-FLEET-BACKLOG-001).

A thin coordinator, not a second executor or scheduler. It owns two buckets over the existing
store - `fleet_backlog_plans` (one registered Git-pinned plan per plan id, with the pin and its
digest) and `fleet_backlog_intents` (one durable intent per plan item) - and it reaches the fleet
only through `Fleet.enqueue` and the portfolio only through the owner's `Portfolio.bind`.
Admission, concurrency, lane and path exclusion, pause, the machine ledger, dispatch, finalization
and the portfolio's own binding rules all stay exactly where they are.

One tick is a few short store transactions with the external work strictly between them:

1. select: read the plan, the intents, the authoritative `fleet_jobs` rows and the fleet control
   row in ONE transaction, settle any open intent against the job that may already exist, and
   write the durable intent for the item this tick will work on.
2. resolve: read and validate the pinned manifest and bind its goal OUTSIDE every transaction
   (that is Git and file I/O), then record the exact job identity on the intent.
3. enqueue: call the idempotent `Fleet.enqueue`, which opens its OWN transaction, and confirm
   against the durable job row.
4. link: call the existing `Portfolio.bind` for the item's project and criterion, which also opens
   its own transaction, and record the durable linkage.

No transaction is ever open while another one is taken. The real `PostgresStore.transaction`
connects and takes `pg_advisory_xact_lock` per transaction, so a nested call would deadlock until
`lock_timeout`; keeping the git read, the manifest validation, the enqueue and the binding outside
the selection transaction is the contract, not a style choice.

Idempotence follows the durable-intent rule: the intent exists before the enqueue, the job id is
the operation id, and a replay after a lost response reconciles the already created job instead of
creating a second one. Identity is the COMPLETE `domain.fleet.binding` of the authoritative job row
- lane, repository, frozen manifest digest, predeclared dependencies and every bound goal field -
never a projection and never a partial comparison: an equal job id under any other binding is a
`conflict` for the owner. Accepted, failed, unknown, pending and unlinked stay distinct, a
selection receipt is never a completion or release receipt, and an idle poll writes nothing.

A repeatedly unavailable input or binding owner defers ONE item for a bounded number of ticks
instead of holding the plan: the intent is kept, reconciled and recoverable, unrelated eligible
items keep moving, and after `MAX_DEFERRALS` outages the item is handed to the owner.
"""
from __future__ import annotations

import logging

from codex_harness.application.fleet import BUCKET_CONTROL, BUCKET_JOBS, CONTROL_KEY, Fleet
from codex_harness.application.portfolio import PortfolioRefused
from codex_harness.domain.fleet import FleetRefused
from codex_harness.domain.fleet_backlog import (
    ACTION_LINK,
    AUTHORITY,
    BLOCKED,
    CONFLICT,
    ENQUEUED,
    EVENT_ADMITTED,
    EVENT_RECOVERED,
    EVENT_REFUSED,
    EVENT_UNAVAILABLE,
    INTENDED,
    LINK_BLOCKED,
    LINK_CONFLICT,
    LINK_LINKED,
    LINK_PENDING,
    MAX_ATTEMPTS,
    MAX_DEFERRALS,
    OUTCOME_CONFLICT,
    OUTCOME_ENQUEUED,
    OUTCOME_REFUSED,
    OUTCOME_SELECTED,
    OUTCOME_UNAVAILABLE,
    OUTCOME_UNREGISTERED,
    STATUS_SCHEMA,
    TICK_SCHEMA,
    BacklogRefused,
    defer_ticks_for,
    expected_binding,
    job_matches,
    link_state,
    new_intent,
    plan_digest,
    plan_next_action,
    plan_status,
    reconcile_intent,
    safe_error_type,
    scope_reason,
    select,
    validate_pin,
    validate_plan,
)
from codex_harness.domain.model import utcnow
from codex_harness.domain.operation import manifest_digest

BUCKET_PLANS, BUCKET_INTENTS = "fleet_backlog_plans", "fleet_backlog_intents"
LOGGER = logging.getLogger("zeus.fleet.backlog")

# The tick outcomes that are transitions worth one structured observation. `selected`, `blocked`,
# both pauses and an exhausted backlog are ordinary polls and are deliberately not emitted.
OBSERVED_OUTCOMES = frozenset({OUTCOME_ENQUEUED, OUTCOME_REFUSED, OUTCOME_CONFLICT, OUTCOME_UNAVAILABLE})


class FleetBacklog:
    """Owner-approved backlog plans over one store, one existing `Fleet` and one existing
    `Portfolio`.

    `loader` is supplied per tick by the adapter: it reads the pinned manifest from Git, validates
    it with the existing operation validator, binds its goal and names the lane repository identity
    the job will carry. It is called outside every store transaction and its definite refusals
    arrive as `BacklogRefused`.

    `portfolio` is the existing owner of job-to-criterion bindings. Without one, an admitted item's
    linkage stays `pending`: unfinished, visible and recoverable, never a reported success and
    never a reason to unlock a dependent item. `observer` is the existing observation port; without
    one nothing is emitted and the durable status is unchanged.
    """

    def __init__(self, store, fleet: Fleet | None = None, clock=utcnow, portfolio=None, observer=None):
        self.store, self.clock = store, clock
        self.fleet = Fleet(store) if fleet is None else fleet
        self.portfolio, self.observer = portfolio, observer

    # ----- registry -----------------------------------------------------------------------
    @staticmethod
    def _intents(tx, plan_id: str) -> dict:
        return {row["item_id"]: row for row in tx.scan(BUCKET_INTENTS) if row.get("plan_id") == plan_id}

    def register(self, document, pin) -> dict:
        """Register one validated plan read at an explicit commit; the identical plan at the
        identical pin is cached.

        A later registration may add items and may flip `enabled`, because those are owner
        decisions expressed in Git. It may NOT move an item that already carries a durable intent:
        a changed lane, manifest pin, project, criterion or dependency list, or a removed item,
        refuses the whole registration and writes nothing, so neither a queued manifest nor the
        goal it was selected under is ever edited under an admitted job.
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
                    moved = scope_reason(item, intent)
                    if moved == "pin_changed":
                        raise BacklogRefused("item_pin_changed", "items[].manifest_revision")
                    if moved is not None:
                        raise BacklogRefused("item_scope_changed", "items[].project_id")
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
        # What this item was already waiting on, so a recovery can be recognized after the fact.
        before = int(intent.get("deferrals") or 0)
        if decision["action"] == ACTION_LINK:
            # The job exists; only its durable goal binding is owed.
            return self._observed(decision, before, cached=True, job_id=intent.get("job_id"),
                                  **self._link(item, intent))
        try:
            loaded = loader(item)
        except BacklogRefused as exc:
            return self._observed(decision, before, **self._attempt_failed(intent, exc.reason_code))
        except Exception as exc:
            # The pinned input could not be read at all. Unavailable is not a definite failure of
            # this item and is not counted as an attempt: the item is deferred for a bounded number
            # of ticks so an independent eligible item keeps moving, and nothing is invented.
            return self._observed(decision, before,
                                  **self._defer(intent, "input_unavailable", type(exc).__name__))
        manifest, goal, repository = loaded["manifest"], loaded["goal"], loaded.get("repository")
        # Selection already required every dependency's Fleet job to be `accepted` and linked; the
        # ids are relayed so Fleet keeps its own predeclared dependency record for this job.
        dependencies = [(decision["intents"].get(d) or {}).get("job_id") for d in item["dependencies"]]
        if any(job_id is None for job_id in dependencies):
            return self._observed(decision, before, **self._attempt_failed(intent, "dependency_job_missing"))
        if type(repository) is not str or not repository:
            # The loader must name the repository identity the job will carry; without it the
            # complete binding cannot be recorded before the enqueue, so nothing is enqueued.
            return self._observed(decision, before, **self._attempt_failed(intent, "repository_identity_missing"))
        expected = expected_binding(item["lane"], repository, manifest_digest(manifest), dependencies, goal)
        intent = self._intend(intent, manifest, goal, expected)
        if intent["state"] == CONFLICT:
            return self._observed(decision, before, outcome=OUTCOME_CONFLICT,
                                  reason_code=intent["reason_code"], job_id=intent.get("job_id"),
                                  item_state=CONFLICT)
        try:
            enqueued = self.fleet.enqueue(item["lane"], manifest, goal, dependencies)
        except FleetRefused as exc:
            if exc.reason_code == "binding_conflict":
                # An equal job id carrying another binding: a conflict for the owner, never a
                # successful enqueue and never an overwrite of the already queued job.
                return self._observed(decision, before, **self._conflict(intent, "binding_conflict"))
            return self._observed(decision, before, **self._attempt_failed(intent, "enqueue_" + exc.reason_code))
        job = enqueued["job"]
        confirmed = self._confirm(intent, job["id"])
        if confirmed["state"] == CONFLICT:
            return self._observed(decision, before, outcome=OUTCOME_CONFLICT,
                                  reason_code=confirmed["reason_code"], job_id=job["id"],
                                  item_state=CONFLICT)
        LOGGER.info("fleet backlog admitted plan=%s item=%s job=%s lane=%s cached=%s",
                    plan_id, item["id"], job["id"], job["lane"], bool(enqueued["cached"]))
        return self._observed(decision, before, job_id=job["id"], cached=bool(enqueued["cached"]),
                              job_status=job["status"], **self._link(item, confirmed))

    def _select(self, plan_id: str) -> dict:
        """Transaction 1: reconcile open intents against the authoritative Fleet rows, choose the
        next item deterministically and write its durable intent. Idle outcomes write nothing; a
        deferred item's bounded countdown is a durable transition, not an idle poll."""
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_PLANS, plan_id)
            if row is None:
                return {"plan_id": plan_id, "outcome": OUTCOME_UNREGISTERED, "item": None, "action": None,
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
            for item_id in decision["deferred"]:
                # The bounded wait of an item this decision passed over counts down durably, so a
                # restart neither forgets it nor retries it early.
                waiting = intents[item_id]
                settled = {**waiting, "defer_ticks": max(0, int(waiting.get("defer_ticks") or 0) - 1),
                           "updated_at": now}
                tx.put(BUCKET_INTENTS, settled["id"], settled)
                intents[item_id] = settled
            item = decision["item"]
            if item is not None and item["id"] not in intents:
                intent = new_intent(plan_id, item, now)
                tx.put(BUCKET_INTENTS, intent["id"], intent)
                intents[item["id"]] = intent
        return {"plan_id": plan_id, "outcome": decision["outcome"], "item": item,
                "action": decision["action"], "intents": intents,
                "intent": None if item is None else intents[item["id"]],
                "blocked": decision["blocked"], "at": now}

    def _intend(self, intent: dict, manifest: dict, goal: dict, expected: dict) -> dict:
        """Transaction 2: record the exact job identity this intent will enqueue.

        The COMPLETE binding is persisted before the call, so a crash between here and the enqueue
        can only either recognize its own job or report a conflict; it can never adopt a foreign
        job that happens to carry the same id.
        """
        job_id, sha = manifest["id"], manifest_digest(manifest)
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INTENTS, intent["id"]) or intent
            if row["state"] == ENQUEUED:
                return row
            recorded = (row.get("job_id"), row.get("job_binding"))
            if recorded != (None, None) and recorded != (job_id, expected):
                settled = {**row, "state": CONFLICT, "reason_code": "intent_identity_conflict",
                           "updated_at": now}
                tx.put(BUCKET_INTENTS, settled["id"], settled)
                return settled
            settled = {**row, "state": INTENDED, "job_id": job_id, "job_manifest_sha256": sha,
                       "goal_sha256": goal["sha256"], "base_revision": goal["base_revision"],
                       "job_binding": expected, "reason_code": None, "updated_at": now}
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        return settled

    def _confirm(self, intent: dict, job_id: str) -> dict:
        """Transaction 3: the AUTHORITATIVE job row settles the intent.

        The durable row is read here, never the caller's projection: `Fleet._view` omits
        `repository`, and a partial comparison cannot establish that this is the same job.
        """
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INTENTS, intent["id"]) or intent
            job = tx.get(BUCKET_JOBS, job_id)
            if job is None:
                settled = {**row, "state": CONFLICT, "reason_code": "job_missing", "updated_at": now}
            elif not job_matches(row, job):
                settled = {**row, "state": CONFLICT, "reason_code": "job_binding_conflict", "updated_at": now}
            else:
                settled = {**row, "state": ENQUEUED, "reason_code": None, "error_type": None,
                           "enqueued_at": row.get("enqueued_at") or now, "updated_at": now}
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        return settled

    # ----- the portfolio linkage of one admitted job ----------------------------------------
    def _link(self, item: dict, intent: dict) -> dict:
        """Bind the admitted job to its EXISTING portfolio criterion through the owner's
        `Portfolio.bind`, outside every held transaction.

        The binding owner keeps its own rules: an identical replay is cached and an existing
        DIFFERENT binding is a conflict that is never rewritten here. An outage leaves the linkage
        durably pending and recoverable; nothing reports linked success and no dependent item is
        unlocked until the binding actually exists.
        """
        if link_state(intent) == LINK_LINKED:
            return {"outcome": OUTCOME_ENQUEUED, "linked": True, "link_state": LINK_LINKED}
        job_id = intent.get("job_id")
        if self.portfolio is None:
            return self._defer(intent, "binding_owner_absent", None, link=True)
        try:
            receipt = self.portfolio.bind(job_id, item["project_id"], item["criterion_id"])
        except PortfolioRefused as exc:
            # A definite refusal by the binding owner: the criterion, the job or the target is not
            # what this item claims. It is handed to the owner, never retried into a success.
            if exc.reason_code == "binding_conflict":
                # This job is already bound to ANOTHER criterion by its owner; it is never rewritten.
                return self._link_refused(intent, LINK_CONFLICT, "portfolio_binding_conflict")
            return self._link_refused(intent, LINK_BLOCKED, "binding_" + exc.reason_code)
        except Exception as exc:
            return self._defer(intent, "binding_unavailable", type(exc).__name__, link=True)
        return self._linked(intent, receipt)

    def _linked(self, intent: dict, receipt: dict) -> dict:
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INTENTS, intent["id"]) or intent
            settled = {**row, "link_state": LINK_LINKED, "link_reason": None,
                       "linked_at": row.get("linked_at") or now, "deferrals": 0, "defer_ticks": 0,
                       "error_type": None, "updated_at": now}
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        LOGGER.info("fleet backlog linked plan=%s item=%s job=%s project=%s criterion=%s cached=%s",
                    settled["plan_id"], settled["item_id"], settled.get("job_id"),
                    settled["project_id"], settled["criterion_id"], bool(receipt.get("cached")))
        return {"outcome": OUTCOME_ENQUEUED, "linked": True, "link_state": LINK_LINKED}

    def _link_refused(self, intent: dict, state: str, reason_code: str) -> dict:
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INTENTS, intent["id"]) or intent
            settled = {**row, "link_state": state, "link_reason": reason_code, "updated_at": now}
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        LOGGER.warning("fleet backlog binding refused plan=%s item=%s job=%s reason=%s state=%s",
                       settled["plan_id"], settled["item_id"], settled.get("job_id"), reason_code, state)
        return {"outcome": OUTCOME_CONFLICT if state == LINK_CONFLICT else OUTCOME_REFUSED,
                "reason_code": reason_code, "linked": False, "link_state": state}

    # ----- durable failure bookkeeping ------------------------------------------------------
    def _attempt_failed(self, intent: dict, reason_code: str) -> dict:
        """One definite refusal of this item. Two distinct attempts block the item and hand it to
        the owner: no infinite retry, and every other eligible item keeps moving."""
        now = self.clock()
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INTENTS, intent["id"]) or intent
            attempts = int(row.get("attempts", 0)) + 1
            state = BLOCKED if attempts >= MAX_ATTEMPTS else row["state"]
            settled = {**row, "attempts": attempts, "state": state, "reason_code": reason_code,
                       "error_type": None, "updated_at": now}
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        LOGGER.warning("fleet backlog item refused plan=%s item=%s reason=%s attempts=%d state=%s",
                       row["plan_id"], row["item_id"], reason_code, attempts, state)
        return {"outcome": OUTCOME_REFUSED, "reason_code": reason_code, "attempts": attempts,
                "item_state": state}

    def _defer(self, intent: dict, reason_code: str, error_type, *, link: bool = False) -> dict:
        """One transient outage of this item's input or of its binding owner.

        It is NOT an attempt: the item is deferred for a bounded, doubling number of ticks, keeps
        its durable intent and stays recoverable after a restart, while every independent eligible
        item keeps being selected. After MAX_DEFERRALS consecutive outages the item stops being
        retried and is handed to the owner with its last failure preserved.
        """
        now, error_type = self.clock(), safe_error_type(error_type)
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_INTENTS, intent["id"]) or intent
            deferrals = int(row.get("deferrals") or 0) + 1
            exhausted = deferrals >= MAX_DEFERRALS
            settled = {**row, "deferrals": deferrals, "error_type": error_type, "updated_at": now,
                       "defer_ticks": 0 if exhausted else defer_ticks_for(deferrals)}
            if link:
                settled["link_state"] = LINK_BLOCKED if exhausted else LINK_PENDING
                settled["link_reason"] = reason_code
            else:
                settled["reason_code"] = reason_code
                if exhausted:
                    settled["state"] = BLOCKED
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        if exhausted:
            LOGGER.warning("fleet backlog item deferral exhausted plan=%s item=%s reason=%s deferrals=%d",
                           settled["plan_id"], settled["item_id"], reason_code, deferrals)
        return {"outcome": OUTCOME_UNAVAILABLE, "reason_code": reason_code, "error_type": error_type,
                "deferrals": deferrals, "item_state": settled["state"], "linked": False,
                "link_state": link_state(settled)}

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
        """The bounded tick receipt: identities, one outcome, a fixed reason code, the linkage and
        a next action. It is a selection receipt, never a completion, review or release receipt."""
        item = decision.get("item")
        result = {"schema": TICK_SCHEMA, "plan_id": decision["plan_id"], "outcome": decision["outcome"],
                  "item_id": None if item is None else item["id"],
                  "lane": None if item is None else item["lane"],
                  "job_id": None, "job_status": None, "cached": None, "reason_code": None,
                  "error_type": None, "item_state": None, "linked": None, "link_state": None,
                  "deferrals": None, "blocked": dict(decision.get("blocked") or {}),
                  "at": decision["at"], "authority": AUTHORITY}
        result.update(overrides)
        result["next_action"] = plan_next_action(result["outcome"])
        return result

    # ----- structured observation ------------------------------------------------------------
    def _observed(self, decision: dict, before: int, **overrides) -> dict:
        """Build the receipt and emit the fixed structured transition for it, if there is one."""
        result = self._result(decision, **overrides)
        self._emit(result, before)
        return result

    def _emit(self, result: dict, before: int) -> None:
        """Identifiers, fixed codes and counts through the existing observation port.

        No manifest, objective, goal text, path, exception message or credential can reach it: the
        attribute allow-list of `domain.observation` is the contract and every value here is an id,
        a fixed code or a count. Repeated polls emit nothing, and a repeated outage emits once per
        run of outages rather than once per tick.
        """
        if self.observer is None or result["outcome"] not in OBSERVED_OUTCOMES:
            return
        common = {"plan_id": result["plan_id"], "item_id": result["item_id"] or "unknown",
                  "lane": result["lane"] or "unknown"}
        outcome, reason = result["outcome"], result["reason_code"]
        if outcome == OUTCOME_ENQUEUED:
            self.observer.emit(EVENT_ADMITTED, "succeeded", attributes={
                **common, "job_id": result["job_id"] or "unknown", "cached": bool(result["cached"]),
                "linked": bool(result["linked"])})
            if before:
                # This item had been deferred; its own recovery is a fact of its own.
                self.observer.emit(EVENT_RECOVERED, "succeeded", attributes={**common, "deferrals": before})
            return
        if outcome == OUTCOME_UNAVAILABLE:
            deferrals = int(result["deferrals"] or 0)
            if deferrals == 1 or deferrals >= MAX_DEFERRALS:
                # The entry into unavailability and its exhaustion are transitions; the ticks in
                # between are not, so a long outage cannot flood the sink.
                self.observer.emit(EVENT_UNAVAILABLE, "unknown", severity="warning", reason_code=reason,
                                   attributes={**common, "error_type": result["error_type"],
                                               "deferrals": deferrals,
                                               "exhausted": deferrals >= MAX_DEFERRALS})
            return
        self.observer.emit(EVENT_REFUSED, "blocked", severity="warning", reason_code=reason,
                           attributes={**common, "outcome": outcome,
                                       "item_state": result["item_state"] or link_state(result),
                                       "attempts": int(result.get("attempts") or 0),
                                       "job_id": result["job_id"]})

    # ----- read-only ----------------------------------------------------------------------
    def status(self, plan_id: str | None = None) -> dict:
        """The durable bounded status of one plan, or of every registered plan. Store reads only:
        no git, process, provider, portfolio or fleet admission happens here."""
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


__all__ = ["BUCKET_INTENTS", "BUCKET_PLANS", "OBSERVED_OUTCOMES", "FleetBacklog", "LOGGER"]
