"""Observation ports: the buckets observation owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: observation
Owns: OWNED_BUCKETS of the observation context
Does not own: the other observation Protocols (PostgresFacts, RedisFacts, ...: S9)
Entry points: OWNED_BUCKETS
Contracts: INV-OBSERVATION-001
"""

from __future__ import annotations

OWNED_BUCKETS = ("observation_audit", "observations", "observation_quarantine", "observation_alerts",
                 "observation_collections", "observation_terminations", "health")
