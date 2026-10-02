"""Evidence ports: the buckets evidence owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: evidence
Owns: OWNED_BUCKETS of the evidence context (S8 pilot 66: the inspection ledger rows and the recording-failure notices; S8 pilot 85: the completion verdict rows and rejection notices)
Does not own: the read of an inspection row by a consumer's gate (coordination reads evidence_inspections through
evidence.application.inspections.EvidenceRecords; it never writes)
Entry points: OWNED_BUCKETS
Contracts: INV-EVIDENCE-001
"""

from __future__ import annotations

OWNED_BUCKETS = ("evidence_inspections", "evidence_inspection_notices", "completion_verdicts", "completion_rejections")
