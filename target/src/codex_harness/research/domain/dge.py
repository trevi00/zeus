"""Debate/meeting packet time rule: `expired` (INV-DGE-001).

Layer: domain
Context: research
Owns: the aware-UTC deadline comparison (M7 `domain/dge.py::expired`, moved ahead in S5 verbatim)
Does not own: packet, event and deadline parsing and the rest of the debate policy (S8 completes the module, TRACE C3)
Entry points: expired
Contracts: INV-DGE-001

Partial move: S8 completes the module (C3).
"""
from __future__ import annotations

from datetime import datetime, timezone


def expired(deadline: str, now: str) -> bool:
    """Aware UTC comparison; `now` is the caller's clock reading so the rule stays testable."""
    return datetime.fromisoformat(now).astimezone(timezone.utc) >= datetime.fromisoformat(deadline)
