"""Target-side composition of RunTask for the S4 execution scenarios (`execution.run_task`, `effects.context_packet`).

Layer: harness (never shipped). A target-driver helper: it imports the product, so it lives beside the target
drivers, not in common/ (scenario bodies never import the product).

It wires by hand what M7's `Executor` built, and what composition will build in S10:
- coordination Workflow (submit with the real adoption gate and the `no_operations` park stub), TaskOwnership,
  Breaker/InvocationBreaker, SessionCheckpoints and ExecutionRecords;
- the target InvocationLedger and the moved Observer;
- the S2 ContextComposer over the scenario's git;
- Transports with the scenario's fixture as the host App Server and the loud Claude stub.

The ids and clocks are the scenario's scripted sources, injected. The observer's process run id is drawn where
M7's Executor constructor draws it. The host interpreter is the fixture interpreter the reference installs as
`sys.executable`.
"""

from __future__ import annotations

from types import SimpleNamespace

from codex_harness.context.adapters.composition_sources import (
    GitRepository,
    ProjectSkills,
    SkillHistoryRecorder,
)
from codex_harness.context.adapters.review_context import review_context
from codex_harness.context.application.compose import ContextComposer
from codex_harness.coordination.application.breaker import Breaker
from codex_harness.coordination.application.execution_records import ExecutionRecords
from codex_harness.coordination.application.invocation_admission import InvocationBreaker
from codex_harness.coordination.application.sessions import SessionCheckpoints
from codex_harness.coordination.application.task_ownership import TaskOwnership
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.execution.adapters import execution_output, output_schema
from codex_harness.execution.adapters.containers import handoff
from codex_harness.execution.adapters.transports import Transports
from codex_harness.execution.application.invocation_ledger import InvocationLedger
from codex_harness.execution.application.run_task import RunTask
from codex_harness.intake.application import tickets
from codex_harness.kernel.ids import utcnow
from codex_harness.observation.adapters.observation_spool import MemorySpool
from codex_harness.observation.application.observations import (
    MemoryDirectory,
    Observer,
    PostExecutionRecordFailure,
    ReconciliationRequired,
)
from codex_harness.research.application.audit_gate import inspect_approval, require_adoption
from codex_harness.routing.adapters.provider_policy import host_policy


class ClaudeRefused:
    """The unexpected transport: constructing it is a driver failure, never a provider call."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("ClaudeCodeRuntime reached in an S4 execution fixture")


def no_operations(tx, message):
    """These scenarios create no operations, so M7 park returns None for every message here (S5 moves park)."""
    return None


def run_task_for(store, org, artifacts, git, interpreter, host_app_server, *, clock, ids, monotonic, research=None):
    """(RunTask, Workflow) for one case. Build it BEFORE the case's first envelope: the observer's run id is the
    first scripted id, as in M7's Executor constructor."""
    observer = Observer(store, MemorySpool(ids.uuid4().hex), component="executor", directory=MemoryDirectory(),
                        clock=lambda: utcnow(clock), monotonic=monotonic)
    workflow = Workflow(store, org, ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                        adoption=require_adoption, park_terminal=no_operations, clock=clock, ids=ids,
                        monotonic=monotonic)
    composer = ContextComposer(artifacts, artifacts.root, GitRepository(git), ProjectSkills(git, artifacts, None),
                               SkillHistoryRecorder(store, artifacts, git, clock), None)
    results = SimpleNamespace(persist=execution_output.persist_result, tool_usage=execution_output.tool_usage,
                              preflight=output_schema.preflight, handoff_refs=handoff.handoff_refs,
                              retain_evidence_handoff=handoff.retain_evidence_handoff)
    run_task = RunTask(
        store, org, git, artifacts,
        ledger=TaskOwnership(workflow, store=store, clock=clock, ids=ids, monotonic=monotonic),
        admission=InvocationBreaker(Breaker(store, clock=clock)), invocations=InvocationLedger(store, clock=clock),
        sessions=SessionCheckpoints(store, org, workflow=workflow, ids=ids), records=ExecutionRecords(org),
        observer=observer, composer=composer,
        # No hook is active in these scenarios, so M7's NativeHooks.configuration() is {} too.
        transports=Transports(host_app_server=host_app_server, host_hooks=lambda: {}, claude_runtime=ClaudeRefused),
        results=results, execution_policy=host_policy({}),
        review_context=lambda cwd: review_context(cwd, interpreter.resolve()), host_python=str(interpreter),
        ticket_binding=tickets.ticket_binding, inspect_approval=inspect_approval,
        ReconciliationRequired=ReconciliationRequired, PostExecutionRecordFailure=PostExecutionRecordFailure,
        research=research, clock=clock, ids=ids, monotonic=monotonic)
    return run_task, workflow
