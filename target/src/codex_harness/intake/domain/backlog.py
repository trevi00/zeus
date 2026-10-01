"""Fleet backlog runner vocabulary: how a returned tick outcome reads to the runner (INV-FLEET-001).

Layer: domain
Context: intake
Owns: the runner-state vocabulary and safe error type of the fleet backlog (M7 `domain/fleet_backlog.py`, moved ahead in S5 verbatim), and its refusal BacklogRefused (moved ahead in S7 verbatim)
Does not own: the rest of the backlog policy, plan and selection rules (S8 completes the module, TRACE C2)
Entry points: runner_state, safe_error_type, BacklogRefused, RUNNER_OK, RUNNER_UNAVAILABLE, RUNNER_REFUSED, RUNNER_STATES
Contracts: INV-FLEET-001

Partial move: S8 completes the module (C2). Only the names above and what they need transitively
(`OUTCOME_UNAVAILABLE`, `OUTCOME_UNREGISTERED`, `OUTCOME_REFUSED`, `OUTCOME_CONFLICT`, `TOKEN`, `_token`)
are here; nothing imports coordination.
"""
from __future__ import annotations

import re

from codex_harness.kernel.errors import ContractError

TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Tick outcomes the runner states below read (a subset of the M7 tick/selection outcomes).
OUTCOME_UNAVAILABLE = "unavailable"
OUTCOME_UNREGISTERED = "plan_unregistered"
OUTCOME_REFUSED = "refused"
OUTCOME_CONFLICT = "conflict"

# How a RETURNED tick outcome reads to the runner that called it. A tick that answers `unavailable`
# or `refused` is a failure of that tick, exactly like a raised outage: it is never `ok` merely
# because the call returned. Idle, blocked and both pauses are ordinary healthy states.
RUNNER_OK, RUNNER_UNAVAILABLE, RUNNER_REFUSED = "ok", "unavailable", "refused"
RUNNER_STATES = {OUTCOME_UNAVAILABLE: RUNNER_UNAVAILABLE, OUTCOME_REFUSED: RUNNER_REFUSED,
                 OUTCOME_CONFLICT: RUNNER_REFUSED, OUTCOME_UNREGISTERED: RUNNER_REFUSED}


def _token(value) -> bool:
    return type(value) is str and TOKEN.fullmatch(value) is not None


def runner_state(outcome) -> str:
    """What a RETURNED tick outcome means to the runner: `ok`, `unavailable` or `refused`."""
    return RUNNER_STATES.get(outcome, RUNNER_OK)


def safe_error_type(value) -> str | None:
    """An exception TYPE name and nothing else; any other text is `unknown` rather than relayed."""
    if value is None:
        return None
    return value if _token(value) else "unknown"


class BacklogRefused(ContractError):
    """Refused; the message carries a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("fleet backlog refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field
