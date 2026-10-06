"""Observation's health owner operation: the `health` rows other contexts report (INV-OBSERVATION-001).

Layer: application
Context: observation
Owns: bucket health rows reported by other contexts (coordination's outbox relay writes `health/outbox` through it)
Does not own: the reporting contexts' own batches or the Observer's alert/health sink bookkeeping (Observer)
Entry points: HealthRecords.record
Contracts: INV-OBSERVATION-001
"""

from __future__ import annotations


class HealthRecords:
    """Stateless owner operation; its constructor takes nothing."""

    def record(self, tx, name: str, row: dict) -> None:
        # §2.9 rule 2: it joins the caller's unit and never opens, commits or nests a transaction.
        tx.put("health", name, row)
