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
- `SOURCE`, `FAMILY`, `INVESTIGATION`, `DEFINITIONS`, `JOBS` and `portfolio(store, jobs=JOBS)` are M7
  `tests/test_research_investigations.py`'s helper definitions, verbatim, labelled copies: that suite belongs to batch P5
  (not yet ported) and the chain and recovery suites cannot be collected without them (`Portfolio` and `BUCKET_JOBS`
  are the target homes). Batch P5 owns the ported module.
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
- `audit_service` is `unavailable("S10", "adapters.audit_service")`: the audit-service CLI (`entry.cli.audit_service`) is not on the
  target; a test that reaches it is skipped whole for S10.
- `FixtureBus`, `FixtureExecutor`, `connected`, `runner`, `partitions_of`, `spool_observer` and `REVISION` are M7
  `tests/test_audit_service.py`'s helper definitions, verbatim, labelled copies (that suite is S10-carried, so no ported module
  exists): `validate_message` is storage's, `Harness`/`Workflow` the `m7_coordination` ones, `Observer`, `MemorySpool` and
  `MemoryDirectory` observation's; `runner` builds `audit_service.AuditServiceRunner`, so it raises for S10 when used.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import pytest
from m7_coordination import Harness, Workflow, organization, packaged_policy, relay, unavailable
from m7_coordination import OwnerActions as _OwnerActions
from m7_delivery import Releases

from codex_harness.coordination.application import council as _council
from codex_harness.coordination.application import (
    execution_fence,
    execution_notices,
    execution_recovery,
    outbox_relay,
)
from codex_harness.coordination.application.decisions import DecisionOwnership, PendingDecisions
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.fleet.state import BUCKET_JOBS
from codex_harness.coordination.application.operation import Operation
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.research_launch_facts import ResearchLaunchFacts
from codex_harness.evidence.application.inspections import EvidenceRecords
from codex_harness.execution.adapters.providers.codex_app_server import AppServer
from codex_harness.host_os.adapters import git_source, process_groups
from codex_harness.intake.application.portfolio import Portfolio, family_id
from codex_harness.intake.application.progress_candidates import ProgressCandidates
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, canonical, digest, utcnow
from codex_harness.knowledge.application import promotion as knowledge_promotion
from codex_harness.observation.adapters.observation_spool import MemorySpool
from codex_harness.observation.application.observations import MemoryDirectory, Observer
from codex_harness.research.adapters import audit_execution as _audit_execution
from codex_harness.research.adapters import audit_runner as _audit_runner
from codex_harness.research.adapters import dge_sources
from codex_harness.research.adapters import research_program as _adapter
from codex_harness.research.adapters import source_execution as _source_execution
from codex_harness.research.adapters import source_verification as _source_verification
from codex_harness.research.application import audit_gate, dge
from codex_harness.research.application import audit_progress as _audit_progress
from codex_harness.research.application import audit_repair as _audit_repair
from codex_harness.research.application import research as _research
from codex_harness.research.application import research_program as _application
from codex_harness.research.application import scheduling as _scheduling
from codex_harness.research.domain.research import PartitionCheckpoint
from codex_harness.review.domain.check_results import classify_isolated_run
from codex_harness.storage.adapters import maintenance as _maintenance
from codex_harness.storage.adapters.message_schema import validate_message

__all__ = ["AppServer", "ArtifactMaintenance", "AuditExecution", "AuditProgress", "AuditRepair", "AuditRunner", "CouncilRun",
           "DEFINITIONS", "DockerSourceRunner", "FAMILY", "FixtureBus", "FixtureExecutor", "GitCapture", "GitSource",
           "GitSourceVerifier", "Harness", "INVESTIGATION", "JOBS", "OwnerActions", "ProgramRunner", "REVISION", "Releases",
           "ResearchAudits", "ResearchProgram", "SOURCE", "Workflow", "audit_runner", "audit_service", "connected", "monitoring",
           "organization", "packaged_policy", "partitions_of", "portfolio", "relay", "repository_identity", "research_program",
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


monitoring = SimpleNamespace(research_program_facts=lambda store: ResearchProgram(store).monitor())


def repository_identity(repository) -> str:
    """The same resolved-repository digest `operate` records in its identity, so the claim-time
    gate compares like with like; the path itself is never stored."""
    return digest(str(Path(repository).resolve()))


class CouncilRun(_council.CouncilRun):
    def __init__(self, service, *args, **kwargs):
        def operation_factory(executor, bus, workflow, budget, collector, observer=None):
            return Operation(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                             executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector,
                             observer=observer, design_gate=SimpleNamespace(check=dge.design_gate),
                             evidence_records=EvidenceRecords(), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
        super().__init__(service, *args, sessions_factory=dge.DebateSessions, evidence_records=EvidenceRecords(),
                         promotion=knowledge_promotion, operation_factory=operation_factory, **kwargs)


# M7 `tests/test_research_investigations.py` helpers, verbatim (labelled copies; see the docstring).
SOURCE = {"topic": "storage", "project_ids": ["ops"], "reason_codes": ["store_timeout"]}
FAMILY = ("failed", "store_timeout")
INVESTIGATION = family_id(*FAMILY)
DEFINITIONS = {"schema": "urn:zeus:portfolio-definitions:1", "projects": [
    {"id": "ops", "title": "Operations", "outcome": "bound fleet work completes", "source_ref": "docs/GOAL.md",
     "criteria": [{"id": "c1", "text": "jobs reach a terminal accepted state"}]},
    {"id": "other", "title": "Other", "outcome": "unrelated work", "source_ref": "docs/GOAL.md",
     "criteria": [{"id": "c1", "text": "unrelated criterion"}]}]}
# (job id, status, reason code, bound project): two distinct qualifying jobs and one same-family job
# bound to a project this program is NOT authorized for.
JOBS = (("j-1", "failed", "store_timeout", "ops"), ("j-2", "failed", "store_timeout", "ops"),
        ("j-3", "failed", "store_timeout", "other"), ("j-4", "rejected", "review_rejected", "ops"))


def portfolio(store, jobs=JOBS) -> Portfolio:
    """LABELLED synthetic Fleet rows (only the fields the reconciler reads) under the REAL portfolio
    reconciler, owner bindings and owner dispositions."""
    from test_research_program_fixtures import BASE_CLOCK
    owner = Portfolio(store, DEFINITIONS, clock=lambda: BASE_CLOCK)
    with store.transaction() as tx:
        for job_id, status, reason, _ in jobs:
            tx.put(BUCKET_JOBS, job_id, {"id": job_id, "lane": "lane-1", "status": status, "reason_code": reason,
                                         "error_type": None, "updated_at": BASE_CLOCK})
    for job_id, _, _, project in jobs:
        owner.bind(job_id, project, "c1")
    owner.reconcile()
    return owner

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


audit_service = unavailable("S10", "adapters.audit_service")

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
