"""The switch preparation stage.

Layer: application
Context: delivery
Owns: no bucket of its own
Does not own: the target (the host port)
Entry points: SwitchPreparation
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.application.host_delivery.state import BUCKET_DESCRIPTORS, BUCKET_TARGETS
from codex_harness.delivery.domain.host_delivery import (
    BLOCKED,
    DRAIN_INTENDED,
    OUTCOME_BLOCKED,
    OUTCOME_REFUSED,
    RECOVERY_FIRST_ACTIVATION,
    descriptor_digest,
    recoveries_of,
    resolve_descriptor,
)


class SwitchPreparation:
    """The `merged` stage: the switch intent bound to the verified release, the registered target and its
    predecessor descriptor."""

    def __init__(self, store, *, hosts=None, state=None):
        self.store = store
        self.hosts = hosts or {}
        self.state = state

    def prepare_switch(self, plan: dict, intent: dict, claim) -> dict:
        """Bind the exact target tuple this delivery will switch to, before touching the host.

        The verified release, the registered target, the current descriptor and the plan's expected
        predecessor must all agree here; the resolved descriptor and the active-release CAS value
        are written durably, so the switch, a replay of it and a rollback all act on one identity.

        The IDENTITY of the instance that is running there is captured here too, while the
        predecessor's own receipt still names it, and durably: the authority to replace an instance
        cannot be re-derived from the target after its descriptor has been replaced. A target whose
        running instance is not the one this delivery's own records name is a disagreement to
        reconcile (`target_instance_mismatch`), not something to switch on top of.
        """
        gate = self.state.gate(plan)
        if gate["status"] not in {"verified", "active"}:
            # The incumbent checks of this candidate are the evaluator's, not this controller's.
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "release_not_verified", claim=claim)
        with self.store.transaction() as tx:
            target = tx.get(BUCKET_TARGETS, plan["target_id"])
            current_row = tx.get(BUCKET_DESCRIPTORS, plan["target_id"])
            active = tx.get("deployment", "active") or {}
        if target is None:
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_REFUSED, "target_unregistered", claim=claim)
        current = (current_row or {}).get("descriptor")
        current_sha = None if current is None else descriptor_digest(current)
        if plan["expected_descriptor"] != current_sha:
            # The host is not where the owner approved this switch from.
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "descriptor_predecessor_mismatch",
                              claim=claim)
        # The identity of the instance this delivery may replace is captured HERE, before the
        # descriptor is replaced and therefore while the predecessor's own receipt still names it.
        # It is durable, so a later tick, a restart or a lost response acts on the same authority.
        # A port that is not wired yet is not a reason to refuse here - the stage that actually
        # touches the host reports that - and it leaves this delivery with NO authority to replace
        # anything, which the start then refuses rather than acting on an assumption.
        host = self.hosts.get(target["kind"])
        identity = host.identity(target) if hasattr(host, "identity") else {}
        recorded = (current_row or {}).get("instance_id") or (current_row or {}).get(
            "observed_instance_id")
        observed_instance = identity.get("instance_id")
        if recorded and observed_instance and recorded != observed_instance:
            # This delivery's own records and the target disagree about who is running there.
            # Nothing is switched, stopped or started on contradictory evidence.
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "target_instance_mismatch",
                              claim=claim)
        # INV-HOST-DELIVERY-FIRST-ACTIVATION-001: the owner's re-derived first-activation tuple, if
        # any; `resolve_descriptor` uses it only when there is no current descriptor to resolve against.
        bound = recoveries_of(intent, RECOVERY_FIRST_ACTIVATION)
        descriptor = resolve_descriptor(target, plan, current, bound[-1].get("binding") if bound else None)
        # A managed target runs an immutable sealed runtime: it is materialized (or, after a lost
        # response, revalidated as the same immutable result) BEFORE the drain, so nothing on the
        # running instance is paused for a runtime that cannot exist. Other kinds have no such port.
        runtime = None
        materialize = getattr(host, "materialize", None)
        if materialize is not None:
            self.state.owned_now(claim)
            runtime = materialize(target, descriptor, authorize=self.state.authorizer(claim))
        return self.state.enter(plan, intent, DRAIN_INTENDED, claim, descriptor=descriptor,
                           **({"runtime": runtime} if runtime is not None else {}),
                           descriptor_sha256=descriptor_digest(descriptor),
                           previous_descriptor=current, previous_descriptor_sha256=current_sha,
                           previous_instance_id=observed_instance or recorded,
                           previous_launch=identity.get("launch"),
                           expected_active=active.get("release_id"), expected_active_set=True,
                           stage_deadline=self.state.deadline(plan["consumption_timeout_seconds"]))
