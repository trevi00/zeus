"""The CI observation stage.

Layer: application
Context: delivery
Owns: no bucket of its own
Does not own: the checks (the GitHub port)
Entry points: CiObservation
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.application.host_delivery.state import require_port
from codex_harness.delivery.domain.host_delivery import (
    AWAITING_CI,
    BLOCKED,
    CI_FAILED,
    CI_HEAD_CHANGED,
    CI_PASSED,
    CI_PENDING,
    MERGE_INTENDED,
    OUTCOME_BLOCKED,
    ci_verdict,
)


class CiObservation:
    """The `awaiting_ci` stage: the required checks of the published head."""

    def __init__(self, store, *, github=None, state=None):
        self.store = store
        self.github = github
        self.state = state

    def observe_ci(self, plan: dict, intent: dict, claim) -> dict:
        """The REAL checks of the exact intended head; nothing else is evidence that CI passed."""
        port = require_port(self.github, "github_port_unavailable")
        candidate = self.state.candidate(plan)
        observed = port.observe(candidate)
        if observed is None:
            # The publication this intent recorded is gone: that is a definite refusal to merge, not
            # a reason to publish a second time under the same intent.
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publication_missing", claim=claim)
        verdict = ci_verdict(plan["required_checks"], observed.get("checks"), intent["head"],
                             observed_head=observed.get("head"))
        self.state.emit_check(plan, intent, AWAITING_CI, verdict, claim=claim)
        if verdict["state"] == CI_PASSED:
            return self.state.enter(plan, intent, MERGE_INTENDED, claim, stage_deadline=None,
                               last_check_state=CI_PASSED)
        if verdict["state"] == CI_FAILED:
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, verdict["reason_code"],
                              claim=claim, last_check_state=CI_FAILED)
        if verdict["state"] == CI_HEAD_CHANGED:
            # A moved head goes to requalification; it is never rebased into the old acceptance.
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "ci_head_changed", claim=claim,
                              last_check_state=CI_HEAD_CHANGED)
        if self.state.expired(intent):
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "ci_timeout", claim=claim,
                              last_check_state=CI_PENDING)
        return self.state.pending(plan, intent, claim, verdict["reason_code"], last_check_state=CI_PENDING)
