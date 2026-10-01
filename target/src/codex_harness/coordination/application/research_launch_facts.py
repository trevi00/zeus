"""The owner-action research launch facts research's program reads (V13 R4, INV-RESEARCH-ATTEMPT-SCOPE-001).

Layer: application
Context: coordination
Owns: the read of `research_dispatch` owner-action rows by launch id, and the authenticity predicate of such a row
Does not own: the owner_actions bucket and its identity rules (coordination.domain.owner_actions); the cycle
    owner decision (research.application.research_program)
Entry points: ResearchLaunchFacts
Contracts: INV-RESEARCH-ATTEMPT-SCOPE-001, INV-OWNER-ACTIONS-001

Structurally satisfies research's `ResearchLaunchFacts` port. The two functions are the owner-actions identity
rules of M7 `ResearchProgram._scope_target` moved behind the port: the rules themselves are
`coordination.domain.owner_actions.action_id` and `research_launch_id`, never copied. Stateless.
"""

from __future__ import annotations

from codex_harness.coordination.application.owner_actions.state import BUCKET_ACTIONS
from codex_harness.coordination.domain.owner_actions import (
    LAUNCHING,
    RESEARCH_DISPATCH,
    RUNNING,
    action_id,
    research_launch_id,
)
from codex_harness.kernel.ids import digest


class ResearchLaunchFacts:
    def launches(self, tx, owner: str) -> list:
        """The `research_dispatch` owner-action rows whose launch id is `owner`, in the store's scan order."""
        return [a for a in tx.scan(BUCKET_ACTIONS)
                if isinstance(a, dict) and a.get("kind") == RESEARCH_DISPATCH and a.get("launch_id") == owner]

    def authentic(self, action: dict, owner: str) -> bool:
        """The action is `launching`/`running` and its id, binding digest and derived launch id recompute.

        The caller has already checked that `action["binding"]` is a dict."""
        binding = action.get("binding")
        return bool(action.get("state") in {LAUNCHING, RUNNING}
                    and action.get("id") == action_id(RESEARCH_DISPATCH, binding)
                    and action.get("binding_sha256") == digest(binding) and type(action.get("launches")) is int
                    and owner == research_launch_id(action["id"], action["launches"]))
