"""TaskOwnership: the task-execution lease operations RunTask calls (REBUILD-DESIGN-v2 §2.4; DESIGN-run-task D8).

Layer: application
Context: coordination
Owns: TaskOwnership, the implementation of execution.ports TaskLedger and TaskLifecycle. Each method delegates to
    the moved Workflow unchanged (M7 `Executor` called `self.workflow.<op>` directly), so body bytes, fences and
    refusals stay M7's; `owned` is `Workflow._owned`, `next_message` is `Workflow._next` with the injected clock/ids,
    `reconcile` is M7 `execution_rejections.reconcile` over the store
Does not own: the claim/complete/fail rules themselves (Workflow); the provider call (execution)
Entry points: TaskOwnership
Contracts: INV-SESSION-001, INV-EXECUTION-IDENTITY-001
"""

from __future__ import annotations

from codex_harness.coordination.application import execution_rejections
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.kernel.policy import POLICY


class TaskOwnership:
    """A stateless facade over one Workflow (one instance per composition)."""

    def __init__(self, workflow: Workflow, *, store=None, clock=None, ids=None, monotonic=None):
        self.workflow, self.store, self.clock, self.ids, self.monotonic = workflow, store, clock, ids, monotonic

    # execution.ports.TaskLedger
    def owned(self, tx, lease: dict) -> dict:
        return self.workflow._owned(tx, lease)

    def heartbeat(self, lease: dict, seconds: int = POLICY.task_lease_seconds):
        return self.workflow.heartbeat(lease, seconds)

    def remaining_seconds(self, lease: dict, maximum):
        return self.workflow.remaining_seconds(lease, maximum)

    def fail(self, task: dict, error: str, retryable: bool = True, **options) -> dict:
        return self.workflow.fail(task, error, retryable, **options)

    def reconcile(self, lease: dict, error, rejection_error=None):
        """A stale executor's failure is reconciled, never published (INV-SESSION-001; M7 execution_rejections)."""
        return execution_rejections.reconcile(self.store, lease, error, rejection_error, clock=self.clock,
                                              monotonic=self.monotonic)

    # execution.ports.TaskLifecycle
    def claim(self, agent: str, owner: str, **options):
        return self.workflow.claim(agent, owner, **options)

    def complete(self, task: dict, result: dict, commands=None, accept=None) -> dict:
        return self.workflow.complete(task, result, commands, accept=accept)

    def fail_execution(self, task: dict, error: Exception, *, transaction=None) -> dict:
        return self.workflow.fail_execution(task, error, transaction=transaction)

    def contain_time(self, task: dict, error):
        return self.workflow.contain_time(task, error)

    def snapshot(self) -> str:
        return self.workflow.snapshot()

    def next_message(self, parent: dict, sender: str, recipient: str, action: str, details: dict) -> dict:
        return Workflow._next(parent, sender, recipient, action, details, clock=self.clock, ids=self.ids)
