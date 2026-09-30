"""The rollback stage.

Layer: application
Context: delivery
Owns: no bucket of its own
Does not own: the restored runtime (the host port)
Entry points: Rollback
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.application.host_delivery.state import (
    LOGGER,
    AmbiguousEffect,
    lifecycle,
    reconcile_descriptor,
    record_effect,
    replaces,
)
from codex_harness.delivery.domain.host_delivery import (
    ACTIVATION_GATE_CODES,
    BLOCKED,
    EVENT_ROLLBACK,
    OUTCOME_BLOCKED,
    OUTCOME_PROGRESSED,
    OUTCOME_ROLLED_BACK,
    ROLLED_BACK,
    ROLLING_BACK,
    DeliveryRefused,
    consumption_verdict,
    safe_error_type,
)
from codex_harness.kernel.ids import utcnow


class Rollback:
    """The `rolling_back` stage: the exact predecessor restored and proven consumed, or an explicit block."""

    def __init__(self, store, *, clock=utcnow, state=None):
        self.store = store
        self.clock = clock
        self.state = state

    def begin_rollback(self, plan: dict, intent: dict, claim, reason_code: str, canary=None,
                        instance_id=None) -> dict:
        if instance_id is not None:
            intent = {**intent, "candidate_instance_id": instance_id}
        if intent.get("previous_descriptor") is None:
            # There is no known-good predecessor for this target: nothing may be restored, and the
            # delivery stops where it is rather than inventing a state to return to.
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "no_known_good_predecessor",
                              claim=claim, rollback={"requested": True, "restored": False,
                                                     "verified": False, "reason_code": reason_code},
                              **({"canary": canary} if canary is not None else {}))
        # Progress toward the restoration, not a stop: the fence is deferred rather than finished,
        # so the very next bounded tick performs the rollback instead of waiting for an owner.
        return self.state.enter(plan, intent, ROLLING_BACK, claim, outcome=OUTCOME_PROGRESSED,
                           reason_code=reason_code, canary=canary,
                           rollback={"requested": True, "restored": False, "verified": False,
                                     "reason_code": reason_code},
                           stage_deadline=self.state.deadline(plan["consumption_timeout_seconds"]))

    def rollback(self, plan: dict, intent: dict, claim) -> dict:
        """Restore the EXACT predecessor tuple, then PROVE the restored runtime is the one running.

        Every entry into this stage reconciles first: what descriptor is on the host right now, and
        which instance is actually running. A restoration whose durable acknowledgement was lost is
        RESUMED from what the host already shows rather than attempted a second time against an
        expectation that no longer holds, a descriptor that is neither the failed one nor the
        predecessor is a foreign state that blocks instead of being overwritten, and the start is
        performed at most once per restoration. The instance it is authorized to replace is the
        failed CANDIDATE this intent started - by its own receipt, or by this delivery's launch
        record when that candidate never confirmed a startup - and never an unknown one. Nothing sleeps under the lease: the predecessor's
        own fresh receipt and a live process are what verify it, and a restoration that cannot be
        proven becomes a blocked operational alert rather than a `rolled_back` claim.
        """
        host, target = self.state.host(plan)
        previous = intent["previous_descriptor"]
        record = dict(intent.get("rollback") or {})
        reason = record.get("reason_code") or "rollback"
        state = reconcile_descriptor(host, target, intent)
        if state == "foreign":
            record.update(restored=False, verified=False, error_type=None, at=self.clock())
            return self._blocked_rollback(plan, intent, claim, record, "rollback_foreign_descriptor")
        if state == "intended":
            # The failed descriptor is still the one on the host: restore the predecessor now.
            try:
                self.state.owned_now(claim)
                host.switch(target, previous, expected=intent["descriptor_sha256"],
                            authorize=self.state.authorizer(claim))
            except AmbiguousEffect:
                raise
            except Exception as exc:
                error_type = safe_error_type(type(exc).__name__)
                record.update(restored=False, verified=False, error_type=error_type,
                              at=self.clock())
                return self._blocked_rollback(plan, intent, claim, record, "rollback_failed")
            record.update(restored=True, started=False, verified=False, error_type=None,
                          at=self.clock())
            return record_effect("descriptor_restored", lambda: self.state.pending(
                plan, intent, claim, "rollback_awaiting_consumption", rollback=record,
                stage_deadline=self.state.deadline(plan["consumption_timeout_seconds"])))
        # The predecessor descriptor IS on the host, whether this tick wrote it or a lost response
        # did. The restoration is a fact of the host, not of the record that failed to name it.
        record.update(restored=True)
        try:
            verdict = consumption_verdict(previous, host.receipt(target))
            alive = bool(host.running(target))
            error_type = None
        except Exception as exc:
            verdict, alive = {"consumed": False, "instance_id": None}, False
            error_type = safe_error_type(type(exc).__name__)
        if not (verdict["consumed"] and alive) and not record.get("started"):
            # The restored descriptor is there but its runtime is not: start it exactly once, under
            # the same guard, the same authorization and the same reconciliation as a forward start.
            try:
                self.state.owned_now(claim)
                lifecycle(lambda: host.start(target, previous,
                                                   authorize=self.state.authorizer(claim),
                                                   replaces=replaces(intent, forward=False)))
            except AmbiguousEffect:
                raise
            except DeliveryRefused as exc:
                if exc.reason_code not in ACTIVATION_GATE_CODES:
                    record.update(started=False, verified=False,
                                  error_type=safe_error_type(type(exc).__name__), at=self.clock())
                    return self._blocked_rollback(plan, intent, claim, record, "rollback_failed")
                # The target's Fleet debt or pause is held or unknown: the predecessor is NOT started,
                # any committed admission pause stays, and the restoration waits for settlement - then
                # blocks for its recovery owner under that same code, never started past the debt.
                record.update(started=False, verified=False, error_type=None, gate=exc.reason_code,
                              at=self.clock())
                if not self.state.expired(intent):
                    return self.state.pending(plan, intent, claim, exc.reason_code, rollback=record)
                return self._blocked_rollback(plan, intent, claim, record, exc.reason_code)
            except Exception as exc:
                record.update(started=False, verified=False,
                              error_type=safe_error_type(type(exc).__name__), at=self.clock())
                return self._blocked_rollback(plan, intent, claim, record, "rollback_failed")
            record.pop("gate", None)
            record.update(started=True, verified=False, error_type=None, at=self.clock())
            return record_effect("predecessor_started", lambda: self.state.pending(
                plan, intent, claim, "rollback_awaiting_consumption", rollback=record,
                stage_deadline=self.state.deadline(plan["consumption_timeout_seconds"])))
        if not (verdict["consumed"] and alive):
            record.update(verified=False, error_type=error_type)
            if not self.state.expired(intent):
                return self.state.pending(plan, intent, claim, "rollback_awaiting_consumption",
                                     rollback=record)
            return self._blocked_rollback(plan, intent, claim, record, "rollback_unverified")
        record.update(verified=True, error_type=None, at=self.clock())
        self.state.emit(EVENT_ROLLBACK, "succeeded", plan, severity="warning", reason_code=reason,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "descriptor_sha256": intent["previous_descriptor_sha256"],
                               "restored": True, "verified": True, "error_type": None})
        record_effect("predecessor_consumed", lambda: self.state.record_descriptor(
            plan, intent, previous, consumed=True, instance_id=verdict.get("instance_id"),
            claim=claim, rolled_back=True,
            startup={key: verdict.get(key) for key in
                     ("instance_id", "pid", "runtime_root", "module_root", "revision")}))
        LOGGER.warning("host delivery rolled back plan=%s target=%s descriptor=%s reason=%s",
                       plan["plan_id"], plan["target_id"], intent["previous_descriptor_sha256"], reason)
        return record_effect("predecessor_consumed", lambda: self.state.enter(
            plan, intent, ROLLED_BACK, claim, outcome=OUTCOME_ROLLED_BACK, reason_code=reason,
            rollback=record, stage_deadline=None))

    def _blocked_rollback(self, plan: dict, intent: dict, claim, record: dict,
                          reason_code: str) -> dict:
        """A failed or unproven restoration: a critical operations alert, never a rolled-back claim."""
        self.state.emit(EVENT_ROLLBACK, "blocked", plan, severity="critical", reason_code=reason_code,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "descriptor_sha256": intent["previous_descriptor_sha256"],
                               "restored": bool(record.get("restored")), "verified": False,
                               "error_type": record.get("error_type")})
        return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, reason_code, claim=claim,
                          error_type=record.get("error_type"), rollback=record)
