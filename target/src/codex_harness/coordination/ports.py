"""Coordination ports: the buckets coordination owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: coordination
Owns: OWNED_BUCKETS of the coordination context
Does not own: the implementations of the Protocols it declares (TaskRunner, PortfolioLineage, ...: other contexts and
    the coordination adapters)
Entry points: OWNED_BUCKETS
Contracts: INV-EXECUTION-IDENTITY-001

S4 (lead decision Option A) declares the buckets its moved-ahead owner operations write; S5 adds the rest.
"""

from __future__ import annotations

from typing import Protocol

OWNED_BUCKETS = ("tasks", "decisions_pending", "outbox", "events", "execution_fences", "execution_notices",
                 "execution_notice_errors", "execution_time_events", "workflow_inbox", "execution_rejections",
                 "execution_failures",
                 "breakers", "breaker_events", "breaker_notices", "breaker_policies", "sessions",
                 # S5 Fleet split (DESIGN-s5 §F): the four Fleet objects are this context's writers.
                 "fleet_registry", "fleet_control", "fleet_jobs", "fleet_budget_grants", "fleet_delivery",
                 "fleet_units", "fleet_recovery_receipts", "fleet_relocations", "fleet_host_migrations",
                 # S5 MessageHandler and operation finalization (DESIGN-s5 §M); the ledger owner is coordination.
                 "rebase_requests", "research_topics", "research_discoveries", "operation_dispositions",
                 "operation_message_dispositions",
                 # S5 outbox relay (DESIGN-s5 §O)
                 "outbox_attempts", "outbox_control", "outbox_delivery", "outbox_quarantine", "outbox_routes",
                 # S5 LocalCycle and Operation (DESIGN-s5 §L, §Op).
                 "local_cycles", "operations",
                 # S5 execution recovery remainder (receipts of prepare/apply).
                 "execution_recoveries",
                 # RF-RT S5 part: the persisted research-admission disposition (declared addition).
                 "research_admissions",
                 # S6 Continuation split (DESIGN-s6 §3 and §9); `continuation_bindings` is the lane store's.
                 "continuation_policies", "continuation_intents", "continuation_progress", "continuation_bindings",
                 "continuation_research_receipts", "continuation_research_supplements",
                 "continuation_capacity_grants", "continuation_requalifications",
                 # S6 OwnerActions split (DESIGN-s6 §4 and §9).
                 "owner_action_policies", "owner_actions", "owner_action_migrations",
                 "continuation_effective_bindings",
                 # S8 pilot 68 (DESIGN-s8 §7 V12): the autonomous cycle is coordination's use case.
                 "autonomous_runs")


class TaskRunner(Protocol):
    """The executor entry points a LocalCycle/Operation drives (DESIGN-s5 §P): execution.RunTask + review.ReviewDecisions."""

    def execute_one(self, agent: str, expected: dict | None = None) -> dict | None: ...

    def decide_one(self, agent: str, expected: dict | None = None) -> dict | None: ...


class DesignGate(Protocol):
    """Research's design gate (INV-DGE-001; implemented in S8): joins the claim unit, raises DgeRefused."""

    def check(self, tx, design: dict, *, repository, base_revision: str, plan: dict, now: str) -> dict: ...


class EvidenceRecords(Protocol):
    """Evidence's read of one all_checked inspection bound to an execution (INV-EVIDENCE-001)."""

    def require_all_checked(self, tx, inspection_id: str, *, policy_hash=None, binding=None) -> dict: ...


class DebateSessions(Protocol):
    """Research's debate sessions (research.application.dge.DebateSessions; INV-DGE-001), built per run over the run's store and
    clock: the autonomous cycle registers the frozen packet, submits each role's event and reads the status (S8 pilot 68, V12)."""

    def register(self, packet: dict, repository: str, sources: list, *, origin: str = "operator_submitted", owner: str | None = None,
                 binding: dict | None = None) -> dict: ...

    def submit(self, session_id: str, document: dict, *, owner: str | None = None, binding: dict | None = None) -> dict: ...

    def status(self, session_id: str) -> dict: ...


class KnowledgePromotion(Protocol):
    """Knowledge's promotion (the module knowledge.application.promotion satisfies this structurally; INV-AUTONOMOUS-001): write the
    verified graph and the receipt in the CALLER's transaction (S8 pilot 68, V12)."""

    def promote(self, tx, run_id: str, graph: dict, evidence: dict, clock=None) -> dict: ...


class ThresholdReviewRecovery(Protocol):
    """Research's threshold-review side of a decision recovery (implemented in S8; it owns threshold_review_requests)."""

    def row(self, tx, row_id: str) -> dict: ...

    def restore(self, tx, request: dict) -> None: ...


class PortfolioLineage(Protocol):
    """Intake's lineage owner operation (S6 moved ahead: intake.application.portfolio_lineage): a successor inherits
    exactly its origin's project binding inside the CALLER's transaction (DESIGN-s6 §5)."""

    def inherit(self, tx, job_id: str, origin_job_id: str, lineage: dict, now: str) -> dict | None: ...


class ConductorLauncher(Protocol):
    """The guarded conductor launch (coordination.adapters.conductor_launch.ConductorProcesses, DESIGN-s6 §6)."""

    def start(self, lane_id: str, job: dict, launch: str, token: str) -> dict: ...

    def poll(self, lane_id: str, launch: str) -> dict: ...


class ResearchEvidence(Protocol):
    """The trusted research evidence reader: `verify(ref)` checks one content-addressed reference's actual bytes."""

    def verify(self, reference) -> None: ...


class ResearchPrograms(Protocol):
    """Research's program resume (S6 moved ahead: research.application.program_state.ProgramState), in its own unit."""

    def resume(self, program_id: str) -> dict: ...
