"""The consumption stage.

Layer: application
Context: delivery
Owns: no bucket of its own
Does not own: the canary (its port), the promotion (review's Releases.promote)
Entry points: Consumption
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.application.host_delivery.state import LOGGER, AmbiguousEffect, record_effect
from codex_harness.delivery.domain.host_delivery import (
    ACTIVE,
    AWAITING_CONSUMPTION,
    BLOCKED,
    EVENT_SWITCHED,
    OUTCOME_ACTIVE,
    OUTCOME_BLOCKED,
    RECOVERY_CONSUMPTION_REARM,
    RECOVERY_CONSUMPTION_RETRY,
    consumption_verdict,
)
from codex_harness.kernel.errors import ContractError


class Consumption:
    """The `awaiting_consumption` stage: the startup receipt and the canary, then the promotion through
    review's release owner."""

    def __init__(self, store, *, releases=None, claims=None, rollback=None, state=None):
        self.store = store
        self.releases = releases
        self.claims = claims
        self.rollback = rollback
        self.state = state

    def consume(self, plan: dict, intent: dict, claim) -> dict:
        """The launched process's OWN startup evidence decides activation; a switch alone does not.

        Observing the startup and activating it are two separate facts in two separate records.
        The accepted receipt is recorded as an OBSERVED startup first - instance, runtime root and
        the revision that runtime is actually at - and only then is the canary asked whether that
        observed runtime may become the active one. The canary therefore never has to read the
        activation this stage has deliberately not written yet, and a runtime that is observed but
        refused is durably an unconsumed descriptor rather than a half-claimed activation.
        """
        host, target = self.state.host(plan)
        descriptor = intent["descriptor"]
        verdict = consumption_verdict(descriptor, host.receipt(target),
                                      expected_instance=intent.get("previous_instance_id"))
        if not verdict["consumed"]:
            if verdict["reason_code"] in {"receipt_missing", "receipt_stale_instance"} \
                    and not self.state.expired(intent):
                return self.state.pending(plan, intent, claim, verdict["reason_code"])
            # A wrong receipt never grants activation, and an expired wait is not an unknown that
            # can be waited out: the exact predecessor is restored.
            return self.rollback.begin_rollback(plan, intent, claim, verdict["reason_code"])
        retry = ((intent.get("recoveries") or [None])[-1]) or {}
        if retry.get("kind") in (RECOVERY_CONSUMPTION_RETRY, RECOVERY_CONSUMPTION_REARM) \
                and verdict["instance_id"] != (retry.get("observed") or {}).get("observed_instance_id"):
            # INV-HOST-DELIVERY-FIRST-ACTIVATION-001: a retry or re-arm consumes ONLY the instance it observed.
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "retry_instance_changed", claim=claim)
        startup = {key: verdict.get(key) for key in
                   ("instance_id", "pid", "runtime_root", "module_root", "revision")}
        record_effect("startup_observed", lambda: self.state.record_descriptor(
            plan, intent, descriptor, consumed=False, instance_id=None, claim=claim,
            startup=startup))
        canary = self.state.canary(plan, target, descriptor, startup)
        if canary.get("pending") and not self.state.expired(intent):
            # The owner's requested actual canary has not answered yet: an external wait under the
            # stage's own deadline, never a pass. Expired, it is the failure below and rolls back.
            return self.state.pending(plan, intent, claim, canary.get("reason_code") or "canary_pending")
        # A canary state of its own, so a passed canary is never mistaken for the CI verdict that
        # preceded it and neither one suppresses the other's transition.
        self.state.emit_check(plan, intent, AWAITING_CONSUMPTION,
                         {"state": "canary_passed" if canary["passed"] else "canary_failed",
                          "reason_code": canary.get("reason_code"), "missing": [], "failed": [],
                          "pending": []}, canary_passed=bool(canary["passed"]))
        if not canary["passed"]:
            # The instance this delivery started is now known by its own receipt: the rollback that
            # follows replaces exactly it, and nothing else that may be on the target.
            return self.rollback.begin_rollback(plan, intent, claim, canary.get("reason_code") or "canary_failed",
                                        canary=canary, instance_id=verdict["instance_id"])
        record_effect("consumed", lambda: self.state.record_descriptor(
            plan, intent, descriptor, consumed=True, instance_id=verdict["instance_id"],
            claim=claim, startup=startup))
        self.state.emit(EVENT_SWITCHED, "succeeded", plan, attributes={
            "plan_id": plan["plan_id"], "target_id": plan["target_id"],
            "descriptor_sha256": intent["descriptor_sha256"],
            "previous_sha256": intent["previous_descriptor_sha256"],
            "instance_id": verdict["instance_id"], "consumed": True})
        try:
            pointer = self._promote(plan, intent, claim)
        except ContractError as refusal:
            # `Releases` refused its own compare-and-swap: the host is consumed, the pointer is
            # not this release's, and that is a blocked operational fact, never an activation.
            failure = type(refusal).__name__
            return record_effect("consumed", lambda: self.state.halt(
                plan, intent, BLOCKED, OUTCOME_BLOCKED, "release_promotion_refused", claim=claim,
                error_type=failure))
        LOGGER.info("host delivery active plan=%s release=%s target=%s descriptor=%s instance=%s",
                    plan["plan_id"], plan["release_id"], plan["target_id"],
                    intent["descriptor_sha256"], verdict["instance_id"])
        return record_effect("release_promoted", lambda: self.state.enter(
            plan, intent, ACTIVE, claim, outcome=OUTCOME_ACTIVE,
            instance_id=verdict["instance_id"], canary=canary, stage_deadline=None,
            active_pointer=pointer))

    def _promote(self, plan: dict, intent: dict, claim) -> dict | None:
        """Move the existing release pointer through `Releases`, with ITS compare-and-swap.

        The fence check and the promotion share ONE transaction - the promotion is handed the very
        transaction the ownership was checked in - so there is no window between "this controller
        still owns the release" and "this controller moved the active pointer". The expected active
        release is the one recorded when this delivery bound its target tuple, so a pointer that
        moved in between refuses here instead of overwriting another activation, and a release this
        promotion already made active is recognized rather than promoted twice.
        """
        with self.store.transaction() as tx:
            if claim is not None:
                try:
                    self.claims.owned(tx, claim, self.state.now())
                except ContractError as exc:
                    raise AmbiguousEffect("release_promotion", exc) from exc
            record = tx.get("releases", plan["release_id"]) or {}
            active = tx.get("deployment", "active") or {}
            if record.get("status") == "active" and active.get("release_id") == plan["release_id"]:
                return active
            return self.releases.promote(plan["release_id"], intent.get("expected_active"),
                                         transaction=tx)
