"""The one mapping from a routing result to a fixed role-container profile.

Layer: domain
Context: routing
Owns: the four profile names and `select_profile` (pure); re-exports IsolationError (defined in kernel.errors)
Does not own: the container argv, mounts or credentials of a profile (execution/credentials, S3)
Entry points: select_profile, IsolationError, CLAUDE_IMPL_RW, CLAUDE_ROLE_RO, CODEX_ROLE_RO, CODEX_IMPL_RW
Contracts: INV-ROLE-CONTAINER-001

Moved from SOURCE M7 `adapters/role_containers.select_profile` (§1.2 routing row). IsolationError keeps
its M7 name, message form and `reason_code`; it is defined once in `kernel.errors` (S3) and re-exported
here, so routing, credentials and execution raise the same type and a refusal before spawn reads
identically whichever layer refused.
"""

from __future__ import annotations

from codex_harness.kernel.errors import IsolationError

CLAUDE_IMPL_RW, CLAUDE_ROLE_RO = "claude-impl-rw", "claude-role-ro"
CODEX_ROLE_RO, CODEX_IMPL_RW = "codex-role-ro", "codex-impl-rw"


def select_profile(provider, transport, action, read_only, *, codex_enabled: bool) -> str:
    """The one mapping from the routing result to a profile; everything else refuses before spawn.
    There is never a host fallback: a disabled Codex store refuses rather than using the host."""
    if type(read_only) is bool:
        if provider == "claude" and transport == "claude_cli":
            if read_only:
                return CLAUDE_ROLE_RO
            if action == "implement":
                return CLAUDE_IMPL_RW
        elif provider == "codex" and transport == "app_server":
            if not codex_enabled:
                raise IsolationError("codex_profile_disabled",
                                     "isolation is selected and no Codex credential store is configured; "
                                     "the host App Server is never the fallback")
            if read_only:
                return CODEX_ROLE_RO
            if action == "implement":
                return CODEX_IMPL_RW
    raise IsolationError("role_profile_refused", f"{provider}/{transport}/{action}/{'ro' if read_only else 'rw'}")
