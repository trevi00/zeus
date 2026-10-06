"""M7 research-subject names over the S8 target, for the ported M7 research suites (DESIGN-s8 §29).

Layer: harness (never shipped). A TEST shim: it lets M7 `tests/test_research_*.py` run, with their assertions unchanged,
against the S8 research target. Ids and clocks are NOT scripted here: as in M7 the real clock and uuid4 are used.

Named adaptations (each is a construction/import adaptation, never a behaviour change):
- `packaged_policy` is `routing.adapters.provider_policy.packaged_policy` (M7 `adapters.providers.packaged_policy`).
- `OwnerActions(store, **ports)` is `m7_coordination.OwnerActions` (the facade over the split objects of
  `coordination.application.owner_actions`, built as the S6 composition builds it, with the SYSTEM clock and ids) with
  four more routes, for the private methods of M7's one class that the scoped-research suite calls, to the split
  homes: `_research_decide`, `_observe_dispatch` and `_discover_research` (the target's `discover`) to the
  scheduler's `research_dispatch` family, `_research_binding` (the target's `research_binding`) to its
  `research_acceptance` family. An unrouted name still raises AttributeError (never a fallback).
- `unavailable(slice_, name)` is `m7_coordination`'s.
- The research domain modules (`research_attempt_scope`, `research_program`, `research_investigations`,
  `audit_progress`, `autonomous`, `council`, `discovery_pressure`) are imported by the ported suites from
  `codex_harness.research.domain`; `continuation` and `owner_actions` from `codex_harness.coordination.domain`;
  `family_id` and the portfolio bucket names from `intake.domain.portfolio`; the owner-action, continuation and research
  bucket names from the `state` modules of their application packages; `digest`/`canonical` from `kernel.ids`;
  `MemoryStore` from `storage.adapters.memory_store`. No M7 name of this batch is without an S8-or-earlier home.

Batch P2 (research program) adds, each a construction/import adaptation:
- `ResearchProgram(store, **kwargs)` is the target class with its three composition ports wired (coordination's
  `ResearchLaunchFacts`, the `execution_fence` module, the `outbox_relay` module), as `compare/drivers/target/
  s8_program_tick.py` builds it, with the SYSTEM clock and uuid4 (the application's own default).
- `GitCapture(repository, ...)` is the target class with host_os's `process_groups.run_process` and `GitSource` wired
  (`composition.research_program_adapters.git_capture`); `ProgramRunner(...)` the target runner with the dge
  `verify_sources` wired (`composition.program_runner`); `GitSource` is `host_os.adapters.git_source.GitSource`.
- `research_program` is a namespace holding the one attribute M7's `adapters.research_program` module global
  `run_process` (host_os's runner); the shim's `GitCapture` reads it at call time, so a test's
  `monkeypatch.setattr(research_program, "run_process", ...)` reaches it as it reached the M7 global.
- `monitoring.research_program_facts(store)` is exactly `ResearchProgram(store).monitor()` (the driver's binding of the
  ledger target `observation.adapters.collectors:research_program_facts`, whose projection is wired by composition).
- `repository_identity(path)` is M7 `adapters.dge_cli.repository_identity` BODY, verbatim (`digest(str(Path(path).resolve()))`),
  a labelled copy: its ledger home `entry.cli.dge` is the S10 CLI module, absent from the target (the precedent is
  `m7_coordination.ResearchEvidence`). It is NOT `coordination.domain.fleet.repository_identity`, whose body differs.
- `SOURCE`, `FAMILY`, `INVESTIGATION`, `DEFINITIONS`, `JOBS` and `portfolio` are NOT here: they are M7 `tests/test_research_investigations.py`'s own
  definitions, imported by the ported suites from the ported `test_research_investigations` (batch P5), as M7's suites import them.
- `organization`, `Harness`, `Workflow`, `relay` are `m7_coordination`'s (M7 `bootstrap.organization`,
  `application.service.Harness`, `application.workflow.Workflow`, `application.outbox.relay`).
- `CouncilRun(service, executor=None, bus=None, workflow=None, budget=None, collector=None, verify_sources=None,
  repository=None, observer=None, clock=utcnow, evidence=None, snapshot=None, artifacts=None)` is the target class with its
  four composition ports (research's `DebateSessions`, evidence's `EvidenceRecords`, knowledge's `promotion`, the S5
  `Operation` over the service as `s8_council.py` builds it), M7's positional arguments unchanged.
Batch P3 (research audits) adds, each a construction/import adaptation:
- `ResearchAudits(store, verifier, artifacts, workflow, runner=None)` is the target class with its three composition ports wired
  (coordination's `ExecutionRecovery` with research's `audit_gate.binding` as `decision_validation`, `Outbox`, `PendingDecisions`),
  as `compare/drivers/target/s8_audit_core.py` builds it, with the SYSTEM clock and ids.
- `AuditExecution(executor, runner)` is the target class over the `ResearchAudits` above built from the executor's
  `service.store`, `artifacts` and `workflow` (as M7's constructor built it), with coordination's `execution_notices` module and
  `DecisionOwnership` wired as `s8_audit_execution.py` wires them.
- `GitSourceVerifier(repository, artifacts, *, processes=None)` is the target class with host_os's `ChokepointProcesses` as the
  default `processes` (`AuditRunner.acquire` passes its own, the same chokepoint).
- `AuditRunner(root, artifacts, host_execution=False)` is the target class with `ChokepointProcesses`, a `run_process` read at call
  time from the `audit_runner` namespace (M7's module global `adapters.audit_runner.run_process`; the ported suite patches
  `m7_research.audit_runner.run_process`) and review's `classify_isolated_run`; its `acquire` builds the shim's `GitSourceVerifier`,
  so a patch of that class's `git` reaches the verifier `acquire` returns as it did in M7.
- `DockerSourceRunner(root, artifacts, docker='docker')` is the target class with `ChokepointProcesses`, a `run_process` read at call
  time from the `source_execution` namespace and `classify_isolated_run`; the namespace also holds `bounded_command(argv, timeout)`,
  M7's module global (the target module's takes the `processes` port too): `execute` runs with the target module's `bounded_command`
  replaced by one that calls the namespace's, restored afterwards. The ported suite patches `m7_research.source_execution.*`.
- `schedule_audits(service, audit_id=None)` is the target function with the `Outbox` and the bound `reconcile_audits` of `Releases`
  (as `s8_scheduling.py` wires them, `Releases` being `m7_delivery.Releases`), over the service's store and organization.
- `AuditProgress(store, artifacts, policy=None, clock=utcnow)` is the target class with intake's `ProgressCandidates`; `AuditRepair(store,
  org, artifacts, replay=None, clock=utcnow)` is the target class with `Outbox`, `EventJournal` and the `execution_notices` module.
- `ArtifactMaintenance(store, artifacts)` is the target class with `EventJournal` and the system clock.
- `Releases` is `m7_delivery.Releases`; `Portfolio` is intake's; `AppServer` is the execution provider's.
- `audit_service` is a namespace over the three R-c25 homes of M7 `adapters/audit_service.py` (S10 unit C6b): `AuditServiceRunner`,
  `analysis_facts`, `progress_facts` and `PROGRESS_ATTRIBUTES` are `coordination.application.audit_service`'s, `status` and `execute` are
  `entry.cli.audit_service._status` and `_execute`, and `build_runner` is `composition.cli_audit_service.build_runner`. The target runner takes
  its `schedule` explicitly (V-c25): this module's `AuditServiceRunner` is the target class defaulting `schedule` to this module's
  `schedule_audits` (the verbatim `runner` copy below passes none; `test_audit_progress.service_runner` passes it explicitly).
- `FixtureBus`, `FixtureExecutor`, `connected`, `runner`, `partitions_of`, `spool_observer` and `REVISION` are M7
  `tests/test_audit_service.py`'s helper definitions, verbatim, labelled copies (that suite is S10-carried, so no ported module
  exists): `validate_message` is storage's, `Harness`/`Workflow` the `m7_coordination` ones, `Observer`, `MemorySpool` and
  `MemoryDirectory` observation's; `runner` builds `audit_service.AuditServiceRunner`, so it raises for S10 when used.
Batch P4 (research council) adds, each a construction/import adaptation:
- `AutonomousRun(service, executor=None, bus=None, workflow=None, budget=None, collector=None, verify_sources=None,
  repository=None, observer=None, clock=utcnow, evidence=None)` is the target class with its four composition ports
  (research's `DebateSessions`, evidence's `EvidenceRecords`, knowledge's `promotion`, the S5 `Operation` over the service as
  `s8_autonomous.py` builds it), M7's positional arguments unchanged, with the SYSTEM clock and ids; `CouncilRun` (above) is
  built the same way.
- `Operation(service, executor=None, bus=None, workflow=None, budget=None, collector=None, observer=None)` is the S5 class built as
  `m7_coordination.Operation` builds it, with research's `dge.design_gate` as its design gate (M7's Operation held the gate).
- `load_isolation(settings)` is `execution.adapters.containers.owned_container.load_host_isolation` (the M7 `adapters.isolated_worker`
  name, as the `m7_containers.iw` namespace binds it).
- `Executor(...)` is `m7_executor.Executor` (a later `executor.isolation = ...` assignment reaches its RunTask and transports, as M7's
  call-time read did) with the V32 council composition wired into its RunTask as S10 composition will wire it
  (DESIGN-s8 §30.1): `council=research.adapters.autonomous_roles`, `feedback=RedactedFeedback()` (an object whose `deliver(store, artifacts, binding)` is
  the redact-bound `deliver` of batch P5 below, as S10 composition will wire it; not the bare `correction_feedback` module),
  `composition_admission=CouncilCompositionAdmission()`; `m7_executor.AppServer`/`ClaudeCodeRuntime` stay the patch points.
- The artifact-reader and verdict-schema constants of M7 `adapters.executor`
  are `execution.domain.output_contracts`'s; M7's `adapters.bus` names are `storage.adapters.redis_bus`'s, and a patch of its
  `Redis` global targets that module.
Batch P5 (research feedback) adds, each a construction/import adaptation:
- `observe_source(path)` is the target `research.adapters.reverse_source.observe_source` with host_os's `run_process` injected as the
  target requires (V18 R-rs1), read at call time from the `reverse_source` namespace (M7's module global
  `adapters.reverse_source.run_process`; the ported suite patches `m7_research.reverse_source.run_process`).
- `deliver(store, artifacts, binding)` is the target `research.adapters.correction_feedback.deliver` with observation's `redact_text` injected
  as its `redact` rule (V18 R-cf1), as `compare/drivers/target/s8_correction_feedback.py` binds it.
- `DiscoveryPressure(store, policy_document, observer, ...)` is the target class with coordination's `DiscoveryCensusReader` wired as its
  `census` port, as `composition.discovery_pressure` and `compare/drivers/target/s8_sources.py` wire it. `Fleet` is `m7_coordination.Fleet`
  (the S5 facade) with M7's static `Fleet._registry` (`coordination.application.fleet.state.registry`, identical, V15), as that driver binds it.
- `monitoring.discovery_pressure_facts(store)` is the observation collector's with its `project` port bound to the target `status` (the
  composition S10 wires; M7's was exactly `status(store)`).
- `events(empty=False)` is M7 `tests/test_threshold_collection.py`'s helper, verbatim, a labelled copy (that suite is S10-carried, so no
  ported module exists). `policy_repo` (that suite's fixture, S10 unit T1) builds its repository from the TARGET constants
  (`research.adapters.threshold_policy.POLICY_PATHS` under `GIT_PREFIX`, V20 section 18), and `current_policy` is that module's.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import m7_executor
import pytest
from m7_coordination import Fleet as _Fleet
from m7_coordination import Harness, Workflow, organization, packaged_policy, relay, unavailable
from m7_coordination import OwnerActions as _OwnerActions
from m7_delivery import Releases

import codex_harness
from codex_harness.composition import cli_audit_service as _audit_service_composition
from codex_harness.coordination.application import audit_service as _audit_service
from codex_harness.coordination.application import autonomous as _autonomous
from codex_harness.coordination.application import council as _council
from codex_harness.coordination.application import (
    execution_fence,
    execution_notices,
    execution_recovery,
    outbox_relay,
)
from codex_harness.coordination.application.decisions import DecisionOwnership, PendingDecisions
from codex_harness.coordination.application.discovery_census_reader import DiscoveryCensusReader
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.fleet import state as fleet_state
from codex_harness.coordination.application.operation import Operation as _Operation
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.research_launch_facts import ResearchLaunchFacts
from codex_harness.entry.cli import audit_service as _audit_service_entry
from codex_harness.evidence.application.inspections import EvidenceRecords
from codex_harness.execution.adapters.containers import owned_container
from codex_harness.execution.adapters.providers.codex_app_server import AppServer
from codex_harness.execution.domain.output_contracts import VERDICT
from codex_harness.host_os.adapters import git_source, process_groups
from codex_harness.host_os.adapters.git_workspace import GitWorkspace
from codex_harness.intake.application.progress_candidates import ProgressCandidates
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, canonical, digest, utcnow
from codex_harness.knowledge.application import promotion as knowledge_promotion
from codex_harness.observation.adapters import collectors
from codex_harness.observation.adapters.observation_spool import MemorySpool
from codex_harness.observation.application.observations import MemoryDirectory, Observer
from codex_harness.observation.domain.observation import redact_text
from codex_harness.research.adapters import audit_execution as _audit_execution
from codex_harness.research.adapters import audit_runner as _audit_runner
from codex_harness.research.adapters import autonomous_roles, correction_feedback, dge_sources
from codex_harness.research.adapters import research_program as _adapter
from codex_harness.research.adapters import reverse_source as _reverse_source
from codex_harness.research.adapters import source_execution as _source_execution
from codex_harness.research.adapters import source_verification as _source_verification
from codex_harness.research.adapters import threshold_policy as _threshold_policy
from codex_harness.research.adapters.council_composition import CouncilCompositionAdmission
from codex_harness.research.adapters.threshold_reviews import review_threshold
from codex_harness.research.application import audit_gate, dge
from codex_harness.research.application import audit_progress as _audit_progress
from codex_harness.research.application import audit_repair as _audit_repair
from codex_harness.research.application import discovery_pressure as _discovery_pressure
from codex_harness.research.application import research as _research
from codex_harness.research.application import research_program as _application
from codex_harness.research.application import scheduling as _scheduling
from codex_harness.research.application.threshold_reviews import ThresholdReviewRecords, ThresholdReviews
from codex_harness.research.domain.research import PartitionCheckpoint
from codex_harness.review.domain.check_results import classify_isolated_run
from codex_harness.storage.adapters import maintenance as _maintenance
from codex_harness.storage.adapters.message_schema import validate_message

__all__ = ["AppServer", "ArtifactMaintenance", "AuditExecution", "AuditProgress", "AuditRepair", "AuditRunner", "AutonomousRun",
           "CouncilRun", "Executor",
           "DockerSourceRunner", "FixtureBus", "FixtureExecutor", "GitCapture", "GitSource",
           "GitSourceVerifier", "Harness", "Operation", "OwnerActions", "ProgramRunner", "REVISION", "Releases",
           "ResearchAudits", "ResearchProgram", "Workflow", "audit_runner", "audit_service", "connected", "DiscoveryPressure", "Fleet", "current_policy", "deliver", "events", "load_isolation", "monitoring",
           "observe_source", "organization", "packaged_policy", "partitions_of", "policy_repo", "relay", "repository_identity", "research_program",
           "runner", "schedule_audits", "source_execution", "spool_observer", "unavailable"]

GitSource = git_source.GitSource
research_program = SimpleNamespace(run_process=process_groups.run_process)


class ResearchProgram(_application.ResearchProgram):
    def __init__(self, store, **kwargs):
        super().__init__(store, launch_facts=ResearchLaunchFacts(), fences=execution_fence, outbox_quarantine=outbox_relay,
                         **kwargs)


class GitCapture(_adapter.GitCapture):
    def __init__(self, repository, *args, **kwargs):
        def run_process(*a, **k):  # read at call time, as M7 read its module global
            return research_program.run_process(*a, **k)
        super().__init__(repository, *args, run_process=run_process, git_source=git_source.GitSource, **kwargs)


class ProgramRunner(_adapter.ProgramRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, verify_sources=dge_sources.verify_sources, **kwargs)


monitoring = SimpleNamespace(
    research_program_facts=lambda store: ResearchProgram(store).monitor(),
    discovery_pressure_facts=lambda store: collectors.discovery_pressure_facts(store, project=_discovery_pressure.status))


def repository_identity(repository) -> str:
    """The same resolved-repository digest `operate` records in its identity, so the claim-time
    gate compares like with like; the path itself is never stored."""
    return digest(str(Path(repository).resolve()))


class CouncilRun(_council.CouncilRun):
    def __init__(self, service, *args, **kwargs):
        def operation_factory(executor, bus, workflow, budget, collector, observer=None):
            return _Operation(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                              executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector,
                              observer=observer, design_gate=SimpleNamespace(check=dge.design_gate),
                              evidence_records=EvidenceRecords(), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
        super().__init__(service, *args, sessions_factory=dge.DebateSessions, evidence_records=EvidenceRecords(),
                         promotion=knowledge_promotion, operation_factory=operation_factory, **kwargs)


RESEARCH_PRIVATE = {"_research_decide": ("research_dispatch", "_research_decide"),
                    "_observe_dispatch": ("research_dispatch", "_observe_dispatch"),
                    "_discover_research": ("research_dispatch", "discover"),
                    "_research_binding": ("research_acceptance", "research_binding")}


class OwnerActions(_OwnerActions):
    def __getattr__(self, name):
        route = RESEARCH_PRIVATE.get(name)
        if route is None:
            return super().__getattr__(name)
        return getattr(getattr(self.objects["scheduler"], route[0]), route[1])


# ---- batch P3: research audits ----------------------------------------------------------------------------------------------
def _recovery(store, org, artifacts):
    return execution_recovery.ExecutionRecovery(store, org, artifacts, audit_binding=audit_gate.binding,
                                                clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


class ResearchAudits(_research.ResearchAudits):
    def __init__(self, store, verifier, artifacts, workflow, runner=None):
        super().__init__(store, verifier, artifacts, workflow, runner,
                         decision_validation=_recovery(store, workflow.org, artifacts), outbox=Outbox(),
                         pending_decisions=PendingDecisions())


class AuditExecution(_audit_execution.AuditExecution):
    def __init__(self, executor, runner):
        audits = ResearchAudits(executor.service.store, None, executor.artifacts, executor.workflow, runner)
        validation = _recovery(executor.service.store, executor.workflow.org, executor.artifacts)
        super().__init__(executor, runner, audits=audits, notices=execution_notices,
                         decisions=DecisionOwnership(executor.workflow, validation, executor.workflow.org,
                                                     clock=SYSTEM_CLOCK, ids=SYSTEM_IDS))


class GitSourceVerifier(_source_verification.GitSourceVerifier):
    def __init__(self, repository, artifacts, *, processes=None):  # `acquire` passes its own (the same chokepoint)
        super().__init__(repository, artifacts, processes=processes or process_groups.ChokepointProcesses())


audit_runner = SimpleNamespace(run_process=process_groups.run_process)
source_execution = SimpleNamespace(
    bounded_command=lambda argv, timeout: _source_execution.bounded_command(
        argv, timeout, processes=process_groups.ChokepointProcesses()),
    run_process=process_groups.run_process)


class AuditRunner(_audit_runner.AuditRunner):
    def __init__(self, root, artifacts, host_execution=False):
        def run_process(*a, **k):  # read at call time, as M7 read its module global
            return audit_runner.run_process(*a, **k)
        super().__init__(root, artifacts, host_execution, processes=process_groups.ChokepointProcesses(),
                         run_process=run_process, classify=classify_isolated_run)

    def acquire(self, *args, **kwargs):
        with mock.patch.object(_audit_runner, "GitSourceVerifier", GitSourceVerifier):
            return super().acquire(*args, **kwargs)


class DockerSourceRunner(_source_execution.DockerSourceRunner):
    def __init__(self, root, artifacts, docker="docker"):
        def run_process(*a, **k):  # read at call time, as M7 read its module global
            return source_execution.run_process(*a, **k)
        super().__init__(root, artifacts, docker, processes=process_groups.ChokepointProcesses(),
                         run_process=run_process, classify=classify_isolated_run)

    def execute(self, *args, **kwargs):
        def bounded_command(argv, timeout, processes=None):  # M7's module global, read at call time
            return source_execution.bounded_command(argv, timeout)
        with mock.patch.object(_source_execution, "bounded_command", bounded_command):
            return super().execute(*args, **kwargs)


def schedule_audits(service, audit_id=None):
    releases = Releases(service.store, service.org)
    return _scheduling.schedule_audits(service, audit_id, outbox=Outbox(), reconcile_audits=releases.reconcile_audits)


class AuditProgress(_audit_progress.AuditProgress):
    def __init__(self, store, artifacts, policy=None, clock=utcnow):
        super().__init__(store, artifacts, policy=policy, clock=clock, investigations=ProgressCandidates())


class AuditRepair(_audit_repair.AuditRepair):
    def __init__(self, store, org, artifacts, replay=None, clock=utcnow):
        super().__init__(store, org, artifacts, replay=replay, clock=clock, outbox=Outbox(), events=EventJournal(),
                         notices=execution_notices)


class ArtifactMaintenance(_maintenance.ArtifactMaintenance):
    def __init__(self, store, artifacts):
        super().__init__(store, artifacts, EventJournal(), clock=SYSTEM_CLOCK)


class AuditServiceRunner(_audit_service.AuditServiceRunner):
    """The target runner with the research scheduler this module wires as its default `schedule` (V-c25: the target
    runner has none, composition injects it); M7's `runner` helper below is a verbatim copy that does not pass one."""

    def __init__(self, *args, schedule=None, **kwargs):
        super().__init__(*args, schedule=schedule_audits if schedule is None else schedule, **kwargs)


