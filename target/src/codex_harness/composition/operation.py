"""The production Executor and its builder (OWNER-DECISIONS-S10 #2, #7, #8, #12, #16, #17, #18; DESIGN-s10 §9-§11).

Layer: composition
Owns: HOST_PROFILE, host_evidence_profile, host_isolation, build_executor, Executor
Does not own: RunTask (execution), ReviewDecisions (review), the isolated worker composition (S10 unit C5c), the research
and role ports (S10 unit C5b-2)
Entry points: build_executor, Executor, host_evidence_profile, host_isolation
Contracts: INV-PROJECT-EVIDENCE-001, INV-ISOLATED-WORKER-001, INV-OBSERVATION-001, INV-EXECUTION-IDENTITY-001

`Executor` is the production `coordination.ports.TaskRunner` (OWNER-DECISIONS-S10 #8): `execute_one` -> RunTask,
`decide_one` -> `claim_decision` + ReviewDecisions; the production counterpart of `tests/ported/m7_executor.Executor`, whose
constructor it reproduces statement for statement. `HOST_PROFILE`, `host_evidence_profile`, `host_isolation` and
`build_executor` are M7 `bootstrap.py` :59-138 (SOURCE e38aa722). Providers (A/evidence/rebuild/s10/prep-fbd439b3/
s10-connections.json, rows by function/parameter):
- observer: `composition.observation.build_observer` (D1); workflow: `composition.cli.workflow` (D2);
  invocations: `composition.invocation_budget.CapacityObservingLedger` (D3, #18b);
- transports (D4): the real `codex_app_server.AppServer` with `ChokepointProcesses`, `claude_cli.ClaudeCodeRuntime` with
  one `ClaudeHost`, `host_hooks` = `HostHooks.configuration` over `composition.cli.hook_units` (GAP #5);
- evidence_gate (D5): `composition.evidence_gate` (C5a); execution_policy (D6): `routing.adapters.provider_policy.host_policy`
  over `composition.configuration.settings`; continuations (D7): `ContinuationBindings` (GAP #16); hook_candidates (D8):
  `HookCandidates`; thresholds (D9): `research.adapters.runtime_thresholds`; host facts (D10); project_evidence (D11, #17).

Deltas from M7, named: D-ar: `audit_runner` is not passed to `build_executor` (C5b-2 composes AuditExecution; RunTask's own
refusal stands for audit tasks); D12: `isolation` is passed through unchanged; `host_isolation` raises `IsolationError`
for every configured selection until C5c (a transitional, declared refusal: it never falls back to host execution and never
constructs a provider or container object); D13: `audit_execution`, `roles`, `council`, `feedback`, `composition_admission`
and `research_admission` stay None (C5b-2); RunTask's own refusals stand.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from codex_harness import composition
from codex_harness.composition import cli, configuration
from codex_harness.composition.evidence_gate import EvidenceGate, evidence_inspector
from codex_harness.composition.invocation_budget import CapacityObservingLedger
from codex_harness.composition.observation import build_observer
from codex_harness.context.adapters import worker_profile
from codex_harness.context.adapters.composition_sources import (
    GitRepository,
    ProjectSkills,
    SkillHistoryRecorder,
)
from codex_harness.context.adapters.review_context import review_context
from codex_harness.context.application.compose import ContextComposer
from codex_harness.coordination.application.breaker import Breaker
from codex_harness.coordination.application.continuation.bindings import ContinuationBindings
from codex_harness.coordination.application.decision_claims import claim_decision
from codex_harness.coordination.application.decision_recovery import release_review_policy
from codex_harness.coordination.application.decisions import DecisionFailures, DecisionOwnership
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.execution_records import ExecutionRecords
from codex_harness.coordination.application.execution_recovery import ExecutionRecovery
from codex_harness.coordination.application.invocation_admission import InvocationBreaker
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.sessions import SessionCheckpoints
from codex_harness.coordination.application.task_ownership import TaskOwnership
from codex_harness.evidence.adapters import project_evidence
from codex_harness.evidence.application.evidence_inspection import EvidenceInspections
from codex_harness.evidence.domain.project_evidence import requires_container, worker_schema
from codex_harness.execution.adapters import execution_output, output_schema
from codex_harness.execution.adapters.containers import handoff, owned_container
from codex_harness.execution.adapters.providers import claude_cli, codex_app_server
from codex_harness.execution.adapters.providers.claude_cli import claude_settings
from codex_harness.execution.adapters.providers.native_hooks import HookCandidates, HostHooks
from codex_harness.execution.adapters.transports import Transports
from codex_harness.execution.application.invocation_ledger import InvocationLedger
from codex_harness.execution.application.run_task import RunTask
from codex_harness.execution.domain.output_contracts import DIAGNOSIS, VERDICT
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses
from codex_harness.host_os.adapters.process_tree import ProcessTree, TreeOwnershipLeak
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import IsolationError
from codex_harness.kernel.ids import SYSTEM_IDS
from codex_harness.observation.application.observations import (
    PostExecutionRecordFailure,
    ReconciliationRequired,
)
from codex_harness.observation.domain.observation import redact_text
from codex_harness.research.adapters import runtime_thresholds
from codex_harness.research.application.audit_gate import inspect_approval
from codex_harness.research.application.hooks import HookLifecycle
from codex_harness.research.domain.discovery_pressure import DiscoveryPaused, DiscoveryRefused
from codex_harness.research.domain.recurrence import hook_apply
from codex_harness.research.domain.research import require_dispatch
from codex_harness.review.application.decisions import ReviewDecisions
from codex_harness.review.application.releases import Releases
from codex_harness.routing.adapters.provider_policy import host_policy

HOST_PROFILE = "host"

# One host's Claude facilities (M7 `adapters/claude.py` read these as module names; the target injects them).
CLAUDE_HOST = claude_cli.ClaudeHost(runner=process_groups.run_process, trees=ProcessTree, tree_leak=TreeOwnershipLeak,
                                    worker_profiles=worker_profile, redact=redact_text)


def host_evidence_profile():
    """INV-PROJECT-EVIDENCE-001: the host-selected project evidence profile, or None when the host
    configured none. A configured profile that is missing or invalid raises; it never falls back."""
    return project_evidence.load_profile(configuration.settings())


def host_isolation(evidence_profile=None):
    """INV-ISOLATED-WORKER-001: the host-selected isolated worker, or None when the host configured none.

    Unknown or partial configuration, a version-1 (host) project-evidence profile beside it and a version-2
    (container) profile without it or naming another image raise here, before any executor or provider exists;
    nothing falls back to host execution. A configured selection is refused until S10 unit C5c composes the isolated
    worker (M7 :95-96 `preflight` and `IsolatedWorker`): a declared, transitional refusal that builds no provider and
    no container object."""
    config = owned_container.load_host_isolation(configuration.settings())
    container_profile = requires_container(evidence_profile)
    if config is None:
        if container_profile:
            raise IsolationError("project_evidence_profile_requires_isolation")
        return None
    if evidence_profile is not None and not container_profile:
        raise IsolationError("isolation_refuses_project_evidence_profile")
    if container_profile and evidence_profile["execution"]["image"] != config["image"]:
        # The profile names an image the host did not select: refused here, before any container.
        raise IsolationError("project_evidence_image_mismatch")
    raise IsolationError("the isolated worker composition is S10 unit C5c")


def build_executor(service=None, observer=None, execution_policy=None, knowledge=True, evidence_profile=HOST_PROFILE,
                   isolation=HOST_PROFILE, worker_sessions=None):
    """`worker_sessions` is a `WorkerSessions` owner for task-session execution, or None (default).
    `knowledge=False` builds the executor without any knowledge adapter: no hybrid query and no
    index_python/project_runtime write on rotate. `evidence_profile` is the profile an entry point already
    loaded (or None) so identity and executor share one load; by default it is read from the host
    settings here, before the executor exists and so before any provider entry."""
    profile = host_evidence_profile() if evidence_profile == HOST_PROFILE else evidence_profile
    # Same sentinel: by default the host selection is read (and refused) here, before the executor.
    isolated = host_isolation(profile) if isolation == HOST_PROFILE else isolation
    from codex_harness.host_os.adapters.git_workspace import GitWorkspace
    from codex_harness.knowledge.adapters.postgres_knowledge import PostgresKnowledge
    from codex_harness.research.adapters import discovery_pressure
    from codex_harness.research.adapters.research import ResearchSources
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts

    repository = str(configuration.repository_root())
    runtime = configuration.runtime_dir()
    artifacts = FileArtifacts(str(runtime / "artifacts"))
    remote = configuration.settings().get("HARNESS_GITHUB_REPO")
    git = GitWorkspace(repository, str(runtime / "workspaces"), remote)
    service = service or composition.build()
    adapter = PostgresKnowledge(composition.database_url()) if knowledge else None
    observer = observer or build_observer(service.store, "executor")
    return Executor(service, git, artifacts, adapter,
                    # INV-DISCOVERY-PRESSURE-001: pressure over THIS process's store (a lane store has no Fleet
                    # registry, so proactive fetches hold there; exempt intents are unaffected).
                    ResearchSources(artifacts, pressure=discovery_pressure.pressure(service.store, observer)),
                    observer=observer,
                    execution_policy=execution_policy, evidence_profile=profile,
                    # INV-WORKER-SESSION-001: only an entry point that holds a trusted continuation
                    # binding passes an owner; None keeps every other caller's exact fresh path.
                    **({} if worker_sessions is None else {"worker_sessions": worker_sessions}),
                    **({} if isolated is None else {"isolation": isolated}))


class _LazyPolicy:
    """RunTask reads `execution_policy` as an attribute; it is bound on first use, as M7 did."""

    def __init__(self, owner):
        self.__dict__["_owner"] = owner

    def __getattr__(self, name):
        return getattr(self._owner.execution_policy, name)


class _ProjectEvidence:
    """RunTask's `project_evidence` port (M7 `Executor._project_instructions` and the profiled schema choice)."""

    def __init__(self, owner):
        self.owner = owner

    def instructions(self, profile, cwd):
        if requires_container(profile):
            return project_evidence.container_execution_instructions(profile, cwd, self.owner.run_task.isolation.config)
        return project_evidence.execution_instructions(profile, cwd)

    def worker_schema(self, profile):
        return worker_schema(profile)


