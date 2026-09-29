"""Execution ports: what one invocation needs from other contexts, declared by execution (§2.4, §2.5).

Layer: ports
Context: execution
Owns: OWNED_BUCKETS of the execution context; the consumer-owned Protocols RunTask depends on
    (ProviderRuntime and the rest arrive with RunTask; ARCHITECTURE.md keeps them PROPOSED until then)
Does not own: their implementations (coordination implements TaskLedger in S5, research/evidence
    implement ResearchAdmission in S8; composition wires them in S10)
Entry points: OWNED_BUCKETS, TaskLedger, ResearchAdmission, TaskLifecycle, InvocationAdmission, SessionCheckpoint, ExecutionRecords,
    ObservationEvents, ObservationMarkers, and the optional S8 ports (CorrectionFeedback, CouncilDelivery, EvidenceGate,
    RoleExecution, AuditExecution, ResearchSources, HookCandidates)
Contracts: INV-INVOCATION-001, INV-WORKER-SESSION-001, INV-EXECUTION-IDENTITY-001

Protocols are structural: an implementation never imports this module (§2.4).
"""

from __future__ import annotations

from typing import Protocol

from codex_harness.storage.ports import Transaction

OWNED_BUCKETS = ("invocation_reservations", "worker_sessions", "hook_cases", "execution_progress")


class TaskLedger(Protocol):
    """Lease ownership of one running execution (coordination's TaskOwnership, S5)."""

    def owned(self, tx: Transaction, lease: dict) -> dict:
        """The current row when `lease` still owns it (status, generation, attempt, owner, durable
        fence and deadline checked in `tx`); raises ContractError("Stale or expired task execution")."""
        ...

    def heartbeat(self, lease: dict) -> dict: ...

    def remaining_seconds(self, lease: dict, maximum: int) -> float:
        """Seconds left before the execution deadline; refuses a lost, superseded or expired lease."""
        ...


class ResearchAdmission(Protocol):
    """RF-RT (addendum A1 v2), S4 part: RunTask consults this before a design/implementation
    dispatch. S8 owns the package store; S5 persists the disposition; S10 wires it."""

    def admit(self, tx: Transaction, lease: dict, action: str) -> dict:
        """{"disposition": "admit" | "exempt" | "research" | "blocked", "reason": str}."""
        ...


class TaskLifecycle(Protocol):
    """The rest of the task-execution lease operations RunTask calls (coordination's TaskOwnership; D8)."""

    def claim(self, agent: str, owner: str, **options) -> dict | None: ...
    def complete(self, task: dict, result: dict, commands=None, accept=None) -> dict: ...
    def fail_execution(self, task: dict, error: Exception, *, transaction=None) -> dict: ...
    def contain_time(self, task: dict, error): ...
    def snapshot(self) -> str: ...
    def next_message(self, parent: dict, sender: str, recipient: str, action: str, details: dict) -> dict: ...


class InvocationAdmission(Protocol):
    """The per-invocation breaker (coordination's InvocationBreaker; D8). A refusal is before any provider."""

    def admit(self, key: str, lease: dict, now=None) -> dict: ...
    def report(self, token: dict, result: str, now=None) -> dict: ...
    def key(self, provider: str, scope: str) -> str: ...
    def verdict(self, result) -> str: ...
    def verdict_of_exception(self, error) -> str: ...


class SessionCheckpoint(Protocol):
    """The fenced session checkpoint of a turn (coordination's SessionCheckpoints; D2)."""

    def checkpoint(self, agent: str, expected_generation: int, state: dict, execution: dict | None = None) -> dict: ...


class ObservationEvents(Protocol):
    """observation: diagnostic events and the mandatory audit row (INV-OBSERVATION-001)."""

    def emit(self, event_type: str, outcome: str, **fields) -> dict | None: ...
    def system(self, *, revision=None, role=None) -> dict: ...
    def for_lease(self, lease: dict, **fields) -> dict: ...
    def correlation(self, lease: dict | None) -> str | None: ...
    def audit(self, tx, event_type: str, outcome: str, *, identity, **fields) -> dict: ...


class ObservationMarkers(Protocol):
    """observation: the unconfirmed-effect marker, the reservation guard and termination records."""

    def close_unconfirmed(self, tx, lease: dict, closure: str): ...
    def mark_unconfirmed(self, tx, lease: dict, *, reservation_id) -> dict: ...
    def guard_reservation(self, tx, lease: dict) -> None: ...
    def pending_terminations(self, task_id: str, strict: bool = False) -> list[dict]: ...
    def record_termination(self, lease: dict, **fields) -> str: ...
    def termination_id(self, lease: dict) -> str: ...


class ExecutionRecords(Protocol):
    """coordination: the notice, event, terminal-row and diagnosis-request writes of RunTask's failure paths."""

    def notice(self, tx, row: dict, bucket: str, code: str, at: str, identity: str | None = None): ...
    def append_event(self, tx, identity: str, body: dict) -> None: ...
    def record_row(self, tx, bucket: str, row: dict) -> None: ...
    def request_diagnosis(self, tx, task: dict, agent: str, error, current: dict, parent: str, receipt) -> None: ...


# S8-owned collaborators RunTask reaches on some actions. Each is optional in RunTask; an action that needs an
# absent one refuses explicitly before any provider (DESIGN-run-task D8), never a silent skip.

class CorrectionFeedback(Protocol):
    def deliver(self, store, artifacts, continuation) -> dict | None: ...
    def require_context(self, rendered_bytes: int, usable_bytes: int) -> None: ...


class CouncilDelivery(Protocol):
    def admitted_delivery(self, agent, action, read_only, stage, evidence, delivery) -> dict | None: ...
    def role_context(self, isolation_config) -> dict: ...


class EvidenceGate(Protocol):
    def inspect(self, task: dict, result: dict, workspace_path: str, heartbeat=None) -> dict: ...


class RoleExecution(Protocol):
    def execute_role(self, task: dict, heartbeat) -> dict: ...
    def execute_frontdesk(self, task: dict, heartbeat) -> dict: ...


class AuditExecution(Protocol):
    def execute(self, task: dict) -> dict: ...


class ResearchSources(Protocol):
    def collect(self, source: str, *, intent=None) -> dict: ...
    def github_detail(self, url: str) -> dict: ...


class HookCandidates(Protocol):
    def candidate(self, hook_id: str, candidate: dict) -> dict: ...

