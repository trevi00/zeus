"""Intake ports: the buckets intake owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: intake
Owns: OWNED_BUCKETS of the intake context (S6: the Portfolio lineage rows; S8 pilot 63: the Portfolio acceptances, investigations and followups)
Does not own: the Protocols other contexts declare for intake's operations (coordination.ports.PortfolioLineage)
Entry points: OWNED_BUCKETS
Contracts: INV-CONTINUATION-001
"""

from __future__ import annotations

OWNED_BUCKETS = ("portfolio_bindings", "portfolio_acceptances", "portfolio_investigations",
                 "portfolio_followups")
