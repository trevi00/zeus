"""Debate/meeting packet time rule: `expired` (INV-DGE-001).

Layer: domain
Context: research
Owns: the aware-UTC deadline comparison (M7 `domain/dge.py::expired`) and the fixed-code refusal type
    `DgeRefused` (M7 `application/dge.py`), both moved ahead in S5 verbatim (Operation catches it)
Does not own: packet, event and deadline parsing and the rest of the debate policy (S8 completes the module, TRACE C3)
Entry points: expired, DgeRefused
Contracts: INV-DGE-001

Partial move: S8 completes the module (C3).
"""
from __future__ import annotations

from datetime import datetime, timezone

from codex_harness.kernel.errors import ContractError


def expired(deadline: str, now: str) -> bool:
    """Aware UTC comparison; `now` is the caller's clock reading so the rule stays testable."""
    return datetime.fromisoformat(now).astimezone(timezone.utc) >= datetime.fromisoformat(deadline)


class DgeRefused(ContractError):
    """Refused with a fixed reason code; the message never carries packet or payload text."""

    def __init__(self, reason_code: str):
        super().__init__("dge refused: " + reason_code)
        self.reason_code = reason_code