audit_service = SimpleNamespace(
    AuditServiceRunner=AuditServiceRunner, analysis_facts=_audit_service.analysis_facts,
    progress_facts=_audit_service.progress_facts, PROGRESS_ATTRIBUTES=_audit_service.PROGRESS_ATTRIBUTES,
    status=_audit_service_entry._status, execute=_audit_service_entry._execute,
    build_runner=_audit_service_composition.build_runner)

REVISION = "audit"  # the fixture release revision `activate_fixture` promotes


class FixtureBus:
    """A stand-in transport with the RedisBus surface this service uses.

    Delivery is per consumer and at least once: an entry is handed to a consumer once and stays in
    the stream until it is acknowledged, so an entry this service skips remains for its own owner.
    """

    def __init__(self):
        self.streams, self.published, self.acked, self.delivered = {}, [], [], {}

    @staticmethod
    def validate(message):
        return validate_message(message)

    def publish(self, message):
        self.validate(message)
        entry_id = str(len(self.published) + 1)
        self.published.append(message)
        self.streams.setdefault(message["who"]["recipient"], []).append(
            (entry_id, {"body": canonical(message)}))
        return entry_id

    def receive(self, agent, consumer, idle_ms=60000):
        seen = self.delivered.setdefault((agent, consumer), set())
        for entry_id, fields in self.streams.get(agent) or []:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            return entry_id, fields
        return None

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)
        self.streams[agent] = [row for row in self.streams.get(agent, []) if row[0] != entry_id]

    @staticmethod
    def decode(fields):
        return validate_message(json.loads(fields["body"]))


