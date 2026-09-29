"""Observation ports: the buckets observation owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: observation
Owns: OWNED_BUCKETS of the observation context; SpoolFull and ObservationSpool (M7 `ports.py`, moved ahead in S4
    unchanged: the append-only record store the Observer writes through)
Does not own: ObservationDirectory (9 methods, above the port-size limit: S9) and the other observation Protocols
    (PostgresFacts, RedisFacts, ...: S9)
Entry points: OWNED_BUCKETS, SpoolFull, ObservationSpool
Contracts: INV-OBSERVATION-001
"""

from __future__ import annotations

from typing import Protocol

OWNED_BUCKETS = ("observation_audit", "observations", "observation_quarantine", "observation_alerts",
                 "observation_collections", "observation_terminations", "health")


class SpoolFull(RuntimeError):
    """The bounded observation spool cannot take another record; the caller counts and reports."""


class ObservationSpool(Protocol):
    """One process run's append-only durable record store (INV-OBSERVATION-001)."""
    process_run_id: str

    def append(self, kind: str, event: dict) -> int: ...
    def close(self) -> None: ...
