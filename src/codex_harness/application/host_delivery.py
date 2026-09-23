"""Durable delivery of a reviewed release to an actual host target (INV-HOST-DELIVERY-001).

A bounded coordinator, not a second approval authority and not a second executor. It owns four
buckets over the existing store - `host_delivery_targets` (the owner's authorized host registry),
`host_delivery_plans` (one registered Git-pinned plan per plan id), `host_delivery_intents` (one
durable intent per plan) and `host_delivery_descriptors` (the active descriptor of each target) -
and it reaches everything else through its existing owners:

* `application.releases.Releases` remains the only approval and the only active-release CAS. The
  lead+conductor reviews, the exact revision/tree/evaluator hash and the ticket binding are read
  from ITS record; nothing here writes a review, and `promote` is called only after the prescribed
  checks AND an actual consumption receipt.
* `application.release_queue.ReleaseQueue` remains the fence: one controller on this host at a
  time, with its generation, lease, attempt budget and backoff unchanged. This controller claims
  only the rows a registered plan names.
* The GitHub port publishes and merges through the existing `GitWorkspace` contracts and observes
  the real checks of the exact PR head; the host port owns the descriptor, the drain and the
  process; the canary port is an incumbent fixed check id, never text from a plan.

One tick is a few short store transactions with every external action strictly between them,
because `PostgresStore.transaction` takes `pg_advisory_xact_lock` per transaction and a nested call
would block until `lock_timeout`. No transaction is open across GitHub, the filesystem, a
subprocess or another independently locking transaction, and every durable observation is committed
in the same transaction that re-checks this controller's ownership.

Idempotence follows the durable-intent rule: the intent names the stage BEFORE the external action
of that stage, so a lost response can only reconcile what already happened - an existing PR at the
intended head is adopted, an already merged PR is recognized, and an already consumed descriptor is
recognized - never repeated. A long external wait (CI, startup) does not sleep holding the lease:
the tick answers `pending`, releases the lease through `ReleaseQueue.defer`, and the next bounded
tick resumes the same logical intent under its own durable stage deadline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.releases import Releases
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AUTHORITY,
    AWAITING_CI,
    AWAITING_CONSUMPTION,
    AWAITING_REVIEW,
    BLOCKED,
    CI_FAILED,
    CI_HEAD_CHANGED,
    CI_PASSED,
    CI_PENDING,
    DRAIN_INTENDED,
    EVENT_BLOCKED,
    EVENT_CHECK,
    EVENT_ROLLBACK,
    EVENT_STAGE,
    EVENT_SWITCHED,
    FAILED,
    MAX_STAGE_ATTEMPTS,
    MERGE_INTENDED,
    MERGED,
    OUTCOME_ACTIVE,
    OUTCOME_BLOCKED,
    OUTCOME_BUSY,
    OUTCOME_DISABLED,
    OUTCOME_IDLE,
    OUTCOME_PENDING,
    OUTCOME_PROGRESSED,
    OUTCOME_REFUSED,
    OUTCOME_ROLLED_BACK,
    OUTCOME_UNAVAILABLE,
    OUTCOME_UNREGISTERED,
    PUBLISHING,
    REGISTERED,
    ROLLED_BACK,
    ROLLING_BACK,
    STATUS_SCHEMA,
    STOPPED_STAGES,
    SWITCHING,
    TICK_SCHEMA,
    DeliveryRefused,
    ci_verdict,
    consumption_verdict,
    delivery_status,
    descriptor_digest,
    new_intent,
    plan_digest,
    release_gate,
    resolve_descriptor,
    safe_error_type,
    stage_next_action,
    validate_pin,
    validate_plan,
    validate_targets,
)
from codex_harness.domain.model import ContractError, utcnow

BUCKET_TARGETS = "host_delivery_targets"
BUCKET_PLANS = "host_delivery_plans"
BUCKET_INTENTS = "host_delivery_intents"
BUCKET_DESCRIPTORS = "host_delivery_descriptors"
LOGGER = logging.getLogger("zeus.host.delivery")

# The stages at which another plan on the SAME target is already touching the host. A second plan
# for that target waits rather than racing it; unrelated targets keep moving.
TARGET_BUSY_STAGES = frozenset({DRAIN_INTENDED, SWITCHING, AWAITING_CONSUMPTION, ROLLING_BACK})
# How long a pending external wait asks to be resumed after; the stage deadline in the intent is
# what actually ends the wait.
RESUME_SECONDS = 15


class HostDelivery:
    """One store, the existing release authority and fence, and three injected host-side ports.

    `github`, `hosts` and `canaries` are ports the adapter wires to the real GitHub CLI, the real
    host targets and the incumbent fixed canary checks. Without them a tick cannot act: the missing
    port is reported as `unavailable` with its own reason code, never as an empty success.

    `enabled` is the opt-in: production delivery is off by default, and while it is off a tick
    registers, projects and refuses to touch anything external.
    """

    def __init__(self, store, org=None, *, github=None, hosts=None, canaries=None, clock=utcnow,
                 observer=None, enabled=False, releases=None, queue=None,
                 resume_seconds: int = RESUME_SECONDS):
        self.store, self.org, self.clock = store, org, clock
        self.github, self.hosts, self.canaries = github, hosts or {}, canaries or {}
        self.observer, self.enabled = observer, bool(enabled)
        self.resume_seconds = int(resume_seconds)
        self.releases = releases if releases is not None else Releases(store, org)
        self.queue = queue if queue is not None else ReleaseQueue(store)

    # ----- registry -----------------------------------------------------------------------
    def register_targets(self, document) -> dict:
        """Register the owner's authorized host target registry; the identical document is cached."""
        registry = validate_targets(document)
        now = self.clock()
        with self.store.transaction() as tx:
            for target in registry["targets"]:
                old = tx.get(BUCKET_TARGETS, target["target_id"]) or {}
                tx.put(BUCKET_TARGETS, target["target_id"],
                       {"id": target["target_id"], **target,
                        "registered_at": old.get("registered_at") or now, "updated_at": now})
        return {"registered": True, "targets": [t["target_id"] for t in registry["targets"]],
                "authority": AUTHORITY}

    def register(self, document, pin) -> dict:
        """Register one validated delivery plan read at an explicit commit.

        The target must already exist in the owner's registry, so a plan can never introduce one.
        The identical plan at the identical pin is cached. A plan whose delivery has already left
        `registered` may not be edited at all: a changed release, revision, tree, evaluator hash,
        target or descriptor refuses the whole registration and writes nothing, so no in-flight
        delivery is ever re-pointed at another candidate.
        """
        plan = validate_plan(document)
        pin = validate_pin(pin)
        sha, now = plan_digest(plan), self.clock()
        with self.store.transaction() as tx:
            if tx.get(BUCKET_TARGETS, plan["target_id"]) is None:
                raise DeliveryRefused("target_unregistered", "target_id")
            old = tx.get(BUCKET_PLANS, plan["plan_id"])
            intent = tx.get(BUCKET_INTENTS, plan["plan_id"])
            if old is not None:
                if old["plan_sha256"] == sha and old["pin"] == pin:
                    return {"registered": True, "cached": True, "plan_id": plan["plan_id"],
                            "plan_sha256": sha, "pin": pin, "target_id": plan["target_id"],
                            "release_id": plan["release_id"], "authority": AUTHORITY}
                if intent is not None and intent.get("stage") != REGISTERED:
                    raise DeliveryRefused("delivery_in_flight", "plan_id")
            row = {"id": plan["plan_id"], "plan_id": plan["plan_id"], "plan": plan,
                   "plan_sha256": sha, "pin": pin, "target_id": plan["target_id"],
                   "registered_at": (old or {}).get("registered_at") or now, "updated_at": now}
            tx.put(BUCKET_PLANS, plan["plan_id"], row)
        return {"registered": True, "cached": False, "plan_id": plan["plan_id"], "plan_sha256": sha,
                "pin": pin, "target_id": plan["target_id"], "release_id": plan["release_id"],
                "authority": AUTHORITY}

    def plan(self, plan_id: str):
        with self.store.transaction() as tx:
            return tx.get(BUCKET_PLANS, plan_id)

    def status(self, plan_id: str | None = None) -> dict:
        """The durable bounded projection of one plan or of every registered plan. Store reads only:
        no git, GitHub, process, descriptor file, provider or host observation happens here."""
        with self.store.transaction() as tx:
            rows = (tx.scan(BUCKET_PLANS) if plan_id is None
                    else [row for row in [tx.get(BUCKET_PLANS, plan_id)] if row])
            intents = {row["plan_id"]: row for row in tx.scan(BUCKET_INTENTS)}
            descriptors = {row["target_id"]: row for row in tx.scan(BUCKET_DESCRIPTORS)}
        if plan_id is not None and not rows:
            return {"schema": STATUS_SCHEMA, "plan_id": plan_id, "registered": False,
                    "enabled": self.enabled, "outcome": OUTCOME_UNREGISTERED, "deliveries": [],
                    "next_action": "register_plan", "targets": sorted(descriptors),
                    "authority": AUTHORITY}
        return delivery_status(rows, intents, descriptors, enabled=self.enabled)

    # ----- one bounded tick ------------------------------------------------------------------
    def tick(self, plan_id: str | None = None) -> dict:
        """Advance at most ONE delivery by at most one stage, under the existing release fence."""
        try:
            selection = self._select(plan_id, create=self.enabled)
        except Exception as exc:
            # The durable state itself cannot be read. That is an explicit outage with its
            # exception TYPE, never an idle poll and never an invented cause.
            return self._result(None, None, OUTCOME_UNAVAILABLE, reason_code="store_unavailable",
                                error_type=safe_error_type(type(exc).__name__))
        if selection["plan"] is None:
            return self._result(None, None, selection["outcome"], blocked=selection["blocked"],
                                reason_code=selection.get("reason_code"))
        row, intent = selection["plan"], selection["intent"]
        plan = row["plan"]
        if not self.enabled:
            # Registration, reconciliation and projection stay available; nothing external happens.
            return self._result(plan, intent, OUTCOME_DISABLED, reason_code="delivery_disabled")
        gate = self._gate(plan)
        if gate["state"] == OUTCOME_REFUSED:
            return self._halt(plan, intent, BLOCKED, OUTCOME_REFUSED, gate["reason_code"])
        if gate["state"] == AWAITING_REVIEW:
            # A registered plan whose review is not complete PROJECTS the wait; it never runs, and
            # no queue row, PR, merge or host change is created for it.
            return self._await_review(plan, intent, gate["reason_code"])
        try:
            self.queue.enqueue(plan["release_id"], "host delivery plan " + plan["plan_id"])
            # This controller's own clock drives its fence too, so a lease, a backoff and a stage
            # deadline are never read from two different times.
            claim = self.queue.claim(now=self._now(),
                                     eligible=lambda queued: queued["id"] == plan["release_id"])
        except ContractError as exc:
            return self._halt(plan, intent, BLOCKED, OUTCOME_REFUSED, "queue_refused",
                              error_type=type(exc).__name__)
        except Exception as exc:  # the store itself is unreachable: an outage, not a verdict
            return self._unavailable(plan, intent, "queue_unavailable", exc, commit=False)
        if claim is None:
            # Why this tick got nothing is an operational fact of its own: another controller holds
            # the single host lease, or this release's own queue row is no longer runnable.
            with self.store.transaction() as tx:
                status = (tx.get("release_queue", plan["release_id"]) or {}).get("status")
            reason = ("controller_lease_held" if status in {"queued", "retry", "running"}
                      else "release_queue_" + str(status))
            return self._result(plan, intent, OUTCOME_BUSY, reason_code=reason)
        try:
            result = self._advance(row, intent, claim)
        except ContractError as refusal:
            # A definite contract refusal of this stage; a fence that moved underneath it cannot be
            # recorded either, and says so instead of raising over what was already observed. The
            # exception is bound to a local because `except ... as` unbinds its own name on exit.
            failure = refusal
            result = self._guard(plan, intent, OUTCOME_REFUSED, lambda: self._halt(
                plan, intent, BLOCKED, OUTCOME_REFUSED,
                getattr(failure, "reason_code", None) or "contract_refused",
                error_type=type(failure).__name__, claim=claim))
        except Exception as outage:
            failure = outage
            result = self._guard(plan, intent, OUTCOME_UNAVAILABLE, lambda: self._unavailable(
                plan, intent, "stage_unavailable", failure, claim=claim))
        self._settle(claim, result)
        return result

    def _guard(self, plan: dict, intent: dict, outcome: str, record) -> dict:
        """Record a stop, or report that this controller no longer owns what it observed."""
        try:
            return record()
        except ContractError as exc:
            return {**self._result(plan, intent, outcome, reason_code="controller_stale",
                                   error_type=type(exc).__name__), "controller": "stale"}

    def _settle(self, claim, result: dict) -> None:
        """Release the fence: a bounded external wait defers, everything else finishes.

        A stale controller cannot commit this either; its own ownership error is recorded on the
        receipt rather than raised over the result that was already observed.
        """
        outcome, now = result["outcome"], self._now()
        try:
            if outcome == OUTCOME_PENDING:
                self.queue.defer(claim, {"status": "pending", "stage": result["stage"],
                                         "reason": result["reason_code"]},
                                 resume_after_seconds=self.resume_seconds, now=now)
            elif outcome == OUTCOME_UNAVAILABLE:
                self.queue.finish(claim, {"status": "retry", "reason": result["reason_code"]}, now)
            elif outcome in {OUTCOME_BLOCKED, OUTCOME_REFUSED}:
                self.queue.finish(claim, {"status": "blocked", "reason": result["reason_code"]}, now)
            elif outcome == OUTCOME_ROLLED_BACK:
                self.queue.finish(claim, {"status": "rolled_back",
                                          "reason": result["reason_code"]}, now)
            elif outcome == OUTCOME_ACTIVE:
                self.queue.finish(claim, {"status": "active", "release_id": result["release_id"]}, now)
            else:
                self.queue.defer(claim, {"status": "progressed", "stage": result["stage"]},
                                 resume_after_seconds=0, now=now)
        except ContractError as exc:
            result["controller"] = "stale"
            result["error_type"] = type(exc).__name__

    def _select(self, plan_id: str | None, *, create: bool = True) -> dict:
        """Transaction 1: the one plan this tick may work on, and why every other one waits.

        `create` is the opt-in: while delivery is disabled the selection is a pure read and not
        even a durable intent is written, so an unaccepted host stays exactly as it was.
        """
        now = self.clock()
        with self.store.transaction() as tx:
            rows = (tx.scan(BUCKET_PLANS) if plan_id is None
                    else [row for row in [tx.get(BUCKET_PLANS, plan_id)] if row])
            if not rows:
                return {"plan": None, "intent": None, "blocked": {},
                        "outcome": OUTCOME_UNREGISTERED if plan_id else OUTCOME_IDLE}
            intents = {row["plan_id"]: row for row in tx.scan(BUCKET_INTENTS)}
            busy = {intent["target_id"] for intent in intents.values()
                    if intent.get("stage") in TARGET_BUSY_STAGES}
            blocked, chosen, chosen_intent = {}, None, None
            for row in sorted(rows, key=lambda r: r["plan_id"]):
                intent = intents.get(row["plan_id"])
                stage = (intent or {}).get("stage") or REGISTERED
                if stage == ACTIVE or stage in STOPPED_STAGES:
                    blocked[row["plan_id"]] = stage
                    continue
                if chosen is None and row["target_id"] in busy and stage not in TARGET_BUSY_STAGES:
                    blocked[row["plan_id"]] = "target_busy"
                    continue
                if chosen is None:
                    chosen, chosen_intent = row, intent
                else:
                    blocked[row["plan_id"]] = "controller_serialized"
            if chosen is None:
                return {"plan": None, "intent": None, "blocked": blocked, "outcome": OUTCOME_IDLE}
            if chosen_intent is None:
                # The durable intent exists before anything else does, including the queue row.
                chosen_intent = new_intent(chosen["plan"], chosen["plan_sha256"], now)
                if create:
                    tx.put(BUCKET_INTENTS, chosen_intent["id"], chosen_intent)
        return {"plan": chosen, "intent": chosen_intent, "blocked": blocked, "outcome": OUTCOME_PROGRESSED}

    def _gate(self, plan: dict) -> dict:
        """What the EXISTING release record says about this plan. This never writes anything."""
        with self.store.transaction() as tx:
            record = tx.get("releases", plan["release_id"])
        return release_gate(record, plan, self._parent(record))

    def _parent(self, record) -> str | None:
        """The candidate author's own lead, from the existing organization; unknown stays None."""
        author = (record or {}).get("candidate", {}).get("author")
        if self.org is None or not isinstance(author, str):
            return None
        try:
            return self.org.actor(author).parent
        except Exception:
            return None

    # ----- the stages -------------------------------------------------------------------------
    def _advance(self, row: dict, intent: dict, claim) -> dict:
        plan, stage = row["plan"], intent["stage"]
        if stage in {REGISTERED, AWAITING_REVIEW}:
            return self._enter(plan, intent, PUBLISHING, claim)
        if stage == PUBLISHING:
            return self._publish(plan, intent, claim)
        if stage == AWAITING_CI:
            return self._observe_ci(plan, intent, claim)
        if stage == MERGE_INTENDED:
            return self._merge(plan, intent, claim)
        if stage == MERGED:
            return self._prepare_switch(plan, intent, claim)
        if stage == DRAIN_INTENDED:
            return self._drain(plan, intent, claim)
        if stage == SWITCHING:
            return self._switch(plan, intent, claim)
        if stage == AWAITING_CONSUMPTION:
            return self._consume(plan, intent, claim)
        if stage == ROLLING_BACK:
            return self._rollback(plan, intent, claim)
        return self._result(plan, intent, OUTCOME_IDLE, reason_code="stage_terminal")

    def _publish(self, plan: dict, intent: dict, claim) -> dict:
        """Publish the reviewed candidate, or ADOPT the publication a lost response already made."""
        port = self._require_port(self.github, "github_port_unavailable")
        candidate = self._candidate(plan)
        observed = port.observe(candidate)
        if observed is None:
            observed = port.publish(candidate)
        head = (observed or {}).get("head")
        if head != plan["revision"]:
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publish_head_mismatch",
                              claim=claim)
        deadline = self._deadline(plan["ci_timeout_seconds"])
        return self._enter(plan, intent, AWAITING_CI, claim, head=head,
                           pr_number=observed.get("number"), pr_url=observed.get("url"),
                           stage_deadline=deadline)

    def _observe_ci(self, plan: dict, intent: dict, claim) -> dict:
        """The REAL checks of the exact intended head; nothing else is evidence that CI passed."""
        port = self._require_port(self.github, "github_port_unavailable")
        candidate = self._candidate(plan)
        observed = port.observe(candidate)
        if observed is None:
            # The publication this intent recorded is gone: that is a definite refusal to merge, not
            # a reason to publish a second time under the same intent.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publication_missing", claim=claim)
        verdict = ci_verdict(plan["required_checks"], observed.get("checks"), intent["head"],
                             observed_head=observed.get("head"))
        self._emit_check(plan, intent, AWAITING_CI, verdict)
        if verdict["state"] == CI_PASSED:
            return self._enter(plan, intent, MERGE_INTENDED, claim, stage_deadline=None,
                               last_check_state=CI_PASSED)
        if verdict["state"] == CI_FAILED:
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, verdict["reason_code"],
                              claim=claim, last_check_state=CI_FAILED)
        if verdict["state"] == CI_HEAD_CHANGED:
            # A moved head goes to requalification; it is never rebased into the old acceptance.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "ci_head_changed", claim=claim,
                              last_check_state=CI_HEAD_CHANGED)
        if self._expired(intent):
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "ci_timeout", claim=claim,
                              last_check_state=CI_PENDING)
        return self._pending(plan, intent, claim, verdict["reason_code"], last_check_state=CI_PENDING)

    def _merge(self, plan: dict, intent: dict, claim) -> dict:
        """Merge the exact reviewed head, or RECOGNIZE the merge a lost response already made."""
        port = self._require_port(self.github, "github_port_unavailable")
        candidate = self._candidate(plan)
        observed = port.observe(candidate)
        if observed is None:
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publication_missing", claim=claim)
        if observed.get("head") != intent["head"]:
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "ci_head_changed", claim=claim)
        if observed.get("state") == "MERGED":
            merged = {"merged": True, "merged_revision": observed.get("merged_revision")
                      or intent["head"], "recovered": True}
        else:
            merged = port.merge(candidate)
        return self._enter(plan, intent, MERGED, claim,
                           merged_revision=merged.get("merged_revision") or intent["head"])

    def _prepare_switch(self, plan: dict, intent: dict, claim) -> dict:
        """Bind the exact target tuple this delivery will switch to, before touching the host.

        The verified release, the registered target, the current descriptor and the plan's expected
        predecessor must all agree here; the resolved descriptor and the active-release CAS value
        are written durably, so the switch, a replay of it and a rollback all act on one identity.
        """
        gate = self._gate(plan)
        if gate["status"] not in {"verified", "active"}:
            # The incumbent checks of this candidate are the evaluator's, not this controller's.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "release_not_verified", claim=claim)
        with self.store.transaction() as tx:
            target = tx.get(BUCKET_TARGETS, plan["target_id"])
            current_row = tx.get(BUCKET_DESCRIPTORS, plan["target_id"])
            active = tx.get("deployment", "active") or {}
        if target is None:
            return self._halt(plan, intent, BLOCKED, OUTCOME_REFUSED, "target_unregistered", claim=claim)
        current = (current_row or {}).get("descriptor")
        current_sha = None if current is None else descriptor_digest(current)
        if plan["expected_descriptor"] != current_sha:
            # The host is not where the owner approved this switch from.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "descriptor_predecessor_mismatch",
                              claim=claim)
        descriptor = resolve_descriptor(target, plan, current)
        return self._enter(plan, intent, DRAIN_INTENDED, claim, descriptor=descriptor,
                           descriptor_sha256=descriptor_digest(descriptor),
                           previous_descriptor=current, previous_descriptor_sha256=current_sha,
                           previous_instance_id=(current_row or {}).get("instance_id"),
                           expected_active=active.get("release_id"), expected_active_set=True,
                           stage_deadline=self._deadline(plan["consumption_timeout_seconds"]))

    def _drain(self, plan: dict, intent: dict, claim) -> dict:
        """Pause new admission and prove the target drained; an unconfirmed effect blocks the switch."""
        host, target = self._host(plan)
        observed = host.drain(target)
        if observed.get("unconfirmed"):
            # Unknown work is not finished work: this never kills active model work to deploy.
            if self._expired(intent):
                return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "drain_unconfirmed_effects",
                                  claim=claim)
            return self._pending(plan, intent, claim, "drain_unconfirmed_effects")
        if not observed.get("drained"):
            if self._expired(intent):
                return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "drain_timeout", claim=claim)
            return self._pending(plan, intent, claim, "drain_pending")
        return self._enter(plan, intent, SWITCHING, claim,
                           stage_deadline=self._deadline(plan["consumption_timeout_seconds"]))

    def _switch(self, plan: dict, intent: dict, claim) -> dict:
        """Replace the immutable descriptor atomically and start the service exactly once.

        Both halves are reconciled before they are repeated, because a tick that lost its response
        after writing the descriptor or after starting the process must not write a second one or
        start a second instance: the descriptor that is already there is compared to the intended
        one, and a process that is already running and already reports this exact descriptor is
        recognized instead of restarted.
        """
        host, target = self._host(plan)
        descriptor = intent["descriptor"]
        current = host.current(target)
        if current is not None and descriptor_digest(current) == intent["descriptor_sha256"]:
            switched = {"written": False, "recovered": True}
        else:
            switched = host.switch(target, descriptor, expected=intent["previous_descriptor_sha256"])
        running = consumption_verdict(descriptor, host.receipt(target),
                                      expected_instance=intent.get("previous_instance_id"))
        if running["consumed"] and host.running(target):
            started = {"started": False, "recovered": True}
        else:
            started = host.start(target, descriptor)
        self._record_descriptor(plan, intent, descriptor, consumed=False,
                                instance_id=None, claim=claim)
        self._emit(EVENT_SWITCHED, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "target_id": plan["target_id"],
            "descriptor_sha256": intent["descriptor_sha256"],
            "previous_sha256": intent["previous_descriptor_sha256"], "instance_id": None,
            "consumed": False})
        return self._enter(plan, intent, AWAITING_CONSUMPTION, claim,
                           switch={"at": self.clock(), "written": bool(switched.get("written")),
                                   "started": bool(started.get("started")),
                                   "recovered": bool(switched.get("recovered")
                                                     or started.get("recovered"))},
                           stage_deadline=self._deadline(plan["consumption_timeout_seconds"]))

    def _consume(self, plan: dict, intent: dict, claim) -> dict:
        """The launched process's OWN startup evidence decides activation; a switch alone does not."""
        host, target = self._host(plan)
        descriptor = intent["descriptor"]
        verdict = consumption_verdict(descriptor, host.receipt(target),
                                      expected_instance=intent.get("previous_instance_id"))
        if not verdict["consumed"]:
            if verdict["reason_code"] in {"receipt_missing", "receipt_stale_instance"} \
                    and not self._expired(intent):
                return self._pending(plan, intent, claim, verdict["reason_code"])
            # A wrong receipt never grants activation, and an expired wait is not an unknown that
            # can be waited out: the exact predecessor is restored.
            return self._begin_rollback(plan, intent, claim, verdict["reason_code"])
        canary = self._canary(plan, target, descriptor)
        # A canary state of its own, so a passed canary is never mistaken for the CI verdict that
        # preceded it and neither one suppresses the other's transition.
        self._emit_check(plan, intent, AWAITING_CONSUMPTION,
                         {"state": "canary_passed" if canary["passed"] else "canary_failed",
                          "reason_code": canary.get("reason_code"), "missing": [], "failed": [],
                          "pending": []}, canary_passed=bool(canary["passed"]))
        if not canary["passed"]:
            return self._begin_rollback(plan, intent, claim, canary.get("reason_code") or "canary_failed",
                                        canary=canary)
        self._record_descriptor(plan, intent, descriptor, consumed=True,
                                instance_id=verdict["instance_id"], claim=claim)
        self._emit(EVENT_SWITCHED, "succeeded", plan, attributes={
            "plan_id": plan["plan_id"], "target_id": plan["target_id"],
            "descriptor_sha256": intent["descriptor_sha256"],
            "previous_sha256": intent["previous_descriptor_sha256"],
            "instance_id": verdict["instance_id"], "consumed": True})
        pointer = self._promote(plan, intent)
        LOGGER.info("host delivery active plan=%s release=%s target=%s descriptor=%s instance=%s",
                    plan["plan_id"], plan["release_id"], plan["target_id"],
                    intent["descriptor_sha256"], verdict["instance_id"])
        return self._enter(plan, intent, ACTIVE, claim, outcome=OUTCOME_ACTIVE,
                           instance_id=verdict["instance_id"], canary=canary, stage_deadline=None,
                           active_pointer=pointer)

    def _promote(self, plan: dict, intent: dict) -> dict | None:
        """Move the existing release pointer through `Releases`, with ITS compare-and-swap.

        The expected active release is the one recorded when this delivery bound its target tuple,
        so a pointer that moved in between refuses here instead of overwriting another activation.
        A release this promotion already made active is recognized rather than promoted twice.
        """
        with self.store.transaction() as tx:
            record = tx.get("releases", plan["release_id"]) or {}
            active = tx.get("deployment", "active") or {}
        if record.get("status") == "active" and active.get("release_id") == plan["release_id"]:
            return active
        return self.releases.promote(plan["release_id"], intent.get("expected_active"))

    def _begin_rollback(self, plan: dict, intent: dict, claim, reason_code: str, canary=None) -> dict:
        if intent.get("previous_descriptor") is None:
            # There is no known-good predecessor for this target: nothing may be restored, and the
            # delivery stops where it is rather than inventing a state to return to.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "no_known_good_predecessor",
                              claim=claim, rollback={"requested": True, "restored": False,
                                                     "verified": False, "reason_code": reason_code},
                              **({"canary": canary} if canary is not None else {}))
        # Progress toward the restoration, not a stop: the fence is deferred rather than finished,
        # so the very next bounded tick performs the rollback instead of waiting for an owner.
        return self._enter(plan, intent, ROLLING_BACK, claim, outcome=OUTCOME_PROGRESSED,
                           reason_code=reason_code, canary=canary,
                           rollback={"requested": True, "restored": False, "verified": False,
                                     "reason_code": reason_code},
                           stage_deadline=self._deadline(plan["consumption_timeout_seconds"]))

    def _rollback(self, plan: dict, intent: dict, claim) -> dict:
        """Restore the EXACT predecessor tuple, then PROVE the restored runtime is the one running.

        The restoration and its proof are two bounded steps of the same stage, exactly like the
        forward switch: nothing sleeps under the lease, the predecessor's own startup receipt and a
        live process are what verify it, and a restoration that cannot be proven becomes a blocked
        operational alert rather than a `rolled_back` claim.
        """
        host, target = self._host(plan)
        previous = intent["previous_descriptor"]
        record = dict(intent.get("rollback") or {})
        reason = record.get("reason_code") or "rollback"
        if not record.get("restored"):
            try:
                host.switch(target, previous, expected=intent["descriptor_sha256"])
                host.start(target, previous)
            except Exception as exc:
                error_type = safe_error_type(type(exc).__name__)
                record.update(restored=False, verified=False, error_type=error_type,
                              at=self.clock())
                return self._blocked_rollback(plan, intent, claim, record, "rollback_failed")
            record.update(restored=True, verified=False, error_type=None, at=self.clock())
            return self._pending(plan, intent, claim, "rollback_awaiting_consumption",
                                 rollback=record,
                                 stage_deadline=self._deadline(plan["consumption_timeout_seconds"]))
        try:
            verdict = consumption_verdict(previous, host.receipt(target))
            alive = bool(host.running(target))
            error_type = None
        except Exception as exc:
            verdict, alive = {"consumed": False, "instance_id": None}, False
            error_type = safe_error_type(type(exc).__name__)
        if not (verdict["consumed"] and alive):
            record.update(verified=False, error_type=error_type)
            if not self._expired(intent):
                return self._pending(plan, intent, claim, "rollback_awaiting_consumption",
                                     rollback=record)
            return self._blocked_rollback(plan, intent, claim, record, "rollback_unverified")
        record.update(verified=True, error_type=None, at=self.clock())
        self._emit(EVENT_ROLLBACK, "succeeded", plan, severity="warning", reason_code=reason,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "descriptor_sha256": intent["previous_descriptor_sha256"],
                               "restored": True, "verified": True, "error_type": None})
        self._record_descriptor(plan, intent, previous, consumed=True,
                                instance_id=verdict.get("instance_id"), claim=claim,
                                rolled_back=True)
        LOGGER.warning("host delivery rolled back plan=%s target=%s descriptor=%s reason=%s",
                       plan["plan_id"], plan["target_id"], intent["previous_descriptor_sha256"], reason)
        return self._enter(plan, intent, ROLLED_BACK, claim, outcome=OUTCOME_ROLLED_BACK,
                           reason_code=reason, rollback=record, stage_deadline=None)

    def _blocked_rollback(self, plan: dict, intent: dict, claim, record: dict,
                          reason_code: str) -> dict:
        """A failed or unproven restoration: a critical operations alert, never a rolled-back claim."""
        self._emit(EVENT_ROLLBACK, "blocked", plan, severity="critical", reason_code=reason_code,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "descriptor_sha256": intent["previous_descriptor_sha256"],
                               "restored": bool(record.get("restored")), "verified": False,
                               "error_type": record.get("error_type")})
        return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, reason_code, claim=claim,
                          error_type=record.get("error_type"), rollback=record)

    # ----- ports ------------------------------------------------------------------------------
    @staticmethod
    def _require_port(port, reason_code: str):
        if port is None:
            raise DeliveryRefused(reason_code)
        return port

    def _host(self, plan: dict):
        with self.store.transaction() as tx:
            target = tx.get(BUCKET_TARGETS, plan["target_id"])
        if target is None:
            raise DeliveryRefused("target_unregistered", "target_id")
        host = self.hosts.get(target["kind"])
        if host is None:
            raise DeliveryRefused("host_port_unavailable", "kind")
        return host, target

    def _candidate(self, plan: dict) -> dict:
        """The reviewed candidate record itself; the plan never supplies a branch, a title or a body."""
        with self.store.transaction() as tx:
            record = tx.get("releases", plan["release_id"])
        if not record or not record.get("candidate"):
            raise DeliveryRefused("release_missing", "release_id")
        return record["candidate"]

    def _canary(self, plan: dict, target: dict, descriptor: dict) -> dict:
        """The incumbent fixed check named by id; a plan can never supply the check itself."""
        check = self.canaries.get(plan["canary_check_id"])
        if check is None:
            return {"passed": False, "reason_code": "canary_unavailable", "evidence": None,
                    "check_id": plan["canary_check_id"]}
        try:
            result = check(target, descriptor)
        except Exception as exc:
            return {"passed": False, "reason_code": "canary_error", "evidence": None,
                    "error_type": safe_error_type(type(exc).__name__),
                    "check_id": plan["canary_check_id"]}
        return {"passed": bool(result.get("passed")), "evidence": result.get("evidence"),
                "reason_code": result.get("reason_code"), "check_id": plan["canary_check_id"]}

    # ----- durable bookkeeping ----------------------------------------------------------------
    def _enter(self, plan: dict, intent: dict, stage: str, claim, *, outcome=None, reason_code=None,
               error_type=None, active_pointer=None, **fields) -> dict:
        """Write the durable intent for the stage that is now owed, and report this tick."""
        now = self.clock()
        settled = {**intent, **fields, "stage": stage, "previous_stage": intent["stage"],
                   "outcome": outcome or (OUTCOME_ACTIVE if stage == ACTIVE else OUTCOME_PROGRESSED),
                   "reason_code": reason_code, "error_type": error_type, "attempts": 0,
                   "stage_entered_at": now if stage != intent["stage"] else intent["stage_entered_at"],
                   "updated_at": now}
        self._write(settled, claim)
        if stage != intent["stage"]:
            self._emit(EVENT_STAGE, "observed", plan, attributes={
                "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": stage, "previous_stage": intent["stage"]})
        return self._result(plan, settled, settled["outcome"], reason_code=reason_code,
                            active=active_pointer)

    def _pending(self, plan: dict, intent: dict, claim, reason_code: str, **fields) -> dict:
        """A bounded external wait: the lease goes back, the stage and its deadline do not move."""
        now = self.clock()
        settled = {**intent, **fields, "outcome": OUTCOME_PENDING, "reason_code": reason_code,
                   "error_type": None, "updated_at": now}
        self._write(settled, claim)
        return self._result(plan, settled, OUTCOME_PENDING, reason_code=reason_code)

    def _halt(self, plan: dict, intent: dict, stage: str, outcome: str, reason_code: str, *,
              claim=None, error_type=None, **fields) -> dict:
        """A definite stop that PRESERVES the stage it happened at, its evidence and its reason."""
        now = self.clock()
        attempts = int(intent.get("attempts") or 0) + 1
        final = FAILED if attempts >= MAX_STAGE_ATTEMPTS and stage == BLOCKED else stage
        settled = {**intent, **fields, "stage": final, "previous_stage": intent["stage"],
                   "outcome": outcome, "reason_code": reason_code,
                   "error_type": safe_error_type(error_type), "attempts": attempts,
                   "updated_at": now}
        self._write(settled, claim)
        self._emit(EVENT_BLOCKED, "blocked", plan, severity="error", reason_code=reason_code,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "stage": intent["stage"], "outcome": outcome,
                               "error_type": settled["error_type"], "attempts": attempts})
        LOGGER.warning("host delivery halted plan=%s stage=%s reason=%s attempts=%d",
                       plan["plan_id"], intent["stage"], reason_code, attempts)
        return self._result(plan, settled, outcome, reason_code=reason_code)

    def _unavailable(self, plan: dict, intent: dict, reason_code: str, exc, *, claim=None,
                     commit: bool = True) -> dict:
        """An outage of the store, of GitHub or of the host: the exception TYPE only, never text."""
        error_type = safe_error_type(type(exc).__name__)
        settled = {**intent, "outcome": OUTCOME_UNAVAILABLE, "reason_code": reason_code,
                   "error_type": error_type, "updated_at": self.clock()}
        if commit:
            try:
                self._write(settled, claim)
            except Exception:
                # The store is what is unavailable; the outage is still reported honestly.
                pass
        LOGGER.warning("host delivery unavailable plan=%s stage=%s reason=%s error=%s",
                       plan["plan_id"], intent["stage"], reason_code, error_type)
        return self._result(plan, settled, OUTCOME_UNAVAILABLE, reason_code=reason_code,
                            error_type=error_type)

    def _write(self, intent: dict, claim) -> None:
        """Commit one durable observation in the SAME transaction that re-checks the fence."""
        with self.store.transaction() as tx:
            if claim is not None:
                self.queue.owned(tx, claim, self._now())
            tx.put(BUCKET_INTENTS, intent["id"], intent)

    def _record_descriptor(self, plan: dict, intent: dict, descriptor: dict, *, consumed: bool,
                           instance_id, claim, rolled_back: bool = False) -> None:
        """The host's active descriptor per target, recorded after the host itself moved."""
        now = self.clock()
        with self.store.transaction() as tx:
            if claim is not None:
                self.queue.owned(tx, claim, self._now())
            old = tx.get(BUCKET_DESCRIPTORS, plan["target_id"]) or {}
            history = list(old.get("history") or [])[-9:]
            if old.get("descriptor_sha256") and old.get("descriptor_sha256") != descriptor_digest(descriptor):
                history.append({"descriptor_sha256": old["descriptor_sha256"], "at": old.get("updated_at"),
                                "consumed": bool(old.get("consumed"))})
            tx.put(BUCKET_DESCRIPTORS, plan["target_id"], {
                "id": plan["target_id"], "target_id": plan["target_id"], "descriptor": descriptor,
                "descriptor_sha256": descriptor_digest(descriptor), "consumed": bool(consumed),
                "instance_id": instance_id, "plan_id": plan["plan_id"],
                "release_id": plan["release_id"], "rolled_back": bool(rolled_back),
                "history": history, "updated_at": now})

    def _await_review(self, plan: dict, intent: dict, reason_code: str) -> dict:
        now = self.clock()
        settled = {**intent, "stage": AWAITING_REVIEW, "previous_stage": intent["stage"],
                   "outcome": OUTCOME_PENDING, "reason_code": reason_code, "updated_at": now,
                   "stage_entered_at": now if intent["stage"] != AWAITING_REVIEW
                   else intent["stage_entered_at"]}
        # No claim here on purpose: a plan awaiting its independent review never takes the release
        # controller lease and never spends an attempt of it.
        self._write(settled, None)
        if intent["stage"] != AWAITING_REVIEW:
            self._emit(EVENT_STAGE, "observed", plan, attributes={
                "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": AWAITING_REVIEW,
                "previous_stage": intent["stage"]})
        return self._result(plan, settled, OUTCOME_PENDING, reason_code=reason_code)

    # ----- time --------------------------------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.fromisoformat(self.clock())

    def _deadline(self, seconds: int) -> str:
        return (self._now() + timedelta(seconds=int(seconds))).isoformat()

    def _expired(self, intent: dict) -> bool:
        deadline = intent.get("stage_deadline")
        if not deadline:
            return False
        try:
            return self._now() >= datetime.fromisoformat(deadline)
        except (TypeError, ValueError):
            return False

    # ----- receipts and structured observation --------------------------------------------------
    def _result(self, plan, intent, outcome: str, *, reason_code=None, error_type=None,
                blocked=None, active=None) -> dict:
        """The bounded tick receipt: identities, digests, one outcome and a fixed reason code."""
        stage = (intent or {}).get("stage") or REGISTERED
        return {"schema": TICK_SCHEMA, "plan_id": (plan or {}).get("plan_id"),
                "release_id": (plan or {}).get("release_id"), "target_id": (plan or {}).get("target_id"),
                "outcome": outcome, "stage": stage if plan is not None else None,
                "reason_code": reason_code if reason_code is not None else (intent or {}).get("reason_code"),
                "error_type": error_type if error_type is not None else (intent or {}).get("error_type"),
                "head": (intent or {}).get("head"), "pr_number": (intent or {}).get("pr_number"),
                "merged_revision": (intent or {}).get("merged_revision"),
                "descriptor_sha256": (intent or {}).get("descriptor_sha256"),
                "previous_descriptor_sha256": (intent or {}).get("previous_descriptor_sha256"),
                "instance_id": (intent or {}).get("instance_id"),
                "canary": (intent or {}).get("canary"), "rollback": (intent or {}).get("rollback"),
                "active": active, "attempts": int((intent or {}).get("attempts") or 0),
                "blocked": dict(blocked or {}), "at": self.clock(),
                "next_action": stage_next_action(stage, outcome), "authority": AUTHORITY}

    def _emit(self, event_type: str, outcome: str, plan, *, attributes: dict, severity="info",
              reason_code=None) -> None:
        if self.observer is None:
            return
        self.observer.emit(event_type, outcome, severity=severity, reason_code=reason_code,
                           attributes=attributes)

    def _emit_check(self, plan: dict, intent: dict, stage: str, verdict: dict,
                    canary_passed=None) -> None:
        """One evidence-stage transition. A repeated poll with the SAME verdict emits nothing."""
        if self.observer is None or verdict["state"] == intent.get("last_check_state"):
            return
        self._emit(EVENT_CHECK, "observed" if verdict["state"] in {CI_PENDING} else
                   "succeeded" if verdict["state"] == CI_PASSED else "failed", plan,
                   severity="info" if verdict["state"] in {CI_PASSED, CI_PENDING} else "warning",
                   reason_code=verdict.get("reason_code"),
                   attributes={"plan_id": plan["plan_id"], "release_id": plan["release_id"],
                               "stage": stage, "check_state": verdict["state"],
                               "required": len(plan["required_checks"]),
                               "missing": len(verdict.get("missing") or []),
                               "pending": len(verdict.get("pending") or []),
                               "failed": len(verdict.get("failed") or []),
                               "canary_passed": canary_passed})


__all__ = ["BUCKET_DESCRIPTORS", "BUCKET_INTENTS", "BUCKET_PLANS", "BUCKET_TARGETS", "LOGGER",
           "RESUME_SECONDS", "TARGET_BUSY_STAGES", "HostDelivery"]
