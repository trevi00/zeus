"""Coordination's event journal append: the one writer of `events` bodies (REBUILD-DESIGN-v2 §2.7, §2.9).

Layer: application
Context: coordination
Owns: EventJournal.append, the unconditional put M7 writes inline (`application/service.py` `hook.required`,
    `adapters/executor.py` `execution.reconciliation_required`), with the caller's key and body unchanged
Does not own: a caller's own existence check before appending (kept at the call site, as M7 has it); the
    event bodies' meaning
Entry points: EventJournal.append
Contracts: INV-RECURRENCE-001, INV-OBSERVATION-001
"""

from __future__ import annotations


class EventJournal:
    """Stateless owner operation; its constructor takes nothing."""

    def append(self, tx, identity: str, body: dict) -> None:
        # §2.9 rule 2: it joins the caller's unit. Unconditional, exactly like the M7 inline puts it replaces.
        tx.put("events", identity, body)
