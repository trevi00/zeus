"""The merge stage.

Layer: application
Context: delivery
Owns: no bucket of its own
Does not own: the merge (the GitHub port)
Entry points: Merge
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.application.host_delivery.state import record_effect, require_port
from codex_harness.delivery.domain.host_delivery import (
    BLOCKED,
    CI_PASSED,
    MERGED,
    OUTCOME_BLOCKED,
    ci_verdict,
)
from codex_harness.kernel.errors import ContractError


class Merge:
    """The `merge_intended` stage: the compare-and-swap merge of the reviewed head, a lost response
    recognized from the remote."""

    def __init__(self, store, *, github=None, state=None):
        self.store = store
        self.github = github
        self.state = state

    def merge(self, plan: dict, intent: dict, claim) -> dict:
        """Fast-forward main to the exact reviewed head, or RECOGNIZE the merge already made.

        Before a NEW effect the target must still hold the plan's expected predecessor with no other
        delivery unsettled on it, and the remote main must still be the reviewed base; the merge
        itself is the server-side compare-and-swap of exactly that (INV-HOST-DELIVERY-001).

        Both paths end at the SAME qualification: the merged revision must carry the reviewed tree,
        checked by the merge owner itself. A merge that happened is not a qualified deployment, so
        a merged tree that is not the reviewed one blocks here - on the tick that performed it and
        on every later tick that observes it - instead of inheriting the old acceptance.
        """
        port = require_port(self.github, "github_port_unavailable")
        candidate = self.state.candidate(plan)
        observed = port.observe(candidate)
        if observed is None:
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publication_missing", claim=claim)
        if observed.get("head") != intent["head"]:
            return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "ci_head_changed", claim=claim)
        # An effect that already happened (our fast-forward whose response was lost, or anyone's
        # merge of this exact head) is reconciled FIRST, before any refusal or new effect.
        state = port.merge_state(candidate, observed)
        if state["state"] == "merged":
            merged = {"merged": True, "merged_revision": state["merged_revision"], "recovered": True}
        else:
            predecessor = self.state.predecessor(plan)
            if predecessor == "in_flight":
                # Another delivery of this target has merged and not settled the host: no effect, no
                # attempt spent, the stage stays; it is decided once that delivery is terminal.
                return self.state.pending(plan, intent, claim, "predecessor_in_flight")
            if predecessor == "moved":
                return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "descriptor_predecessor_moved",
                                  claim=claim)
            if state["state"] != "unmerged":
                return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "reviewed_base_moved", claim=claim)
            # A NEW mainline effect keeps the existing gates of that effect: the exact open PR of the
            # reviewed head and the plan's required checks passing on it right now. Recognizing an
            # effect above is recovery; it never stands in for this.
            if observed.get("state") != "OPEN":
                return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publication_not_open", claim=claim)
            verdict = ci_verdict(plan["required_checks"], observed.get("checks"), intent["head"],
                                 observed_head=observed.get("head"))
            if verdict["state"] != CI_PASSED:
                return self.state.halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, verdict["reason_code"], claim=claim,
                                  last_check_state=verdict["state"])
            self.state.owned_now(claim)
            merged = port.merge(candidate, observed)
        revision = merged.get("merged_revision") or intent["head"]
        qualify = getattr(port, "qualify", None)
        if qualify is None:
            return record_effect("merged", lambda: self.state.halt(
                plan, intent, BLOCKED, OUTCOME_BLOCKED, "merge_unqualified", claim=claim,
                merged_revision=revision))
        try:
            qualify(candidate, revision)
        except ContractError as refusal:
            # Bound to a local: `except ... as` unbinds its own name before the lambda runs.
            failure = type(refusal).__name__
            return record_effect("merged", lambda: self.state.halt(
                plan, intent, BLOCKED, OUTCOME_BLOCKED, "merged_tree_mismatch", claim=claim,
                error_type=failure, merged_revision=revision))
        return record_effect("merged", lambda: self.state.enter(plan, intent, MERGED, claim,
                                                          merged_revision=revision))
