"""The publication stage.

Layer: application
Context: delivery
Owns: no bucket of its own
Does not own: the pull request (the GitHub port)
Entry points: Publication
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.application.host_delivery.state import record_effect, require_port
from codex_harness.delivery.domain.host_delivery import AWAITING_CI, BLOCKED, OUTCOME_BLOCKED


class Publication:
    """The `publishing` stage: the reviewed candidate's pull request, an existing one at the intended
    head adopted."""

    def __init__(self, store, *, github=None, state=None):
        self.store = store
        self.github = github
        self.state = state

    def publish(self, plan: dict, intent: dict, claim) -> dict:
        """Publish the reviewed candidate, or ADOPT the publication a lost response already made.

        A candidate whose reviewed base is no longer the remote main is refused here, before any PR
        or CI is spent on it: it can never be fast-forwarded (INV-HOST-DELIVERY-001)."""
        port = require_port(self.github, "github_port_unavailable")
        candidate = self.state.candidate(plan)
        observed = port.observe(candidate)
        if port.merge_state(candidate, observed)["state"] == "base_moved":
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "reviewed_base_moved", claim=claim)
        if observed is None:
            self.state.owned_now(claim)
            observed = port.publish(candidate)
        head = (observed or {}).get("head")
        if head != plan["revision"]:
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publish_head_mismatch",
                              claim=claim)
        deadline = self.state.deadline(plan["ci_timeout_seconds"])
        return record_effect("published", lambda: self.state.enter(
            plan, intent, AWAITING_CI, claim, head=head, pr_number=observed.get("number"),
            pr_url=observed.get("url"), stage_deadline=deadline))
