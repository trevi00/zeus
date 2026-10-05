"""The production Executor and its builder (OWNER-DECISIONS-S10 #2, #7, #8, #12, #16, #17, #18; DESIGN-s10 §9-§11).

Layer: composition
Owns: HOST_PROFILE, COMPOSITION_PROFILES, composition_profile, host_evidence_profile, host_isolation, build_executor, Executor
Does not own: RunTask (execution), ReviewDecisions (review), the isolated worker (`composition.isolation`, C5c-1),
research_admission (wired by S10 unit G20-1b, G20-D7)
Entry points: build_executor, Executor, composition_profile, host_evidence_profile, host_isolation
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

Research and role ports (C5b-2; the shim wiring of `tests/ported/m7_research.py` :245-280 and :455-460, providers by the
connections inventory): `audit_execution` = `AuditExecution(self, AuditRunner(runtime_dir()/"audit-sources", artifacts,
host_execution=True, ChokepointProcesses, process_groups.run_process, classify_isolated_run), audits=ResearchAudits(...),
notices=execution_notices, decisions=DecisionOwnership(...))` (construction cycle 1, #2: it needs the Executor, RunTask needs
it; closed by assigning `run_task.audit_execution` after RunTask); `roles` = `_Roles` over `autonomous_roles.execute_role` and
`frontdesk.execute_frontdesk` with the Executor first (cycle 2; M7 :1471-1479 passed no `snapshot` and the frontdesk took its
own default capture; since S8 R-f1 the adapter requires one, so `_Roles` supplies `desk_monitoring.monitoring_evidence(
runtime_dir()/MONITORING_FILE)`, S11 XC-5); `council` = the `autonomous_roles` module; `feedback` = `_Feedback` (`correction_feedback.deliver` with
observation's `redact_text` bound, #9, and `require_context`); `composition_admission` = `CouncilCompositionAdmission()`.
The decision side is complete as the inventory lists it: `Releases` (events, hooks, ticket_superseded, clock, ids),
`ExecutionRecovery` (threshold_reviews = `ThresholdReviewRecords`, ticket_binding, audit_binding, clock, ids),
`ReviewDecisions(audit_execution, clock)`, `claim_decision(threshold_exhausted=ThresholdReviews.exhausted)` (M7 :1752).
Gap, not written here: `ReviewDecisions.threshold_review` (M7 `review_threshold`, :1787-1789) is still absent at this head
(S8 B6; `research/adapters` has no `threshold_reviews`), so it keeps ReviewDecisions' own refusing default.

Composition profile (C5c-2; OWNER-DECISIONS-S10 #10, REBUILD-DESIGN-v2 section 4 row 8): `ZEUS_COMPOSITION_PROFILE` is
`development` or `production`. There is no default: an absent, empty or other value is unknown and the composition refuses
it (`composition_profile_unknown`) before anything is built. `production` requires isolation (`production_requires_isolation`)
and constructs no host provider transport: the Executor's `host_app_server` and `claude_runtime` factories raise
`host_transport_refused_in_production`. Which hosts set `production` is the user's decision in the consolidated U-request
(U6(c)), not code. P2's import audit is S11 (AR3), not this module.

Deltas from M7, named: D-ar: `audit_runner` is not a `build_executor` parameter (the runner is built in `Executor.__init__`
with `host_execution=True`, as M7 `bootstrap.build_executor` passed it); D12: `isolation` is passed through unchanged; `host_isolation` composes the C5c-1
`composition.isolation.isolated_worker` for a configured selection (it never falls back to host execution); D13: `research_admission` is wired by S10 unit G20-1b (G20-D7: `PersistedResearchAdmission` over `ResearchPackagePolicy`, `UvLockPins`; the RF-RT research-first admission is an intended behaviour
change M7 did not have); the five ports above are wired by C5b-2; RunTask's own refusals stand.
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
from codex_harness.coordination.application import execution_notices
from codex_harness.coordination.application.breaker import Breaker
from codex_harness.coordination.application.continuation.bindings import ContinuationBindings
from codex_harness.coordination.application.decision_claims import claim_decision
from codex_harness.coordination.application.decision_recovery import release_review_policy
from codex_harness.coordination.application.decisions import (
    DecisionFailures,
    DecisionOwnership,
    PendingDecisions,
)
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.execution_records import ExecutionRecords
from codex_harness.coordination.application.execution_recovery import ExecutionRecovery
from codex_harness.coordination.application.invocation_admission import InvocationBreaker
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.research_admission import PersistedResearchAdmission
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
from codex_harness.execution.adapters.redacting_artifacts import RedactingArtifacts
from codex_harness.execution.adapters.transports import Transports
from codex_harness.execution.application.invocation_ledger import InvocationLedger
from codex_harness.execution.application.run_task import RunTask
from codex_harness.execution.domain.output_contracts import DIAGNOSIS, VERDICT
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses
from codex_harness.host_os.adapters.process_tree import ProcessTree, TreeOwnershipLeak
from codex_harness.intake.adapters import frontdesk
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError, IsolationError, require
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
from codex_harness.observation.adapters import desk_monitoring
from codex_harness.observation.application.observations import (
    PostExecutionRecordFailure,
    ReconciliationRequired,
)
from codex_harness.observation.domain.observation import redact_credential_shapes, redact_text
from codex_harness.research.adapters import autonomous_roles, correction_feedback, runtime_thresholds
from codex_harness.research.adapters.audit_execution import AuditExecution
from codex_harness.research.adapters.audit_runner import AuditRunner
from codex_harness.research.adapters.council_composition import CouncilCompositionAdmission
from codex_harness.research.adapters.research_pins import UvLockPins
from codex_harness.research.application import audit_gate
from codex_harness.research.application.audit_gate import inspect_approval
from codex_harness.research.application.hook_rollback import HookRollback
from codex_harness.research.application.hooks import HookLifecycle
from codex_harness.research.application.research import ResearchAudits
from codex_harness.research.application.research_package_policy import ResearchPackagePolicy
from codex_harness.research.application.research_packages import ResearchPackages
from codex_harness.research.application.threshold_reviews import ThresholdReviewRecords, ThresholdReviews
from codex_harness.research.domain.discovery_pressure import DiscoveryPaused, DiscoveryRefused
from codex_harness.research.domain.recurrence import hook_apply
from codex_harness.research.domain.research import require_dispatch
from codex_harness.review.application.decisions import ReviewDecisions
from codex_harness.review.application.releases import Releases
from codex_harness.review.domain.check_results import classify_isolated_run
from codex_harness.routing.adapters.provider_policy import host_policy

HOST_PROFILE = "host"
COMPOSITION_PROFILES = ("development", "production")



def _bound_evidence_root(runtime):
    """S11 XC-6 A7: M7's unset case (`adapters/worker_profile.py:209-214`) read the host runtime directory; the adapter
    takes it as an argument, so composition binds `configuration.runtime_dir()` (read per call). A configured
    `profile_evidence_root` still wins (adapter rule)."""
    return worker_profile.evidence_root(runtime, configuration.runtime_dir())


# The worker-profile functions `ClaudeCodeRuntime` reads through `host.worker_profiles` (measured, 11), with
# `evidence_root` bound to the host runtime directory.
CLAUDE_WORKER_PROFILES = SimpleNamespace(
    load_profile=worker_profile.load_profile, verified_interpreter=worker_profile.verified_interpreter,
    hook_command=worker_profile.hook_command, profile_digest=worker_profile.profile_digest,
    merge_settings=worker_profile.merge_settings, hook_settings=worker_profile.hook_settings,
    session_directory=worker_profile.session_directory, evidence_root=_bound_evidence_root,
    profile_environment=worker_profile.profile_environment, delivery_receipt=worker_profile.delivery_receipt,
    hook_receipts=worker_profile.hook_receipts)

# One host's Claude facilities (M7 `adapters/claude.py` read these as module names; the target injects them).
CLAUDE_HOST = claude_cli.ClaudeHost(runner=process_groups.run_process, trees=ProcessTree, tree_leak=TreeOwnershipLeak,
                                    worker_profiles=CLAUDE_WORKER_PROFILES, redact=redact_text)


def composition_profile(host_settings):
    """OWNER-DECISIONS-S10 #10: the explicit composition profile. No default: absent IS unknown."""
    value = host_settings.get("ZEUS_COMPOSITION_PROFILE")
    if value not in COMPOSITION_PROFILES:
        raise ContractError("composition_profile_unknown")
    return value


