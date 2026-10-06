"""The verified-promotion graph namespace.

Layer: domain
Context: knowledge
Owns: PROMOTED_NAMESPACE, the repository prefix of every promoted `verified:<run>` graph; BUCKET, the name of the
    promotions bucket (S8 pilot 73: research's program reads it from here, one owner)
Does not own: which run may be promoted (research.domain.autonomous, S8)
Entry points: PROMOTED_NAMESPACE, BUCKET
Contracts: INV-AUTONOMOUS-001

Moved from SOURCE M7 `domain/autonomous.PROMOTED_NAMESPACE`: knowledge writes the promoted graph and
research (downstream in the §2.4 DAG) reads the same constant from here in S8.
"""

PROMOTED_NAMESPACE = "verified:"
BUCKET = "promotions"
