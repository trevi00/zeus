"""Delivery ports: the buckets delivery owns (REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: delivery
Owns: OWNED_BUCKETS of the delivery context; empty until S7 declares the buckets its use cases write
Does not own: any bucket body or use case (S7)
Entry points: OWNED_BUCKETS
Contracts: INV-HOST-DELIVERY-001
"""

from __future__ import annotations

OWNED_BUCKETS = ()  # S7 declares them