def _host_transport_refused(**_kwargs):
    raise IsolationError("host_transport_refused_in_production")


def _host_app_server(**kw):
    return codex_app_server.AppServer(**kw, processes=ChokepointProcesses())


def _host_claude_runtime(**kw):
    return claude_cli.ClaudeCodeRuntime(**kw, host=CLAUDE_HOST)


def host_evidence_profile():
    """INV-PROJECT-EVIDENCE-001: the host-selected project evidence profile, or None when the host
    configured none. A configured profile that is missing or invalid raises; it never falls back."""
    return project_evidence.load_profile(configuration.settings())


def host_isolation(evidence_profile=None):
    """INV-ISOLATED-WORKER-001: the host-selected isolated worker, or None when the host configured none.

    Unknown or partial configuration, a version-1 (host) project-evidence profile beside it and a version-2
    (container) profile without it or naming another image raise here, before any executor or provider exists;
    nothing falls back to host execution. A configured selection composes the isolated worker
    (`composition.isolation`, C5c-1; M7 :95-96 `preflight` and `IsolatedWorker`)."""
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
    from codex_harness.composition import isolation
    return isolation.isolated_worker(config)


def build_executor(service=None, observer=None, execution_policy=None, knowledge=True, evidence_profile=HOST_PROFILE,
                   isolation=HOST_PROFILE, worker_sessions=None, profile=None):
    """`worker_sessions` is a `WorkerSessions` owner for task-session execution, or None (default).
    `knowledge=False` builds the executor without any knowledge adapter: no hybrid query and no
    index_python/project_runtime write on rotate. `evidence_profile` is the profile an entry point already
    loaded (or None) so identity and executor share one load; by default it is read from the host
    settings here, before the executor exists and so before any provider entry. `profile` overrides the
    `ZEUS_COMPOSITION_PROFILE` setting (OWNER-DECISIONS-S10 #10)."""
    chosen = profile if profile is not None else composition_profile(configuration.settings())
    require(chosen in COMPOSITION_PROFILES, "composition_profile_unknown")
    profile = host_evidence_profile() if evidence_profile == HOST_PROFILE else evidence_profile
    # Same sentinel: by default the host selection is read (and refused) here, before the executor.
    isolated = host_isolation(profile) if isolation == HOST_PROFILE else isolation
    if chosen == "production" and isolated is None:
        raise IsolationError("production_requires_isolation")
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
    if isolated is not None and getattr(isolated, "observer", False) is None:
        # S10 F2 (FLEET-REBUILD-S10-ACCEPT F2 row 3): the executor's process observer reaches the container cleanup
        # lifecycle (`cleanup_ledger.hold/retire`); an isolation that already has one, or none to take, is left alone.
        isolated.observer = observer
    return Executor(service, git, artifacts, adapter,
                    # INV-DISCOVERY-PRESSURE-001: pressure over THIS process's store (a lane store has no Fleet
                    # registry, so proactive fetches hold there; exempt intents are unaffected).
                    ResearchSources(artifacts, pressure=discovery_pressure.pressure(service.store, observer)),
                    observer=observer,
                    execution_policy=execution_policy, evidence_profile=profile,
                    host_transports=(chosen == "development"),
                    # INV-WORKER-SESSION-001: only an entry point that holds a trusted continuation
                    # binding passes an owner; None keeps every other caller's exact fresh path.
                    **({} if worker_sessions is None else {"worker_sessions": worker_sessions}),
                    **({} if isolated is None else {"isolation": isolated}))


