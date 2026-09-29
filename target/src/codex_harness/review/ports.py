"""Review ports: the buckets review owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: review
Owns: OWNED_BUCKETS of the review context
Does not own: HandoffReader and the other review Protocols (S8)
Entry points: OWNED_BUCKETS
Contracts: INV-RELEASE-001
"""

from __future__ import annotations

OWNED_BUCKETS = ("releases", "release_queue", "improvement_loops")  # improvement_loops: named correction (S4)
