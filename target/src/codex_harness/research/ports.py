"""Research ports: the buckets research owns and the owner operations it consumes (REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: research
Owns: OWNED_BUCKETS of the research context; OutboxAppend and EventAppend, the consumer-declared shapes of
    coordination's Outbox.append and EventJournal.append; AuditArtifacts and SourceVerifier (moved from M7 `ports`);
    DecisionValidation and PendingDecisions, the shapes of coordination's ExecutionRecovery.validate_decision and
    PendingDecisions.queue that ResearchAudits calls; InvestigationCandidates, the shape of intake's
    ProgressCandidates that AuditProgress calls (S8 pilot 72); ResearchLaunchFacts, ExecutionFences and
    OutboxQuarantine, the shapes of coordination's owner-action launch facts, execution fence and outbox quarantine
    that ResearchProgram calls (S8 pilot 73)
Does not own: the outbox, events, decisions_pending and portfolio_investigations bucket bodies (coordination, intake)
Entry points: OWNED_BUCKETS, OutboxAppend, EventAppend, AuditArtifacts, SourceVerifier, DecisionValidation,
    PendingDecisions, InvestigationCandidates, ResearchLaunchFacts, ExecutionFences, OutboxQuarantine
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
                 "research_subsystems",  # paths/subsystems: written through the loop variable `kind`
                 # S8 pilot 72 (V4): the two buckets only research.application.audit_progress writes
                 "audit_progress_state", "audit_progress_windows",
                 # S8 pilot 73 (V4): the six buckets only research.application.research_program writes
                 # (research_programs is already listed above)
                 "research_program_candidates", "research_program_cycles", "research_investigation_dispatches",
                 "research_dispatch_recoveries", "research_dispatch_successors", "research_dispatch_heads")


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
    def exists(self, tx, key: str) -> bool: ...
    def queue(self, tx, row: dict) -> bool: ...


class InvestigationCandidates(Protocol):
    def progress_candidate(self, tx, identifier: str): ...
    def record_progress_candidate(self, tx, identifier: str, row: dict) -> None: ...


class ResearchLaunchFacts(Protocol):
    def launches(self, tx, owner: str) -> list: ...
    def authentic(self, action: dict, owner: str) -> bool: ...


class ExecutionFences(Protocol):
    def advance(self, tx, bucket: str, row_id: str, generation: int, owner=None) -> None: ...
    def current(self, tx, bucket: str, row_id: str): ...


class OutboxQuarantine(Protocol):
    def quarantine(self, tx, identity, item, source_hash, reason, delivery, audit=None): ...
