"""Research ports: the buckets research owns and the owner operations it consumes (REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: research
Owns: OWNED_BUCKETS of the research context; OutboxAppend and EventAppend, the consumer-declared shapes of
    coordination's Outbox.append and EventJournal.append; AuditArtifacts and SourceVerifier (moved from M7 `ports`);
    DecisionValidation and PendingDecisions, the shapes of coordination's ExecutionRecovery.validate_decision and
    PendingDecisions.queue that ResearchAudits calls; InvestigationCandidates, the shape of intake's
    ProgressCandidates that AuditProgress calls (S8 pilot 72); ResearchLaunchFacts, ExecutionFences and
    OutboxQuarantine, the shapes of coordination's owner-action launch facts, execution fence and outbox quarantine
    that ResearchProgram calls (S8 pilot 73); DiscoveryCensus, the shape of coordination's
    DiscoveryCensusReader that DiscoveryPressure calls (S8 pilot 76); GitBlobSource, the consumer shape of host_os's
    GitSource that the pinned registry reader load_registry calls (S8 pilot 91, V18 R-df1); ExecutionNotices, the shape of
    coordination's execution_notices.record that AuditRepair calls (S8 pilot 100, V18 R-ar1); DecisionRecord, the shape of
    coordination's DecisionOwnership.record that ThresholdReviews calls (S8 pilot 101, V22 R-tr2)
Does not own: the outbox, events, decisions_pending and portfolio_investigations bucket bodies (coordination, intake)
Entry points: OWNED_BUCKETS, OutboxAppend, EventAppend, AuditArtifacts, SourceVerifier, DecisionValidation,
    PendingDecisions, InvestigationCandidates, ResearchLaunchFacts, ExecutionFences, OutboxQuarantine, DiscoveryCensus,
    GitBlobSource, ExecutionNotices, DecisionRecord
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
                 "research_dispatch_recoveries", "research_dispatch_successors", "research_dispatch_heads",
                 # S8 pilot 76 (V4): the one bucket only research.application.discovery_pressure writes
                 "discovery_pressure",
                 # S8 pilot 86 (V4): the two buckets only research.application.threshold_approvals writes
                 "threshold_approvals", "threshold_approval_events",
                 # S8 pilot 88 (V4): the three buckets only research.application.reverse_progress writes and the two buckets only
                 # research.application.source_execution writes
                 "reverse_requests", "reverse_progress", "reverse_history",
                 "source_execution_requests", "source_execution_history",
                 # S8 pilot 92 (V4): the three buckets only research.application.threshold_proposals writes
                 "threshold_collection_inputs", "threshold_proposal_runs", "threshold_proposals",
                 # S8 pilot 100 (V4): the three buckets only research.application.audit_repair writes (`schedule`: M7's other
                 # writer, application/scheduling.py, is research's and not moved yet)
                 "audit_repair_activation", "audit_repair_corrections", "schedule",
                 # S8 pilot 101 (V4): the bucket only research.application.threshold_reviews writes (restore: V22 R-tr3)
                 "threshold_review_requests",
                 # S8 batch B4 (V25 R-df2): the five buckets only research.application.decision_feedback writes
                 "decision_observations", "decision_feedback_groups", "recurring_work_candidates",
                 "decision_feedback_conflicts", "decision_feedback_collections")


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


class DiscoveryCensus(Protocol):
    def observe(self, tx, ledger) -> dict: ...


class GitBlobSource(Protocol):
    def commit_exists(self, revision: str) -> bool: ...
    def blob(self, revision: str, path: str) -> tuple[str | None, bytes]: ...


class ExecutionNotices(Protocol):
    def record(self, tx, org, row: dict, bucket: str, reason_code: str, at: str, transition_ref=None, *,
               proof=None, evidence_refs=()): ...


class DecisionRecord(Protocol):
    def record(self, tx, current: dict) -> None: ...
