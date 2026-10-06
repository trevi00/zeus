"""Evidence ports: the buckets evidence owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: evidence
Owns: OWNED_BUCKETS of the evidence context (S8 pilot 66: the inspection ledger rows and the recording-failure notices; S8 pilot 85: the completion verdict rows and rejection notices); ContainerReplay (S8 batch B5b, DESIGN-s8 V26 rule E-2: the container run of one evidence replay, provided by execution)
Does not own: the read of an inspection row by a consumer's gate (coordination reads evidence_inspections through
evidence.application.inspections.EvidenceRecords; it never writes)
Entry points: OWNED_BUCKETS, ContainerReplay
Contracts: INV-EVIDENCE-001
"""

from __future__ import annotations

from typing import Protocol

OWNED_BUCKETS = ("evidence_inspections", "evidence_inspection_notices", "completion_verdicts", "completion_rejections")


class ContainerReplay(Protocol):
    """The container run of one already authorized argv (S8 V26 rule E-2). The container inspectors delegate to it; execution provides it
    (`execution.adapters.containers.evidence_replay.ContainerEvidenceReplay`), so evidence imports no execution name. `capture` is the bounded
    attached capture the evidence side hands in; `workdir` defaults to the mounted candidate root."""

    def summary(self) -> dict: ...

    def replay(self, argv, cwd, timeout, max_bytes, env, *, capture, progress=None, workdir=...) -> dict: ...
