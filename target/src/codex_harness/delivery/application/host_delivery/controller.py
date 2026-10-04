"""One bounded delivery tick.

Layer: application
Context: delivery
Owns: no bucket of its own (the intent writes through DeliveryState)
Does not own: the stage effects (the stage objects), review's releases and release_queue rows (the ReleaseAuthority/ReleaseClaims/ReleaseSettlement ports)
Entry points: DeliveryController
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_INTENTS,
    BUCKET_MIGRATIONS,
    BUCKET_PLANS,
    LOGGER,
    MAX_SCAN,
    RESUME_SECONDS,
    TARGET_BUSY_STAGES,
    AmbiguousEffect,
)
from codex_harness.delivery.domain.host_delivery import (
    ACTIVE,
    AWAITING_CI,
    AWAITING_CONSUMPTION,
    AWAITING_REVIEW,
    BLOCKED,
    DRAIN_INTENDED,
    MERGE_INTENDED,
    MERGED,
    MIGRATION_RESERVING,
    OUTCOME_ACTIVE,
    OUTCOME_BLOCKED,
    OUTCOME_BUSY,
    OUTCOME_CONFLICT,
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
    ROLLING_BACK,
    STOPPED_STAGES,
    SWITCHING,
    VERIFYING,
    new_intent,
    release_gate,
    safe_error_type,
)
from codex_harness.delivery.domain.managed_runtime import EnvironmentUnqualified
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import utcnow
from codex_harness.kernel.policy import POLICY


class DeliveryController:
    """One bounded delivery tick: select one plan, claim its release under the single host lease, advance
    exactly one stage through its handler, and settle the claim (M7 `HostDelivery.tick`)."""

    def __init__(self, store, *, clock=utcnow, enabled=False, claims=None, settlement=None,
                 resume_seconds=RESUME_SECONDS, ci=None, consumption=None, draining=None, merging=None,
                 preparation=None, publication=None, rollback=None, state=None, switching=None,
                 verification=None):
        self.store = store
        self.clock = clock
        self.enabled = bool(enabled)
        self.claims = claims
        self.settlement = settlement
        self.resume_seconds = int(resume_seconds)
        self.ci = ci
        self.consumption = consumption
        self.draining = draining
        self.merging = merging
        self.preparation = preparation
        self.publication = publication
        self.rollback = rollback
        self.state = state
        self.switching = switching
        self.verification = verification

    # ----- one bounded tick ------------------------------------------------------------------
    def tick(self, plan_id: str | None = None) -> dict:
        """Advance at most ONE delivery by at most one stage, under the existing release fence.

        Whatever this tick did, its receipt carries why every OTHER registered plan waited, so a
        plan that was passed over is an explicit recorded reason rather than a silent omission.
        """
        try:
            selection = self._select(plan_id, create=self.enabled)
        except Exception as exc:
            # The durable state itself cannot be read. That is an explicit outage with its
            # exception TYPE, never an idle poll and never an invented cause.
            return self.state.result(None, None, OUTCOME_UNAVAILABLE, reason_code="store_unavailable",
                                error_type=safe_error_type(type(exc).__name__))
        if selection["plan"] is None:
            return self.state.result(None, None, selection["outcome"], blocked=selection["blocked"],
                                reason_code=selection.get("reason_code"))
        result = self._act(selection)
        result["blocked"] = {**selection["blocked"], **(result.get("blocked") or {})}
        return result

    def _act(self, selection: dict) -> dict:
        """Everything one tick does once its single plan has been selected."""
        row, intent = selection["plan"], selection["intent"]
        plan = row["plan"]
        if (intent or {}).get("held"):
            # Defensive: `_select` never chooses a held intent; nothing is enqueued or claimed.
            return self.state.result(plan, intent, OUTCOME_BUSY, reason_code=str(intent["held"]))
        if not self.enabled:
            # Registration, reconciliation and projection stay available; nothing external happens.
            # S10 A5-2: the state's own Observer (if any) records the declined path.
            observer = getattr(self.state, "observer", None)
            if observer is not None:
                observer.emit("operations.path_declined", "observed",
                              attributes={"feature": "host_delivery", "decline_reason": "disabled"})
            return self.state.result(plan, intent, OUTCOME_DISABLED, reason_code="delivery_disabled")
        gate = self.state.gate(plan)
        if gate["state"] == OUTCOME_REFUSED and intent["stage"] != VERIFYING:
            # A `verifying` delivery halts only from inside `_verify`, after its attempts are
            # reconciled, so a refused verdict never leaves attempt debt unreconciled here.
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_REFUSED, gate["reason_code"])
        if gate["state"] == AWAITING_REVIEW:
            # A registered plan whose review is not complete PROJECTS the wait; it never runs, and
            # no queue row, PR, merge or host change is created for it.
            return self.state.await_review(plan, intent, gate["reason_code"])
        try:
            self.claims.enqueue(plan["release_id"], "host delivery plan " + plan["plan_id"])
            # This controller's own clock drives its fence too, so a lease, a backoff and a stage
            # deadline are never read from two different times.
            claim = self.claims.claim(now=self.state.now(),
                                     eligible=lambda queued: queued["id"] == plan["release_id"])
        except ContractError as exc:
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_REFUSED, "queue_refused",
                              error_type=type(exc).__name__)
        except Exception as exc:  # the store itself is unreachable: an outage, not a verdict
            return self.state.unavailable(plan, intent, "queue_unavailable", exc, commit=False)
        if claim is None:
            return self.state.result(plan, intent, OUTCOME_BUSY, reason_code=self.state.unclaimed(plan))
        try:
            result = self._advance(row, intent, claim)
        except AmbiguousEffect as ambiguous:
            # The effect happened; this controller no longer owns the fence that would record it.
            # It is neither progress nor a cancellation: the successor reconciles what is there.
            LOGGER.warning("host delivery ambiguous effect plan=%s stage=%s effect=%s error=%s",
                           plan["plan_id"], intent["stage"], ambiguous.effect,
                           type(ambiguous.cause).__name__)
            result = {**self.state.result(plan, intent, OUTCOME_CONFLICT,
                                     reason_code="controller_stale_after_effect",
                                     error_type=type(ambiguous.cause).__name__),
                      "controller": "stale", "ambiguous_effect": ambiguous.effect}
        except ContractError as refusal:
            # A definite contract refusal of this stage; a fence that moved underneath it cannot be
            # recorded either, and says so instead of raising over what was already observed. The
            # exception is bound to a local because `except ... as` unbinds its own name on exit.
            failure = refusal
            result = self._guard(plan, intent, OUTCOME_REFUSED, lambda: self.state.halt(
                plan, intent, BLOCKED, OUTCOME_REFUSED,
                getattr(failure, "reason_code", None) or "contract_refused",
                error_type=type(failure).__name__, claim=claim))
        except Exception as outage:
            failure = outage
            # The one NAMED outage: a managed runtime whose dependencies are not the qualified
            # environment waits for the owner to build and qualify it; nothing is installed here.
            reason = ("environment_unqualified" if isinstance(outage, EnvironmentUnqualified)
                      else "stage_unavailable")
            result = self._guard(plan, intent, OUTCOME_UNAVAILABLE, lambda: self.state.unavailable(
                plan, intent, reason, failure, claim=claim))
        if result.get("claim") != "unsettled":
            # An unobserved verification fence (`_unobserved`) is not settled through the store it
            # could not observe: the claim stays running until its lease expires, and the next
            # owner reconciles the attempt first (INV-HOST-DELIVERY-VERIFY-001).
            self._settle(claim, result)
        return result

    def _guard(self, plan: dict, intent: dict, outcome: str, record) -> dict:
        """Record a stop, or report that this controller no longer owns what it observed."""
        try:
            return record()
        except ContractError as exc:
            return {**self.state.result(plan, intent, outcome, reason_code="controller_stale",
                                   error_type=type(exc).__name__), "controller": "stale"}

    def _settle(self, claim, result: dict) -> None:
        """Release the fence: a bounded external wait defers, everything else finishes.

        A stale controller cannot commit this either; its own ownership error is recorded on the
        receipt rather than raised over the result that was already observed.
        """
        outcome, now = result["outcome"], self.state.now()
        try:
            if outcome == OUTCOME_PENDING:
                self.settlement.defer(claim, {"status": "pending", "stage": result["stage"],
                                         "reason": result["reason_code"]},
                                 resume_after_seconds=self.resume_seconds, now=now)
            elif outcome == OUTCOME_UNAVAILABLE:
                self.settlement.finish(claim, {"status": "retry", "reason": result["reason_code"]}, now)
            elif outcome in {OUTCOME_BLOCKED, OUTCOME_REFUSED}:
                self.settlement.finish(claim, {"status": "blocked", "reason": result["reason_code"]}, now)
            elif outcome == OUTCOME_ROLLED_BACK:
                self.settlement.finish(claim, {"status": "rolled_back",
                                          "reason": result["reason_code"]}, now)
            elif outcome == OUTCOME_ACTIVE:
                self.settlement.finish(claim, {"status": "active", "release_id": result["release_id"]}, now)
            else:
                self.settlement.defer(claim, {"status": "progressed", "stage": result["stage"]},
                                 resume_after_seconds=0, now=now)
        except ContractError as exc:
            result["controller"] = "stale"
            result["error_type"] = type(exc).__name__

    def _select(self, plan_id: str | None, *, create: bool = True) -> dict:
        """Transaction 1: the one plan this tick may work on, and why every other one waits.

        A plan that cannot be acted on right now - its independent review is not complete, its
        queue row is in backoff, exhausted, blocked or held by another controller - does not
        consume the single selection: the scan keeps looking for a plan that IS actionable, so one
        waiting target can no longer starve a qualified one. Every skipped plan is recorded with
        its own explicit wait reason rather than silently passed over, the same-target exclusion is
        unchanged, and the scan itself is bounded.

        Only when nothing is actionable does the first WAITING plan become the selection, so a
        single registered plan still projects its own wait (`awaiting_review`) exactly as before.

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
            reserved = {record["target_id"]: record for record in tx.scan(BUCKET_MIGRATIONS)
                        if record.get("state") in MIGRATION_RESERVING}
            blocked, chosen, chosen_intent, waiting = {}, None, None, None
            for index, row in enumerate(sorted(rows, key=lambda r: r["plan_id"])):
                intent = intents.get(row["plan_id"])
                stage = (intent or {}).get("stage") or REGISTERED
                if index >= MAX_SCAN:
                    blocked[row["plan_id"]] = "scan_bounded"
                    continue
                if (intent or {}).get("held"):
                    # INV-HOST-DELIVERY-MIGRATION-001: a held migration successor is never claimed,
                    # evaluated or even projected as the waiting selection until its durable
                    # control acknowledgement (`finalize_migration`) clears the hold.
                    blocked[row["plan_id"]] = str(intent["held"])
                    continue
                if stage == ACTIVE or stage in STOPPED_STAGES:
                    blocked[row["plan_id"]] = stage
                    continue
                migration = reserved.get(row["target_id"])
                if migration is not None and migration.get("plan_id") != row["plan_id"]:
                    blocked[row["plan_id"]] = "target_reserved_by_migration"
                    continue
                if row["target_id"] in busy and stage not in TARGET_BUSY_STAGES:
                    blocked[row["plan_id"]] = "target_busy"
                    continue
                if chosen is not None:
                    blocked[row["plan_id"]] = "controller_serialized"
                    continue
                reason = self._waiting_reason(tx, row["plan"], stage)
                if reason is not None:
                    blocked[row["plan_id"]] = reason
                    waiting = waiting or (row, intent)
                    continue
                chosen, chosen_intent = row, intent
            if chosen is None and waiting is not None:
                # Nothing is actionable; the first waiting plan is selected so its own wait is
                # projected and recorded, which advances no stage and touches nothing external.
                chosen, chosen_intent = waiting
                blocked.pop(chosen["plan_id"], None)
            if chosen is None:
                return {"plan": None, "intent": None, "blocked": blocked, "outcome": OUTCOME_IDLE}
            if chosen_intent is None:
                # The durable intent exists before anything else does, including the queue row.
                chosen_intent = new_intent(chosen["plan"], chosen["plan_sha256"], now)
                if create:
                    tx.put(BUCKET_INTENTS, chosen_intent["id"], chosen_intent)
        return {"plan": chosen, "intent": chosen_intent, "blocked": blocked, "outcome": OUTCOME_PROGRESSED}

    def _waiting_reason(self, tx, plan: dict, stage: str) -> str | None:
        """Why this plan cannot be advanced right now, or None when it can be.

        Read-only, inside the caller's transaction, and deliberately in the same order as the tick
        itself: the existing release record first, then the existing queue row. A refused release
        is NOT a wait - halting it is the tick's owed work - and a rolling back delivery is owed
        work too, because a restoration that stopped being selected would leave the host on a
        descriptor that failed its own canary.
        """
        if stage == ROLLING_BACK:
            return None
        record = tx.get("releases", plan["release_id"])
        gate = release_gate(record, plan, self.state.parent(record))
        if gate["state"] == AWAITING_REVIEW:
            return gate["reason_code"]
        if gate["state"] == OUTCOME_REFUSED:
            return None
        row = tx.get("release_queue", plan["release_id"])
        if row is None:
            return None
        if row.get("status") not in {"queued", "retry", "running"}:
            return "release_queue_" + str(row.get("status"))
        if int(row.get("attempt") or 0) >= POLICY.release_max_attempts:
            return "release_attempts_exhausted"
        if row.get("status") == "running" and self.state.leased(row):
            return "controller_lease_held"
        if self.state.not_due(row):
            return "release_retry_not_due"
        return None

    # ----- the stages -------------------------------------------------------------------------
    def _advance(self, row: dict, intent: dict, claim) -> dict:
        plan, stage = row["plan"], intent["stage"]
        if stage in {REGISTERED, AWAITING_REVIEW}:
            # An already verified (or active) release keeps today's path; a reviewed one is verified
            # by the incumbent evaluator BEFORE anything is published (INV-HOST-DELIVERY-VERIFY-001).
            gate = self.state.gate(plan)
            return self.state.enter(plan, intent, PUBLISHING if gate["status"] in {"verified", "active"}
                               else VERIFYING, claim)
        if stage == VERIFYING:
            return self.verification.verify(plan, intent, claim)
        if stage == PUBLISHING:
            return self.publication.publish(plan, intent, claim)
        if stage == AWAITING_CI:
            return self.ci.observe_ci(plan, intent, claim)
        if stage == MERGE_INTENDED:
            return self.merging.merge(plan, intent, claim)
        if stage == MERGED:
            return self.preparation.prepare_switch(plan, intent, claim)
        if stage == DRAIN_INTENDED:
            return self.draining.drain(plan, intent, claim)
        if stage == SWITCHING:
            return self.switching.switch(plan, intent, claim)
        if stage == AWAITING_CONSUMPTION:
            return self.consumption.consume(plan, intent, claim)
        if stage == ROLLING_BACK:
            return self.rollback.rollback(plan, intent, claim)
        return self.state.result(plan, intent, OUTCOME_IDLE, reason_code="stage_terminal")