class Executor:
    """The production `coordination.ports.TaskRunner` (OWNER-DECISIONS-S10 #8): execute_one -> RunTask, decide_one ->
    claim_decision + ReviewDecisions; the production counterpart of `tests/ported/m7_executor.Executor`.

    Not wired here (S10 unit C5b-2; RunTask's own refusals stand): `audit_execution`, `roles`, `council`, `feedback`,
    `composition_admission` and `research_admission`."""

    def __init__(self, service, git, artifacts, knowledge=None, research=None, observer=None, execution_policy=None,
                 evidence_profile=None, isolation=None, worker_sessions=None):
        self.service, self.git, self.artifacts = service, git, artifacts
        store, org = service.store, service.org
        self.worker_sessions, self.knowledge, self.research = worker_sessions, knowledge, research
        self._execution_policy = execution_policy
        self.evidence_profile, self.isolation = evidence_profile, isolation
        self.observer = observer or build_observer(store, "executor")
        self.workflow = cli.workflow(service)
        self.invocations = CapacityObservingLedger(InvocationLedger(store), self.observer)
        self.releases = Releases(store, org, ticket_binding=tickets.ticket_binding)
        self.breaker = Breaker(store)
        units = cli.hook_units(service)
        show = lambda spec, strip=True: self.git._git("show", spec, strip=strip)  # noqa: E731 - read at call time
        self.host_hooks = HostHooks(units, show, artifacts, sys.executable)
        composer = ContextComposer(artifacts, artifacts.root, GitRepository(git),
                                   ProjectSkills(git, artifacts, runtime_thresholds),
                                   SkillHistoryRecorder(store, artifacts, git), knowledge)
        results = SimpleNamespace(persist=execution_output.persist_result, tool_usage=execution_output.tool_usage,
                                  preflight=output_schema.preflight, handoff_refs=handoff.handoff_refs,
                                  retain_evidence_handoff=handoff.retain_evidence_handoff)
        transports = Transports(
            isolation=isolation, evidence_profile=evidence_profile, claude_settings=claude_settings,
            worker_delivery=project_evidence.worker_delivery,
            container_worker_delivery=project_evidence.container_worker_delivery,
            host_app_server=lambda **kw: codex_app_server.AppServer(**kw, processes=ChokepointProcesses()),
            claude_runtime=lambda **kw: claude_cli.ClaudeCodeRuntime(**kw, host=CLAUDE_HOST),
            host_hooks=self.host_hooks.configuration)
        interpreter = Path(sys.executable).resolve()
        self.evidence_gate = EvidenceGate(
            EvidenceInspections(store, evidence_inspector(artifacts, isolation=isolation,
                                                          evidence_profile=evidence_profile)),
            self.workflow, self.observer)
        self.run_task = RunTask(
            store, org, git, artifacts,
            ledger=TaskOwnership(self.workflow, store=store, ids=SYSTEM_IDS),
            admission=InvocationBreaker(self.breaker), invocations=self.invocations,
            sessions=SessionCheckpoints(store, org, workflow=self.workflow, ids=SYSTEM_IDS),
            records=ExecutionRecords(org), observer=self.observer, composer=composer, transports=transports,
            results=results, execution_policy=_LazyPolicy(self),
            review_context=lambda cwd: review_context(cwd, interpreter), host_python=sys.executable,
            ticket_binding=tickets.ticket_binding, inspect_approval=inspect_approval,
            ReconciliationRequired=ReconciliationRequired, PostExecutionRecordFailure=PostExecutionRecordFailure,
            worker_sessions=worker_sessions, isolation=isolation, evidence_profile=evidence_profile,
            knowledge=knowledge, research=research, policy_refusals=(DiscoveryPaused, DiscoveryRefused),
            project_evidence=_ProjectEvidence(self), evidence_gate=self.evidence_gate,
            hook_candidates=HookCandidates(units, store, show, self.host_hooks, validate=hook_apply,
                                           runner=process_groups.run_process,
                                           channel_environment=process_groups.python_channel_environment,
                                           interpreter=sys.executable),
            continuations=ContinuationBindings(store), ids=SYSTEM_IDS)
        self.recovery = ExecutionRecovery(store, org, artifacts)
        self.hooks = HookLifecycle(org, outbox=Outbox(), events=EventJournal(), ids=SYSTEM_IDS)
        self.decisions = ReviewDecisions(
            store, org, ownership=DecisionOwnership(self.workflow, self.recovery, org, ids=SYSTEM_IDS),
            failures=DecisionFailures(self.workflow, store), outbox=Outbox(), events=EventJournal(),
            releases=self.releases, hooks=self.hooks, observer=self.observer,
            invoker=SimpleNamespace(invoke=self._invoke), git=git, release_policy=release_review_policy,
            ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
            require_dispatch=require_dispatch, ReconciliationRequired=ReconciliationRequired,
            PostExecutionRecordFailure=PostExecutionRecordFailure, worker_sessions=worker_sessions, ids=SYSTEM_IDS)

    @property
    def execution_policy(self):
        """The packaged execution policy bound to this host's configuration (read on first use, as M7)."""
        if self._execution_policy is None:
            self._execution_policy = host_policy(configuration.settings())
        return self._execution_policy

    def _run(self, *args, **kwargs):
        return self.run_task._run(*args, **kwargs)

    def _invoke(self, agent, task_id, instruction, data, cwd, schema, read_only, **kwargs):
        """The VerdictInvoker port over `_run`: M7 called `_run` with the closed output schema itself."""
        return self._run(agent, task_id, instruction, data, cwd, DIAGNOSIS if schema == "diagnosis" else VERDICT,
                         read_only, **kwargs)

    def execute_one(self, agent, expected=None):
        return self.run_task.execute_one(agent, expected)

    def decide_one(self, agent, expected=None):
        store, org = self.service.store, self.service.org
        owner = str(uuid4())
        decision = claim_decision(store, org, agent, owner, expected, recovery=self.recovery,
                                  ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded)
        if not decision:
            return None
        return self.decisions.decide(agent, decision)