class _TransportHooks:
    """S11 XC-6 A6: the hook source `Transports` hands the Codex role container (`Transports._container_hooks`):
    `active_hooks` is the lifecycle read of the same `units` object, `read_script(revision, path)` the reviewed script
    read exactly as `HostHooks.materialize` reads it (the same `show` handle, `revision:path`, `strip=False`)."""

    def __init__(self, units, show):
        self.units, self.show = units, show

    def active_hooks(self, **kwargs):
        return self.units.active_hooks(**kwargs)

    def read_script(self, revision, path):
        return self.show(revision + ":" + path, strip=False)


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


class _Roles:
    """RunTask's `roles` port (cycle 2): the role functions take the Executor first, as M7 `Executor._run` called them
    (M7 :1471-1479). The frontdesk adapter requires its monitoring evidence (S8 R-f1), so composition supplies the capture:
    `monitoring_evidence` over the runtime directory's `MONITORING_FILE`, M7's default capture; an unavailable capture is
    explicit unknown evidence, not a failure (S11 XC-5, TQ-XCUT-PLAN section 8 A5)."""

    def __init__(self, executor):
        self.executor = executor

    def execute_role(self, task, heartbeat):
        return autonomous_roles.execute_role(self.executor, task, heartbeat)

    def execute_frontdesk(self, task, heartbeat):
        snapshot = desk_monitoring.monitoring_evidence(configuration.runtime_dir() / desk_monitoring.MONITORING_FILE)
        return frontdesk.execute_frontdesk(self.executor, task, heartbeat, snapshot=snapshot)