class FixtureExecutor:
    """Stand-in for the real Executor: it drives the REAL claim, checkpoint and complete path with
    the guard it was given, and never enters a provider. `status` and `error` are injected."""

    def __init__(self, audits, status="succeeded", error=None):
        self.audits, self.status, self.error = audits, status, error
        self.calls = []

    def execute_one(self, agent, expected=None):
        self.calls.append({"agent": agent, "expected": expected})
        workflow = self.audits.workflow
        task = workflow.claim(agent, "audit-service-fixture-" + uuid4().hex, expected=expected)
        if task is None:
            return None
        if self.error is not None:
            raise self.error
        if self.status != "succeeded":
            return workflow.fail(task, "injected failure", retryable=self.status == "retry")
        details = task["message"]["what"]["details"]
        with self.audits.store.transaction() as tx:
            partition = tx.get("research_partitions", details["partition_id"])
        # A real application checkpoint with no coverage: the generation advances and every
        # remaining path stays remaining (INV-RESEARCH-001, no semantic credit).
        saved = self.audits.checkpoint(
            task, replace(PartitionCheckpoint(**partition), cursor="fixture-cursor"), [], [])
        return workflow.complete(task, saved)


@pytest.fixture
def connected(audit):  # the `audit` fixture is imported by the requesting module
    """The existing audit fixture, partitioned, with a fixture release promoted and a Harness on
    the SAME store. The release, its reviews and its checks are fixtures, not a deployment."""
    from test_research_audits import activate_fixture
    audits, record, source, entries, _ = audit
    activate_fixture(audits, revision=REVISION)
    partitions = audits.partition(record["id"], 1)
    service = Harness(audits.store, audits.workflow.org)
    return SimpleNamespace(service=service, audits=audits, audit_id=record["id"],
                           partitions=partitions, store=audits.store)


