"""The decision aggregate's owner operations for the review commit unit (REBUILD-DESIGN-v2 §2.9; S4 Option A).

Layer: application
Context: coordination
Owns: DecisionOwnership (fence, validate, terminal record, notice, next message, heartbeat) and DecisionFailures
    (fail, time containment, rejection reconcile) over `decisions_pending`. These are the writes and fences that M7
    `Executor.decide_one/_commit_decision/_fail_decision/_lost_execution` performed inline with coordination's
    objects. Each delegates to the moved owner code unchanged, so the body bytes and fence placement stay M7's.
Does not own: the decision verdict and its effects (review's ReviewDecisions); the claim (decision_claims);
    the clocks (injected)
Entry points: DecisionOwnership, DecisionFailures
Contracts: INV-SESSION-001, INV-EXECUTION-IDENTITY-001, INV-RELEASE-001
"""

from __future__ import annotations

from codex_harness.coordination.application import execution_notices, execution_rejections
from codex_harness.coordination.application.workflow import Workflow

BUCKET = "decisions_pending"


class DecisionOwnership:
    """What ReviewDecisions may do to its claimed decision row, always inside the caller's transaction."""

    def __init__(self, workflow: Workflow, recovery, organization, *, clock=None, ids=None):
        self.workflow, self.recovery, self.organization = workflow, recovery, organization
        self.clock, self.ids = clock, ids

    def owned(self, tx, lease: dict) -> dict:
        # INV-SESSION-001: the fence is checked in the same transaction as the effects it guards.
        return self.workflow._owned(tx, lease)

    def validate(self, tx, current: dict) -> None:
        self.recovery.validate_decision(tx, current)

    def record(self, tx, current: dict) -> None:
        tx.put(BUCKET, current["id"], current)

    def notice(self, tx, current: dict, code: str, at: str, identity: str | None = None):
        return execution_notices.record(tx, self.organization, current, BUCKET, code, at, identity)

    def next_message(self, parent: dict, sender: str, recipient: str, action: str, details: dict) -> dict:
        return Workflow._next(parent, sender, recipient, action, details, clock=self.clock, ids=self.ids)

    def heartbeat(self, lease: dict) -> None:
        self.workflow.heartbeat(lease)


class DecisionFailures:
    """The failure writes of a decision execution. A stale executor never publishes a failure (INV-SESSION-001)."""

    def __init__(self, workflow: Workflow, store, *, clock=None, monotonic=None):
        self.workflow, self.store, self.clock, self.monotonic = workflow, store, clock, monotonic

    def fail(self, tx, lease: dict, error: Exception) -> dict:
        return self.workflow.fail_execution(lease, error, transaction=tx)

    def contain_time(self, lease: dict, error):
        return self.workflow.contain_time(lease, error)

    def reconcile(self, lease: dict, error, rejection_error=None):
        return execution_rejections.reconcile(self.store, lease, error, rejection_error, clock=self.clock,
                                              monotonic=self.monotonic)
