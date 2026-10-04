"""M7 `Executor` surface over the S4 composition, for the ported executor-level M7 suites.

Layer: harness (never shipped). A TEST shim: it lets the M7 tests that drive `Executor` run, with their
assertions unchanged, against `RunTask` (execution) and `ReviewDecisions` (review) as composition will
build them (S10). The wiring mirrors `compare/drivers/target/s4_run_task_composition.py` (RunTask) and
`s4_decision_composition.py` (ReviewDecisions); ids and clocks are NOT scripted here: as in M7 the real
clock and uuid4 are used (SYSTEM_IDS / SYSTEM_CLOCK).

Named adaptations (each is a construction/patch-point adaptation, never a behaviour change):
- `Service(store, org)` stands in for M7's `Harness(store, organization())` where a test only used it as the
  carrier of `.store` and `.org` (the target `packaged_organization()` by default).
- `AppServer` and `ClaudeCodeRuntime` are module-level names looked up AT OPEN TIME: a test replaces them with
  `monkeypatch.setattr("m7_executor.AppServer", ...)`, the adapted form of M7's
  `"codex_harness.adapters.executor.AppServer"`. The defaults are the target Claude transport with its host
  facilities injected (the `ClaudeHost` below, with observation's real `redact_text`) and an App Server that
  raises AssertionError (an unstubbed host Codex would be a real provider call).
- `execution_policy` is built on first use from the alias-normalized environment (M7
  `adapters/configuration.settings()` without the repository .env) through the target
  `routing.adapters.provider_policy.host_policy`, so `monkeypatch.setenv` before the first run still routes and
  `executor._execution_policy = None` re-reads the environment.
- `_run` and `_inspect_evidence` are methods of the shim: RunTask's own `_run` and the review invoker call
  through them, so `monkeypatch.setattr(executor, "_run", ...)` works as it did in M7. `_inspect_evidence`
  forwards to `self.evidence_gate`: #7 is composed by `composition.evidence_gate` (the EvidenceGate and the inspector selection);
  `evidence` forwards to `evidence_gate.evidence`, and an isolation stand-in without `config`/`root`/`docker` keeps M7's own
  `isolation.inspector(...)` call.
- An isolation object without `summary()`/`review_context()` (the M7 tests' stand-ins) is wrapped so the RunTask isolation
  port is met over its `config` (`container_spec.summary`, `owned_container.isolated_review_context`).
- P9 additions (routes added only; no existing route changed): `Executor._fail_task` is RunTask's, `Executor._open_runtime` is
  `Transports.open` (M7 `Executor._open_runtime`), and the Transports gets the evidence adapters' `worker_delivery` and
  `container_worker_delivery` (the profiled-implementation delivery composition wires; unused without a profile), and RunTask
  gets `policy_refusals=(DiscoveryPaused, DiscoveryRefused)` (research's discovery-pressure refusals, M7's `except` of
  `Executor.execute_one`; composition wires them, S10) and `project_evidence=_ProjectEvidence(...)`: RunTask's project-evidence
  port, the body of M7 `Executor._project_instructions` (container contexts bound to the isolation config when the profile
  requires a container) and of its profiled-schema choice (`worker_schema`).
- `run_process` and `CodexRuntime` stand for M7's `adapters.codex` module names the output-schema suite patches and calls
  (`monkeypatch.setattr(cli, "run_process", ...)`, `cli.CodexRuntime(executable)`): `CodexRuntime(executable=None)` is the target
  `execution.adapters.providers.codex_exec.CodexRuntime` with its `runner` bound to this module's `run_process` AT CALL TIME
  (default: host_os `process_groups.run_process`, the composition's runner); the test imports this module as `cli`.
- `NativeHooks(service, git, artifacts)` is M7's `adapters.hooks.NativeHooks` over its two target halves, built as
  `compare/drivers/target/s4_hooks.py` builds them: `HostHooks` (`materialize`, `configuration`) and `HookCandidates`
  (`candidate`, `canary`), with `service` as the hook lifecycle and the store owner, `git._git("show", ...)` read at call time as
  the Git `show`, research's `hook_apply` and host_os's runner and channel environment. `.git` and `.artifacts` are readable,
  and `canary`/`configuration` call `materialize` through the facade, so a test's replacement of `adapter.materialize` is seen.
- The M7 module names of `test_background_processes` (`commands`, `app_server`, `process_tree`, `isolated_worker`, `operation_cli`,
  `source_verification`, `audit_runner`, `source_execution`; `published_ports`, `port_diagnosis` and `fleet_runtime` are the target
  modules themselves) are `_View` stand-ins that route a read or an assignment to the target module that now owns the name:
  `commands` -> `host_os.adapters.process_groups` / `windows.no_console` (so `monkeypatch.setattr(commands, "os", ...)` lands on
  `process_groups.os`); `app_server` -> `execution.adapters.providers.codex_app_server` whose `AppServer(**kw)` is built with the
  `ChokepointProcesses()` port composition injects; `process_tree` -> `host_os.adapters.process_tree`, with `CREATE_SUSPENDED` and
  `_kernel32` (Windows-only names the M7 module held, read by the target's own `windows.job_objects`) routed to `job_objects`, which is
  also made visible as `process_tree.job_objects` when `os` is assigned (the module imports it only on Windows); `isolated_worker` ->
  `execution.adapters.containers.staging` (`list_revision`, `init_standalone_git`, `stage_source` with the `processes` port bound; an
  assigned `list_revision` is installed behind a wrapper that drops the port argument and restored as it was); `operation_cli` exposes
  `GitSource` (`host_os.adapters.git_source`, moved ahead of the S10 CLI); `source_verification.GitSourceVerifier`,
  `audit_runner.AuditRunner` and `source_execution.bounded_command` are the target objects with `processes=ChokepointProcesses()`.
- Batch U3 route: `Executor._task_session_owner` is RunTask's function of that name (read on the class, with a stand-in `self`).
- The context composer's threshold source is the packaged definition (`conftest.NATIVE_THRESHOLDS`), as the
  ported S2 suites supply it (research implements that port in S8).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from conftest import NATIVE_THRESHOLDS

from codex_harness.composition.evidence_gate import EvidenceGate, evidence_inspector
from codex_harness.context.adapters import worker_profile
from codex_harness.context.adapters.composition_sources import (
    GitRepository,
    ProjectSkills,
    SkillHistoryRecorder,
)
from codex_harness.context.adapters.review_context import review_context
from codex_harness.context.application.compose import ContextComposer
from codex_harness.coordination.adapters import fleet_runtime  # noqa: F401 - the M7 module name
from codex_harness.coordination.application.breaker import Breaker
from codex_harness.coordination.application.decision_claims import claim_decision
from codex_harness.coordination.application.decision_recovery import release_review_policy
from codex_harness.coordination.application.decisions import DecisionFailures, DecisionOwnership
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.execution_records import ExecutionRecords
from codex_harness.coordination.application.execution_recovery import ExecutionRecovery
from codex_harness.coordination.application.invocation_admission import InvocationBreaker
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.outbox_relay import OutboxFlusher
from codex_harness.coordination.application.sessions import SessionCheckpoints
from codex_harness.coordination.application.task_ownership import TaskOwnership
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.evidence.adapters import project_evidence
from codex_harness.evidence.application.evidence_inspection import EvidenceInspections
from codex_harness.evidence.domain.project_evidence import requires_container, worker_schema
from codex_harness.execution.adapters import execution_output, output_schema
from codex_harness.execution.adapters.containers import handoff, owned_container, staging
from codex_harness.execution.adapters.providers import claude_cli, codex_app_server, codex_exec
from codex_harness.execution.adapters.providers.claude_cli import claude_settings
from codex_harness.execution.adapters.providers.native_hooks import HookCandidates, HostHooks
from codex_harness.execution.adapters.transports import Transports
from codex_harness.execution.application.invocation_ledger import InvocationLedger
from codex_harness.execution.application.run_task import RunTask
from codex_harness.execution.domain import container_spec
from codex_harness.execution.domain.output_contracts import DIAGNOSIS, VERDICT
from codex_harness.host_os.adapters import (  # noqa: F401 - port_diagnosis, published_ports: the M7 module names
    git_source,
    port_diagnosis,
    process_groups,
    published_ports,
)
from codex_harness.host_os.adapters import (
    process_tree as _process_tree,
)
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses
from codex_harness.host_os.adapters.process_tree import ProcessTree, TreeOwnershipLeak
from codex_harness.host_os.adapters.windows import job_objects, no_console
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
from codex_harness.observation.adapters.observation_spool import MemorySpool
from codex_harness.observation.application.health import HealthRecords
from codex_harness.observation.application.observations import (
    MemoryDirectory,
    Observer,
    PostExecutionRecordFailure,
    ReconciliationRequired,
)
from codex_harness.observation.domain.observation import redact_text
from codex_harness.research.adapters import audit_runner as _audit_runner
from codex_harness.research.adapters import source_execution as _source_execution
from codex_harness.research.adapters import source_verification as _source_verification
from codex_harness.research.application.audit_gate import inspect_approval, require_adoption
from codex_harness.research.application.hooks import HookLifecycle
from codex_harness.research.domain.discovery_pressure import DiscoveryPaused, DiscoveryRefused
from codex_harness.research.domain.recurrence import hook_apply
from codex_harness.research.domain.research import require_dispatch
from codex_harness.review.application.decisions import ReviewDecisions
from codex_harness.review.application.releases import Releases
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.routing.adapters.provider_policy import host_policy

CLAUDE_HOST = claude_cli.ClaudeHost(runner=process_groups.run_process, trees=ProcessTree, tree_leak=TreeOwnershipLeak,
                                    worker_profiles=worker_profile, redact=redact_text)


def AppServer(**kwargs):  # noqa: N802 - the M7 patch-point name
    raise AssertionError("AppServer reached in an M7 executor test without a stub")


def ClaudeCodeRuntime(**kwargs):  # noqa: N802 - the M7 constructor form, adapted: the host is injected
    return claude_cli.ClaudeCodeRuntime(**kwargs, host=CLAUDE_HOST)


run_process = process_groups.run_process


def CodexRuntime(executable=None):  # noqa: N802 - the M7 constructor form, adapted: the runner is injected
    return codex_exec.CodexRuntime(executable, runner=lambda *args, **kwargs: run_process(*args, **kwargs))


class _View:
    """An M7 module name over the target module(s) that now own its names (reads and assignments are routed)."""

    def __init__(self, *modules, routes=None, extra=None):
        object.__setattr__(self, "_modules", modules)
        object.__setattr__(self, "_routes", dict(routes or {}))
        object.__setattr__(self, "_extra", dict(extra or {}))

    def _owner(self, name):
        if name in self._routes:
            return self._routes[name]
        for module in self._modules:
            if hasattr(module, name):
                return module
        raise AttributeError(name)

    def __getattr__(self, name):
        if name in self._extra:
            return self._extra[name]
        return getattr(self._owner(name), name)

    def __setattr__(self, name, value):
        if name in self._extra:
            self._extra[name] = value
        else:
            setattr(self._owner(name), name, value)

    def __delattr__(self, name):
        delattr(self._owner(name), name)


commands = _View(process_groups, no_console)


def _host_app_server(**kwargs):
    return codex_app_server.AppServer(**kwargs, processes=ChokepointProcesses())


app_server = _View(codex_app_server, extra={"AppServer": _host_app_server})


class _ProcessTreeView(_View):
    def __setattr__(self, name, value):
        if name == "os":  # the Windows branch reads `job_objects`, which the module imports only on Windows
            self._modules[0].__dict__.setdefault("job_objects", job_objects)
        super().__setattr__(name, value)


process_tree = _ProcessTreeView(_process_tree, routes={"CREATE_SUSPENDED": job_objects, "_kernel32": job_objects})
_STAGING_LIST_REVISION = staging.list_revision


def _bound_list_revision(repository, revision):
    return _STAGING_LIST_REVISION(repository, revision, processes=ChokepointProcesses())


class _IsolatedWorkerView(_View):
    def __getattr__(self, name):
        return _bound_list_revision if name == "list_revision" and staging.list_revision is _STAGING_LIST_REVISION \
            else super().__getattr__(name)

    def __setattr__(self, name, value):
        if name != "list_revision":
            return super().__setattr__(name, value)
        if value is _bound_list_revision:  # monkeypatch's undo: put the module's own function back
            staging.list_revision = _STAGING_LIST_REVISION
        else:
            staging.list_revision = lambda repository, revision, *, processes: value(repository, revision)


def _staged(function):
    def call(*args, **kwargs):
        return function(*args, processes=ChokepointProcesses(), **kwargs)
    return call


isolated_worker = _IsolatedWorkerView(staging, extra={
    "init_standalone_git": _staged(staging.init_standalone_git), "stage_source": _staged(staging.stage_source)})
operation_cli = _View(extra={"GitSource": git_source.GitSource})
source_verification = _View(extra={"GitSourceVerifier": lambda repository, artifacts: _source_verification.GitSourceVerifier(
    repository, artifacts, processes=ChokepointProcesses())})
audit_runner = _View(extra={"AuditRunner": lambda root, artifacts, host_execution=False: _audit_runner.AuditRunner(
    root, artifacts, host_execution, processes=ChokepointProcesses())})
source_execution = _View(extra={"bounded_command": lambda argv, timeout: _source_execution.bounded_command(
    argv, timeout, processes=ChokepointProcesses())})


class _FacadeHost(HostHooks):
    """HostHooks whose `materialize` goes through the facade (M7's `self.materialize`)."""

    def __init__(self, owner, *args):
        super().__init__(*args)
        self.owner = owner

    def materialize(self, hook):
        return self.owner.materialize(hook)


class NativeHooks:
    def __init__(self, service, git, artifacts):
        self.service, self.git, self.artifacts = service, git, artifacts
        show = lambda spec, strip=True: self.git._git("show", spec, strip=strip)  # noqa: E731 - read at call time
        self._host = _FacadeHost(self, service, show, artifacts, sys.executable)
        self._candidates = HookCandidates(service, service.store, show, self._host, validate=hook_apply,
                                          runner=process_groups.run_process,
                                          channel_environment=process_groups.python_channel_environment,
                                          interpreter=sys.executable)

    def materialize(self, hook):
        return HostHooks.materialize(self._host, hook)

    def configuration(self):
        return self._host.configuration()

    def candidate(self, hook_id, candidate):
        return self._candidates.candidate(hook_id, candidate)

    def canary(self, hook_id):
        return self._candidates.canary(hook_id)


def aliases(layer: dict[str, str]) -> dict[str, str]:
    """M7 `adapters/configuration.aliases`, copied: Zeus wins within one layer."""
    result = dict(layer)
    suffixes = {key.split("_", 1)[1] for key in layer if key.startswith(("ZEUS_", "HARNESS_"))}
    for suffix in suffixes:
        value = layer.get("ZEUS_" + suffix, layer.get("HARNESS_" + suffix))
        result["ZEUS_" + suffix] = result["HARNESS_" + suffix] = value
    return result


def no_operations(tx, message):
    """These executions create no operations, so M7 park returns None for every message here (S5 moves park)."""
    return None


class Service:
    """The carrier of `.store` and `.org` (M7 `Harness(store, organization())`)."""

    def __init__(self, store, org=None):
        self.store, self.org = store, org if org is not None else packaged_organization()

    def flush_outbox(self, bus, limit=100, audit=None, correlation_id=None):
        """M7 `Harness.flush_outbox` over the target `OutboxFlusher`, built as `m7_coordination.Harness` builds it."""
        flusher = OutboxFlusher(self.store, self.org, health=HealthRecords().record, clock=SYSTEM_CLOCK,
                                ids=SYSTEM_IDS)
        return flusher.flush(bus, limit, audit, correlation_id)


class _LazyPolicy:
    """RunTask reads `execution_policy` as an attribute; the shim binds it on first use, as M7 did."""

    def __init__(self, owner):
        self.__dict__["_owner"] = owner

    def __getattr__(self, name):
        return getattr(self._owner.execution_policy, name)


def make_workflow(store, org=None):
    """The coordination Workflow of one composition (submit with the real adoption gate, the park stub)."""
    return Workflow(store, org if org is not None else packaged_organization(),
                    ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                    adoption=require_adoption, park_terminal=no_operations, ids=SYSTEM_IDS)


class _Isolation:
    """RunTask's isolation port over an M7-style isolation object (`config` and its runtimes): at M7 `summary` and
    `review_context` were module functions of the config (`isolated_worker.summary/isolated_review_context`)."""

    def __init__(self, inner):
        self.__dict__["_inner"] = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def summary(self):
        return container_spec.summary(self._inner.config)

    def review_context(self, cwd, profile=None):
        return owned_container.isolated_review_context(cwd, self._inner.config, profile)


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


def _stand_in_refusals(isolation, evidence_profile):
    """M7 `Executor.__init__` :402-406 for an isolation stand-in: the same two refusals, then whether the profile is a container one."""
    container = requires_container(evidence_profile) if evidence_profile is not None else False
    require(isolation is None or evidence_profile is None or container,
            "Isolated worker mode refuses a host project evidence profile")
    require(not container or isolation is not None, "A container project evidence profile requires the host isolated worker")
    return container


class Executor:
    def __init__(self, service, git, artifacts, knowledge=None, research=None, observer=None, execution_policy=None,
                 evidence_profile=None, isolation=None, worker_sessions=None):
        self.service, self.git, self.artifacts = service, git, artifacts
        store, org = service.store, service.org
        self.worker_sessions, self.knowledge, self.research = worker_sessions, knowledge, research
        self._execution_policy = execution_policy
        self.evidence_profile, self.isolation = evidence_profile, isolation
        port = isolation if isolation is None or hasattr(isolation, "summary") else _Isolation(isolation)
        self.observer = observer or Observer(store, MemorySpool(uuid4().hex), component="executor",
                                             directory=MemoryDirectory())
        self.workflow = make_workflow(store, org)
        self.invocations = InvocationLedger(store)
        self.releases = Releases(store, org, ticket_binding=tickets.ticket_binding)
        self.breaker = Breaker(store)
        composer = ContextComposer(artifacts, artifacts.root, GitRepository(git),
                                   ProjectSkills(git, artifacts, NATIVE_THRESHOLDS),
                                   SkillHistoryRecorder(store, artifacts, git), knowledge)
        results = SimpleNamespace(persist=execution_output.persist_result, tool_usage=execution_output.tool_usage,
                                  preflight=output_schema.preflight, handoff_refs=handoff.handoff_refs,
                                  retain_evidence_handoff=handoff.retain_evidence_handoff)
        module = sys.modules[__name__]
        transports = Transports(
            isolation=port, evidence_profile=evidence_profile, claude_settings=claude_settings,
            worker_delivery=project_evidence.worker_delivery,
            container_worker_delivery=project_evidence.container_worker_delivery,
            host_app_server=lambda **kw: module.AppServer(**kw),
            claude_runtime=lambda **kw: module.ClaudeCodeRuntime(**kw), host_hooks=lambda: {})
        interpreter = Path(sys.executable).resolve()
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
            worker_sessions=worker_sessions, isolation=port, evidence_profile=evidence_profile,
            knowledge=knowledge, research=research, policy_refusals=(DiscoveryPaused, DiscoveryRefused),
            project_evidence=_ProjectEvidence(self),
            evidence_gate=SimpleNamespace(inspect=lambda *a, **k: self._inspect_evidence(*a, **k)),
            ids=SYSTEM_IDS)
        # RunTask reaches its own `_run`; route it through the shim so a test's patch of `executor._run` is seen.
        self._run_task_run = self.run_task._run
        self.run_task._run = lambda *a, **k: self._run(*a, **k)
        # #7 is composed by `composition.evidence_gate`; an isolation stand-in without `config`/`root`/`docker`
        # keeps M7's behaviour: its own `inspector(artifacts, profile)` (M7 `IsolatedWorker.inspector`) is called.
        if isolation is not None and not all(hasattr(isolation, a) for a in ("config", "root", "docker")):
            container = _stand_in_refusals(isolation, evidence_profile)
            inspector = isolation.inspector(artifacts, evidence_profile if container else None)
        else:
            inspector = evidence_inspector(artifacts, isolation=isolation, evidence_profile=evidence_profile)
        self.evidence_gate = EvidenceGate(EvidenceInspections(store, inspector), self.workflow, self.observer)
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
            self._execution_policy = host_policy({**aliases(dict(os.environ))})
        return self._execution_policy

    def _run(self, *args, **kwargs):
        return self._run_task_run(*args, **kwargs)

    def _invoke(self, agent, task_id, instruction, data, cwd, schema, read_only, **kwargs):
        """The VerdictInvoker port over `_run`: M7 called `_run` with the closed output schema itself."""
        return self._run(agent, task_id, instruction, data, cwd, DIAGNOSIS if schema == "diagnosis" else VERDICT,
                         read_only, **kwargs)

    def _fail_task(self, *args, **kwargs):
        return self.run_task._fail_task(*args, **kwargs)

    def _open_runtime(self, assignment, model, cwd=None, action=None, read_only=False, handoff=None):
        return self.run_task.transports.open(assignment, model, cwd, action, read_only, handoff)

    # Batch U3 route (added only): M7 `Executor._task_session_owner(self, ...)`, read on the class by the session suite with a
    # stand-in `self` that carries `worker_sessions` and `isolation`; RunTask's own function reads exactly those two attributes.
    _task_session_owner = RunTask._task_session_owner

    def _inspect_evidence(self, *args, **kwargs):
        return self.evidence_gate.inspect(*args, **kwargs)

    @property
    def evidence(self):
        return self.evidence_gate.evidence

    @evidence.setter
    def evidence(self, value):
        self.evidence_gate.evidence = value

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