class _Feedback:
    """RunTask's `feedback` port (OWNER-DECISIONS-S10 #9): the correction feedback with observation's redaction rule bound."""

    @staticmethod
    def deliver(store, artifacts, continuation):
        return correction_feedback.deliver(store, artifacts, continuation, redact=redact_text)

    @staticmethod
    def require_context(rendered_bytes, usable_bytes):
        return correction_feedback.require_context(rendered_bytes, usable_bytes)


class Executor:
    """The production `coordination.ports.TaskRunner` (OWNER-DECISIONS-S10 #8): execute_one -> RunTask, decide_one ->
    claim_decision + ReviewDecisions; the production counterpart of `tests/ported/m7_executor.Executor`.

    Not wired here: `ReviewDecisions.threshold_review` (S8 B6, absent at this head; it keeps ReviewDecisions' refusing default)."""

    def __init__(self, service, git, artifacts, knowledge=None, research=None, observer=None, execution_policy=None,
                 evidence_profile=None, isolation=None, worker_sessions=None, host_transports=True):
        self.service, self.git, self.artifacts = service, git, artifacts
        store, org = service.store, service.org
        self.worker_sessions, self.knowledge, self.research = worker_sessions, knowledge, research
        self._execution_policy = execution_policy
        self.evidence_profile, self.isolation = evidence_profile, isolation
        self.observer = observer or build_observer(store, "executor")
        self.workflow = cli.workflow(service)
        self.invocations = CapacityObservingLedger(InvocationLedger(store), self.observer)
        self.releases = Releases(store, org, ticket_binding=tickets.ticket_binding,
                                 ticket_superseded=tickets.TicketSuperseded, events=EventJournal(), hooks=HookRollback(),
                                 clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
        self.breaker = Breaker(store)
        units = cli.hook_units(service)
        show = lambda spec, strip=True: self.git._git("show", spec, strip=strip)  # noqa: E731 - read at call time
        self.host_hooks = HostHooks(units, show, artifacts, sys.executable)
        composer = ContextComposer(artifacts, artifacts.root, GitRepository(git),
                                   ProjectSkills(git, artifacts, runtime_thresholds),
                                   SkillHistoryRecorder(store, artifacts, git), knowledge)
        composer.observer = self.observer  # S10 A5-2: attribute injection; the S8 pin fixes ContextComposer.__init__
        results = SimpleNamespace(persist=execution_output.persist_result, tool_usage=execution_output.tool_usage,
                                  preflight=output_schema.preflight, handoff_refs=handoff.handoff_refs,
                                  retain_evidence_handoff=handoff.retain_evidence_handoff)
        transports = Transports(
            isolation=isolation, evidence_profile=evidence_profile, claude_settings=claude_settings,
            worker_delivery=project_evidence.worker_delivery,
            container_worker_delivery=project_evidence.container_worker_delivery,
            host_app_server=(_host_app_server if host_transports else _host_transport_refused),
            claude_runtime=(_host_claude_runtime if host_transports else _host_transport_refused),
            host_hooks=self.host_hooks.configuration, hooks=_TransportHooks(units, show))  # S11 XC-6 A6
        interpreter = Path(sys.executable).resolve()
        self.evidence_gate = EvidenceGate(
            EvidenceInspections(store, evidence_inspector(artifacts, isolation=isolation,
                                                          evidence_profile=evidence_profile)),
            self.workflow, self.observer)
        # S11 XC-2b B3: RunTask's provider-stream artifacts (`runtime-event:`, `execution:`) are redacted at write by
        # observation's `redact_text`, injected here (execution may not import observation).
        self.run_task = RunTask(
            store, org, git, RedactingArtifacts(artifacts, redact_credential_shapes),
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
            continuations=ContinuationBindings(store), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
        self.recovery = ExecutionRecovery(store, org, artifacts, ticket_binding=tickets.ticket_binding,
                                          audit_binding=audit_gate.binding,
                                          threshold_reviews=ThresholdReviewRecords(artifacts), clock=SYSTEM_CLOCK,
                                          ids=SYSTEM_IDS)
        # Construction cycles (OWNER-DECISIONS-S10 #2): AuditExecution and the roles need this Executor, RunTask needs
        # them; closed here by assignment, after RunTask exists (the shim wiring of tests/ported/m7_research.py).
        audit_validation = ExecutionRecovery(store, org, artifacts, audit_binding=audit_gate.binding, clock=SYSTEM_CLOCK,
                                             ids=SYSTEM_IDS)
        runner = AuditRunner(configuration.runtime_dir() / "audit-sources", artifacts, host_execution=True,
                             processes=ChokepointProcesses(), run_process=process_groups.run_process,
                             classify=classify_isolated_run)
        self.audit_execution = AuditExecution(
            self, runner,
            audits=ResearchAudits(store, None, artifacts, self.workflow, runner, decision_validation=audit_validation,
                                  outbox=Outbox(), pending_decisions=PendingDecisions()),
            notices=execution_notices,
            decisions=DecisionOwnership(self.workflow, audit_validation, org, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS))
        self.run_task.audit_execution = self.audit_execution
        self.run_task.roles = _Roles(self)
        self.run_task.council = autonomous_roles
        self.run_task.feedback = _Feedback()
        self.run_task.composition_admission = CouncilCompositionAdmission()
        # G20-D7 (C5b-3): the RF-RT research-first admission, in both profiles; a substantial plan/implement without an
        # accepted package holds explicitly (an intended change versus M7).
        self.run_task.research_admission = PersistedResearchAdmission(
            policy=ResearchPackagePolicy(ResearchPackages(clock=SYSTEM_CLOCK), UvLockPins(configuration.repository_root()),
                                         clock=SYSTEM_CLOCK), clock=SYSTEM_CLOCK)
        self.hooks = HookLifecycle(org, outbox=Outbox(), events=EventJournal(), ids=SYSTEM_IDS)
        self.decisions = ReviewDecisions(
            store, org, ownership=DecisionOwnership(self.workflow, self.recovery, org, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS),
            failures=DecisionFailures(self.workflow, store), outbox=Outbox(), events=EventJournal(),
            releases=self.releases, hooks=self.hooks, observer=self.observer,
            invoker=SimpleNamespace(invoke=self._invoke), git=git, release_policy=release_review_policy,
            ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
            require_dispatch=require_dispatch, ReconciliationRequired=ReconciliationRequired,
            PostExecutionRecordFailure=PostExecutionRecordFailure, worker_sessions=worker_sessions,
            audit_execution=self.audit_execution, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)

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
                                  ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                                  threshold_exhausted=ThresholdReviews.exhausted)
        if not decision:
            return None
        return self.decisions.decide(agent, decision)
