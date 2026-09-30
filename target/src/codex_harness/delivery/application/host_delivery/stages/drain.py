"""The drain stage.

Layer: application
Context: delivery
Owns: no bucket of its own
Does not own: the target's work (the host port)
Entry points: Drain
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.domain.host_delivery import BLOCKED, OUTCOME_BLOCKED, SWITCHING


class Drain:
    """The `drain_intended` stage: the target's active work drained under the fence."""

    def __init__(self, store, *, state=None):
        self.store = store
        self.state = state

    def drain(self, plan: dict, intent: dict, claim) -> dict:
        """Pause new admission and prove the target drained; an unconfirmed effect blocks the switch."""
        host, target = self.state.host(plan)
        # Pausing admission writes to the target's state directory: a stale actor pauses nothing.
        # The check is made again inside the target guard, where the pause actually happens.
        self.state.owned_now(claim)
        observed = host.drain(target, authorize=self.state.authorizer(claim))
        # A target that reports what its instance is doing (the managed heartbeat verdict) has that
        # observation recorded with the stage, so the projection shows why a drain waits.
        work = {"work": observed["work"]} if isinstance(observed.get("work"), dict) else {}
        if observed.get("unconfirmed"):
            # Unknown work is not finished work: this never kills active model work to deploy.
            if self.state.expired(intent):
                return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "drain_unconfirmed_effects",
                                  claim=claim, **work)
            return self.state.pending(plan, intent, claim, "drain_unconfirmed_effects", **work)
        if not observed.get("drained"):
            if self.state.expired(intent):
                return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "drain_timeout", claim=claim,
                                  **work)
            return self.state.pending(plan, intent, claim, "drain_pending", **work)
        return self.state.enter(plan, intent, SWITCHING, claim,
                           stage_deadline=self.state.deadline(plan["consumption_timeout_seconds"]), **work)
