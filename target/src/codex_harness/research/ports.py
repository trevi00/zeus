"""Research ports: the buckets research owns and the owner operations it consumes (REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: research
Owns: OWNED_BUCKETS of the research context; OutboxAppend and EventAppend, the consumer-declared shapes of
    coordination's Outbox.append and EventJournal.append; AuditArtifacts and SourceVerifier (moved from M7 `ports`);
    DecisionValidation and PendingDecisions, the shapes of coordination's ExecutionRecovery.validate_decision and
    PendingDecisions.queue that ResearchAudits calls
Does not own: the outbox, events and decisions_pending bucket bodies (coordination)
Entry points: OWNED_BUCKETS, OutboxAppend, EventAppend, AuditArtifacts, SourceVerifier, DecisionValidation,
    PendingDecisions
Contracts: INV-RECURRENCE-001, INV-MESSAGE-001
"""

from __future__ import annotations

from typing import Protocol

from codex_harness.storage.ports import ArtifactStore

OWNED_BUCKETS = ("inbox", "incidents", "hooks", "research_programs", "dge_sessions",
                 "dge_events",  # S6: ProgramState.resume; S8 pilot 65: the debate sessions
                 # S8 pilot 70 (V4): the twelve audit buckets only research.application.research writes
                 "research_adaptations", "research_approvals", "research_audits", "research_backlog",
                 "research_checkpoints", "research_evidence_history", "research_observed_assets",
                 "research_partitions", "research_paths", "research_receipts", "research_reviews",
                 "research_subsystems")  # paths/subsystems: written through the loop variable `kind`


class OutboxAppend(Protocol):
    def append(self, tx, message: dict) -> None: ...


class EventAppend(Protocol):
    def append(self, tx, identity: str, body: dict) -> None: ...


class AuditArtifacts(ArtifactStore, Protocol):
    def document(self, reference: str) -> dict: ...
    def inspect(self, reference: str) -> dict: ...


class SourceVerifier(Protocol):
    def verify(self, source, entries) -> dict: ...


class DecisionValidation(Protocol):
    def validate_decision(self, tx, row: dict) -> None: ...


class PendingDecisions(Protocol):
    def queue(self, tx, row: dict) -> bool: ...