def runner(connected, executor=None, bus=None, collector=None, **kwargs):
    bus = FixtureBus() if bus is None else bus
    executor = FixtureExecutor(connected.audits) if executor is None else executor
    return audit_service.AuditServiceRunner(
        connected.service, connected.audit_id, executor=executor, bus=bus,
        workflow=Workflow(connected.store, connected.service.org), collector=collector,
        revision=REVISION, release_id="fixture-release", sleep=lambda _: None, **kwargs), bus, executor


def spool_observer(connected):
    """A real Observer over an in-process spool: the observation contract runs, no sink is needed."""
    return Observer(connected.store, MemorySpool(uuid4().hex), component="unit",
                    directory=MemoryDirectory(), role="worker:github")


def partitions_of(connected, audit_id=None):
    with connected.store.transaction() as tx:
        return [p for p in tx.scan("research_partitions")
                if p["audit_id"] == (audit_id or connected.audit_id)]


# ---- batch P4: research council -------------------------------------------------------------------------------------------
class Operation(_Operation):
    def __init__(self, service, executor=None, bus=None, workflow=None, budget=None, collector=None, observer=None):
        super().__init__(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                         executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector,
                         observer=observer, design_gate=SimpleNamespace(check=dge.design_gate),
                         evidence_records=EvidenceRecords(), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


class AutonomousRun(_autonomous.AutonomousRun):
    def __init__(self, service, *args, **kwargs):
        def operation_factory(executor, bus, workflow, budget, collector, observer=None):
            return Operation(service, executor, bus, workflow, budget, collector, observer)
        super().__init__(service, *args, sessions_factory=dge.DebateSessions, evidence_records=EvidenceRecords(),
                         promotion=knowledge_promotion, operation_factory=operation_factory, **kwargs)


load_isolation = owned_container.load_host_isolation


class RedactedFeedback:
    """The object `run_task.feedback` is wired to (RunTask calls only `feedback.deliver(store, artifacts, binding)`): the
    target `correction_feedback.deliver` with observation's `redact_text` injected as its `redact` rule, i.e. this
    shim's `deliver` below, as S10 composition will wire it (OWNER-DECISIONS-S10 #9), not the bare module."""

    @staticmethod
    def deliver(store, artifacts, binding):
        return deliver(store, artifacts, binding)


class Executor(m7_executor.Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_task.council, self.run_task.feedback = autonomous_roles, RedactedFeedback()
        self.run_task.composition_admission = CouncilCompositionAdmission()
        # S10 unit T1: `ReviewDecisions.threshold_review` is M7's `review_threshold(self, lease, VERDICT)` with the V22 ports wired
        # (coordination's ExecutionRecovery validates a recovered decision, DecisionOwnership records it), and the recovery reads the request row
        self.recovery.threshold_reviews = ThresholdReviewRecords(self.artifacts)
        self.decisions.threshold_review = lambda lease: review_threshold(
            self, lease, VERDICT, decision_validation=self.recovery, decisions=self.decisions.ownership)

    def decide_one(self, agent, expected=None):  # M7 `decide_one` (:1752) with the threshold-review exhaustion rule wired (S10 unit T1)
        store, org = self.service.store, self.service.org
        decision = m7_executor.claim_decision(store, org, agent, str(uuid4()), expected, recovery=self.recovery,
                                              ticket_binding=m7_executor.tickets.ticket_binding,
                                              TicketSuperseded=m7_executor.tickets.TicketSuperseded,
                                              threshold_exhausted=ThresholdReviews.exhausted)
        if not decision:
            return None
        return self.decisions.decide(agent, decision)

    @property
    def isolation(self):
        return self._isolation

    @isolation.setter
    def isolation(self, value):  # M7's executor read `self.isolation` at call time: a later assignment reaches RunTask
        self._isolation = value
        run_task = self.__dict__.get("run_task")
        if run_task is not None:
            port = value if value is None or hasattr(value, "summary") else m7_executor._Isolation(value)
            run_task.isolation = run_task.transports.isolation = port


# ---- batch P5: research feedback ---------------------------------------------------------------------------------------------
reverse_source = SimpleNamespace(run_process=process_groups.run_process)


def observe_source(path):
    def run_process(*a, **k):  # read at call time, as M7 read its module global
        return reverse_source.run_process(*a, **k)
    return _reverse_source.observe_source(path, run_process=run_process)


def events(empty=False):  # M7 `tests/test_threshold_collection.py::events`, verbatim (labelled copy)
    return [{'at': f'2026-01-01T00:00:{i:02d}Z',
             'top': [{'score': score, 'body_chars': 500} for score in ([3] if empty else [3, 5])]}
            for i in range(40)]


current_policy = _threshold_policy.current_policy


@pytest.fixture
def policy_repo(tmp_path):  # M7 `tests/test_threshold_collection.py::policy_repo`; the paths are the TARGET's (V20 section 18: GIT_PREFIX, POLICY_PATHS)
    root = tmp_path / 'repo'
    root.mkdir()
    git = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    git._git('init', '-q')
    git._git('config', 'user.name', 'Fixture')
    git._git('config', 'user.email', 'fixture@localhost')
    # The committed fixture must equal the LOADED package, which `current_policy` compares against: under the
    # release evaluator's two-checkout layout (incumbent tests, candidate package) the tests' own checkout is not it.
    package = Path(codex_harness.__file__).resolve().parent
    for entry in _threshold_policy.POLICY_PATHS:
        target = root / (_threshold_policy.GIT_PREFIX + entry)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((package.parent / entry).read_text(encoding='utf-8'), encoding='utf-8')
    git._git('add', '.')
    git._git('commit', '-qm', 'policy fixture')
    return root, git


def deliver(store, artifacts, binding):
    return correction_feedback.deliver(store, artifacts, binding, redact=redact_text)


class DiscoveryPressure(_discovery_pressure.DiscoveryPressure):
    def __init__(self, store, policy_document, observer, *args, **kwargs):
        super().__init__(store, policy_document, observer, *args, census=DiscoveryCensusReader(), **kwargs)


class Fleet(_Fleet):
    _registry = staticmethod(fleet_state.registry)
