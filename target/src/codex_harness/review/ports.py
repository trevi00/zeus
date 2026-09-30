"""Review ports: the buckets review owns, and the Protocols the decision unit declares (REBUILD-DESIGN-v2 §2.4, §2.7, §2.9).

Layer: ports
Context: review
Owns: OWNED_BUCKETS of the review context; the consumer-declared Protocols ReviewDecisions calls
    (DESIGN-review-decisions §2). Each has at most 6 methods; the implementations are structural and never import
    this module; composition wires them
Does not own: HandoffReader and the other review Protocols (S8); the implementations (coordination, research,
    observation, execution, host_os)
Entry points: OWNED_BUCKETS, DecisionOwnership, DecisionFailures, OutboxAppend, EventAppend, HookEffects,
    ObservationMarkers, ObservationAudit, VerdictInvoker, ReviewWorkspace
Contracts: INV-RELEASE-001, INV-SESSION-001
"""

from __future__ import annotations

from typing import Protocol

OWNED_BUCKETS = ("releases", "release_queue", "improvement_loops",  # improvement_loops: named correction (S4)
                 # S7 (DESIGN-s7 V3): the rows the moved-ahead Releases/ReleaseQueue write.
                 "deployment", "deployment_locks", "deployment_history", "research_control")


class DecisionOwnership(Protocol):
    """coordination: the fence, validation and terminal write of the claimed decision, inside the unit's tx."""

    def owned(self, tx, lease: dict) -> dict: ...
    def validate(self, tx, current: dict) -> None: ...
    def record(self, tx, current: dict) -> None: ...
    def notice(self, tx, current: dict, code: str, at: str, identity: str | None = None): ...
    def next_message(self, parent: dict, sender: str, recipient: str, action: str, details: dict) -> dict: ...
    def heartbeat(self, lease: dict) -> None: ...


class DecisionFailures(Protocol):
    """coordination: the failure writes of a decision execution."""

    def fail(self, tx, lease: dict, error: Exception) -> dict: ...
    def contain_time(self, lease: dict, error): ...
    def reconcile(self, lease: dict, error, rejection_error=None): ...


class OutboxAppend(Protocol):
    def append(self, tx, message: dict) -> None: ...


class EventAppend(Protocol):
    def append(self, tx, identity: str, body: dict) -> None: ...


class HookEffects(Protocol):
    """research: the incident record and the hook review, joining the unit's transaction."""

    def record_incident(self, message: dict, *, independent_occurrence: str | None = None, transaction) -> dict: ...
    def review(self, hook_id: str, actor: str, revision: str, spec_hash: str, passed: bool, evidence_ref: str,
               *, transaction) -> dict: ...


class ObservationMarkers(Protocol):
    """observation: the unconfirmed-effect marker and termination records (INV-OBSERVATION-001)."""

    def close_unconfirmed(self, tx, lease: dict, closure: str): ...
    def termination_id(self, lease: dict) -> str: ...
    def pending_terminations(self, task_id: str, strict: bool = False) -> list[dict]: ...
    def record_termination(self, lease: dict, **fields) -> str: ...


class ObservationAudit(Protocol):
    """observation: the mandatory audit row in the caller's transaction, and its identity helpers."""

    def audit(self, tx, event_type: str, outcome: str, *, identity, **fields) -> dict: ...
    def for_lease(self, lease: dict, **fields) -> dict: ...
    def correlation(self, lease: dict | None) -> str | None: ...


class VerdictInvoker(Protocol):
    """execution: one read-only reviewer invocation outside any transaction (§2.9 rule 4); RunTask supplies it.
    `schema` names the output contract ("verdict" or "diagnosis"); the invoker maps it to execution's own."""

    def invoke(self, agent: str, task_id: str, instruction: str, data: dict, cwd: str, schema: str,
               read_only: bool, *, heartbeat, lease: dict, workload: str) -> dict: ...


class ReviewWorkspace(Protocol):
    """host_os: the reviewer's checkout (M7 `git.inspect/review_workspace/_git`)."""

    repository: object

    def inspect(self, revision: str, base: str) -> dict: ...
    def review_workspace(self, revision: str, review_id: str) -> str: ...
    def _git(self, *args: str, cwd: str | None = None, strip: bool = True) -> str: ...


class ExecutionFences(Protocol):
    """coordination: the execution fence rows ReleaseQueue advances and re-checks (S7 V3; coordination owns them)."""

    def advance(self, tx, bucket, row_id, generation, owner=None, *, clock=None): ...

    def require_current(self, tx, bucket, row_id, generation, owner=None): ...


class HookRollback(Protocol):
    """research: a rolled-back release's hook restored in the caller's transaction (S7 V3 R6)."""

    def roll_back(self, tx, record: dict) -> None: ...
