"""The switch stage.

Layer: application
Context: delivery
Owns: no bucket of its own
Does not own: the descriptor file and the runtime (the host port)
Entry points: Switch
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.application.host_delivery.state import (
    launch_record,
    lifecycle,
    reconcile_descriptor,
    record_effect,
    replaces,
)
from codex_harness.delivery.domain.host_delivery import (
    AWAITING_CONSUMPTION,
    BLOCKED,
    EVENT_SWITCHED,
    OUTCOME_BLOCKED,
    consumption_verdict,
)
from codex_harness.kernel.ids import utcnow


class Switch:
    """The `switching` stage: the descriptor compare-and-swap and the runtime start under the target lock."""

    def __init__(self, store, *, clock=utcnow, state=None):
        self.store = store
        self.clock = clock
        self.state = state

    def switch(self, plan: dict, intent: dict, claim) -> dict:
        """Replace the immutable descriptor atomically and start the service exactly once.

        Both halves are reconciled before they are repeated, because a tick that lost its response
        after writing the descriptor or after starting the process must not write a second one or
        start a second instance: the descriptor that is already there is compared to the intended
        one, and a process that is already running and already reports this exact descriptor is
        recognized instead of restarted.

        The start carries the authority captured before the descriptor was replaced, so the only
        running instance it may end is the predecessor this transition named - and what it launched
        or recognized is recorded durably, because that is what a rollback is later authorized to
        replace.
        """
        host, target = self.state.host(plan)
        descriptor = intent["descriptor"]
        state = reconcile_descriptor(host, target, intent)
        if state == "foreign":
            # Neither the descriptor this delivery bound nor the one it expected to replace is
            # there. Something outside this delivery owns the target; it is not overwritten.
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "descriptor_foreign",
                              claim=claim)
        authorize = self.state.authorizer(claim)
        if state == "intended":
            switched = {"written": False, "recovered": True}
        else:
            self.state.owned_now(claim)
            switched = host.switch(target, descriptor, expected=intent["previous_descriptor_sha256"],
                                   authorize=authorize)
        running = consumption_verdict(descriptor, host.receipt(target),
                                      expected_instance=intent.get("previous_instance_id"))
        if running["consumed"] and host.running(target):
            started = {"started": False, "recovered": True, "instance_id": running["instance_id"]}
        else:
            # This outer check is not the mutation boundary: the guard inside the adapter proves
            # ownership again before the first effect, reconciles what is actually on the target,
            # recognizes an already matching live instance instead of restarting it, and replaces
            # only the instance this delivery's durable transition authorized it to replace.
            self.state.owned_now(claim)
            started = lifecycle(
                lambda: host.start(target, descriptor, authorize=authorize,
                                   replaces=replaces(intent, forward=True)))
        record_effect("descriptor_switched", lambda: self.state.record_descriptor(
            plan, intent, descriptor, consumed=False, instance_id=None, claim=claim))
        self.state.emit(EVENT_SWITCHED, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "target_id": plan["target_id"],
            "descriptor_sha256": intent["descriptor_sha256"],
            "previous_sha256": intent["previous_descriptor_sha256"], "instance_id": None,
            "consumed": False})
        # What this delivery itself put on the target: the instance it launched or recognized, and
        # the launch record that identifies it even if that instance never confirms a startup. A
        # rollback replaces exactly this, never the predecessor it is restoring.
        return record_effect("descriptor_switched", lambda: self.state.enter(
            plan, intent, AWAITING_CONSUMPTION, claim,
            candidate_instance_id=started.get("instance_id") or intent.get("candidate_instance_id"),
            candidate_launch=started.get("launch") or launch_record(host, target),
            switch={"at": self.clock(), "written": bool(switched.get("written")),
                    "started": bool(started.get("started")),
                    "recovered": bool(switched.get("recovered") or started.get("recovered"))},
            stage_deadline=self.state.deadline(plan["consumption_timeout_seconds"])))
