"""M7 observation surface (Observer, Collector, spool, schema, measurements, the monitor's collect) over the S9 target, for the
ported M7 observation suites (`test_observations`, `test_observation_*`, `test_measurements`, `test_dispatch_fairness`).

Layer: harness (never shipped). A TEST shim: it lets those M7 suites run, with their assertions unchanged, against the
moved observation objects as `compare/drivers/target/s9_collector.py`, `s9_file_spool.py`, `s9_schema.py`,
`s9_measurements.py`, `s9_collectors_core.py` and `s9_collectors_sources.py` build them. Ids and clocks are NOT scripted
here: as in M7 the real clock and uuid4 are used (the modules' own, the kernel's SYSTEM_CLOCK / SYSTEM_IDS).

Named adaptations (each is a construction/import/patch-target adaptation, never a behaviour change):
- Most names are plain moves and are re-exported from their target homes (the ledger's `target_symbol`): `Observer`,
  `Collector`, `MemoryDirectory`, `orphan_report`, `status_report` (`observation.application.observations`); `FileSpool`,
  `MemorySpool`, `SpoolDirectory`, `writer_alive`, `run_lock_path`, `lifecycle_lock`, `atomic_write`, `encode_record`,
  `segment_identity` (`observation.adapters.observation_spool`; `observation_spool` is that module, the suites'
  `spool_module`: an assignment such as `LIFECYCLE_TIMEOUT` lands on it); `validate_observation`
  (`observation.adapters.observation_schema`); `validate_message` (`storage.adapters.message_schema`); the observation
  domain (`REGISTRY`, `build_event`, `check_attributes`, `content_hash`, `execution_identity`, `redact_value`,
  `new_process_run_id`, `SUBTYPE_REASONS`, `TERMINAL_SUBTYPES`: `observation.domain.observation`; `safe_code`:
  `kernel.analysis`; `invocation_outcome`: `execution.domain.invocation_outcomes`); `Measurements`, `DEFINITIONS`,
  `evaluate`; `observation_facts`; `SpoolFull` (`observation.ports`); the stores, `FileArtifacts`, `ContractError`,
  `envelope`, `digest`, `parse_request`, `InvocationLedger`, `GitWorkspace`, `completed_output`, `EvidenceInspector`,
  `EvidenceInspections` and the evidence `STATES` from their S1-S8 homes; `EvidenceInspector(artifacts, policy=None,
  interpreter=None)` is the moved class with `process_tree=ProcessTree` injected, as composition passes it (E-4c).
- `Harness`, `organization`, `ExecutionRecovery` are `m7_coordination`'s, `Workflow` is `m7_coordination.Workflow` with the
  S4 Workflow's static `_attempt_outcome` (M7 `Workflow._attempt_outcome`, read on the class) added, and `Executor` is
  `m7_intake.Executor` (`m7_executor.Executor` with M7's evidence gate wired, the legacy inspector) whose `workflow` forwards an
  assignment to the Workflow the executor's ports hold (M7 had the one object: `monkeypatch.setattr(executor.workflow, "complete", ...)`). M7's `executor.evidence`
  is that gate's `EvidenceInspections`; a case replaces it, as in M7. M7's two observation events around the inspection
  (`development.evidence_inspection_started`/`_finished`, the executor composition's `_inspect_evidence`) are not
  emitted by any S1-S9 target object (the Executor is composed in S10), so the cases that assert them are skipped whole.
- `AppServer` is a module-level name read at open time (`m7_executor.AppServer`): the patch target of M7's
  `codex_harness.adapters.executor.AppServer`. The patch target of `codex_harness.adapters.executor.persist_result` is the
  `results.persist` seam of the executor's `run_task` (`execution_output.persist_result` as the shim binds it), and the one
  of the Harness' `checkpoint` is the `sessions.checkpoint` of the same `run_task` (`SessionCheckpoints`, RunTask's port).
- `monitoring` stands for M7 `adapters.monitoring` as the one test that reads the monitor's `collect` sees it
  (`test_measurements`): a facade over `observation.adapters.collectors`. `collect` supplies `CollectorPorts` as S10 composes
  them (`run_process` is the facade's own, replaceable name; `bus_factory` is `RedisBus`; the owner projections are M7's own
  calls on the moved owners: `Fleet(store).status()`, `ResearchProgram(store).monitor()`, `portfolio(store).status()`,
  `FleetBacklog(store).status()`, `HostDelivery(store).status()`, `WorkerSessions(store, None).status()`,
  `Continuation(store).status()` and `discovery_pressure.status(store)`; S9P1 labelled the research-program, portfolio,
  backlog, worker-session and discovery-pressure ones as refusals because its suites read only `database`, S9P2's read
  them all).
  M7 called `docker_facts(repository, containers)` and `redis_facts(url, agents)` as module names; the moved functions
  receive their process and bus as keyword seams, so an assignment of either name on the facade is run, for the span of one
  `collect` call, through a wrapper that drops that keyword and calls the replacement as M7 did (the module is restored).
- S9P2 (the monitoring suites): `monitoring` also carries M7's `lane_resolver(host_dsn, store_factory=None)` (the moved one
  with `dsn_for=lane_dsn`) and `lane_session_facts(store, resolve, artifacts=None, now=None)` (with `registered=` the Fleet's
  `registered`); names such as `ReadOnlyStore`, `LaneSnapshotStore`, `ContractError`, `datetime` are read from the moved
  collectors module. The module-level `docker_facts` is the moved function run through the facade's replaceable `run_process`
  (M7 read `monitoring.run_process` at call time); `monitoring_web` is the viewer module (`observation.adapters.viewer_http`,
  desk-free: no desk is injected by these suites); `monitoring_readiness`, `monitoring_observations` names are re-exported from
  their homes; `Fleet`, `FleetBacklog` (the moved class over the shim Fleet's registry, M7's `FleetBacklog(store, fleet, ...)`),
  `Portfolio`, `packaged_definitions`, `packaged_policy`, `validate_manifest` (operation manifest, `intake.domain`),
  `repository_identity`, `new_intent`/`BUCKET_INTENTS` (the backlog's) are the owners' own; `module`, `observe`, `main`,
  `CHECK_IDS` of the frontend checks bind the composition's capture, `partial(_capture, process_tree=ProcessTree)`, as
  `compare/drivers/target/s9_frontend_checks.py` does.
- `utcnow` is M7's zero-argument `adapters.executor.utcnow`, the patch target of a frozen executor clock: the Executor's RunTask
  takes a clock port (`utcnow(self.clock)`) that reads it.
- `ArtifactMaintenance(store, artifacts)` is the moved class with the stateless `EventJournal()` it takes (`storage.adapters.maintenance`);
  `postgres_store` is the moved store module (M7 `adapters.store`, whose `psycopg` the connect-budget case replaces).
- `redis_url` (M7 `bootstrap`) is S10's `composition.redis_url`: only the test skipped whole for it names it.
- `unavailable(slice_, name)` is `m7_coordination.unavailable`.
"""

from __future__ import annotations

import functools
import time  # noqa: F401
from datetime import datetime

from m7_coordination import Continuation as _Continuation
from m7_coordination import (  # noqa: F401
    ExecutionRecovery,
    Harness,
    LaunchRefused,  # noqa: F401
    organization,
    packaged_policy,  # noqa: F401
    unavailable,
)
from m7_coordination import Fleet as _Fleet
from m7_coordination import Workflow as _Workflow
from m7_delivery import HostDelivery as _HostDelivery
from m7_executor import AppServer  # noqa: F401
from m7_intake import (  # noqa: F401  # noqa: F401
    ContractError,
    FileArtifacts,
    GitWorkspace,
    MemoryStore,
    _Facade,
    _Messaging,
    completed_output,
    digest,
    validate_message,
)
from m7_intake import Executor as _IntakeExecutor

from codex_harness.context.adapters.project_skills import initialize  # noqa: F401
from codex_harness.coordination.adapters.fleet_runtime import lane_dsn
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.fleet_backlog import FleetBacklog as _FleetBacklog
from codex_harness.coordination.application.workflow import Workflow as _TargetWorkflow
from codex_harness.coordination.domain.fleet import repository_identity  # noqa: F401
from codex_harness.evidence.adapters.evidence_inspection import EvidenceInspector as _EvidenceInspector
from codex_harness.evidence.adapters.evidence_inspection import _capture
from codex_harness.evidence.application.evidence_inspection import EvidenceInspections  # noqa: F401
from codex_harness.evidence.domain.evidence import STATES  # noqa: F401
from codex_harness.execution.adapters.providers.claude_cli import _normalize  # noqa: F401
from codex_harness.execution.application.invocation_ledger import InvocationLedger  # noqa: F401
from codex_harness.execution.application.worker_sessions import WorkerSessions as _WorkerSessions
from codex_harness.execution.domain.invocation import parse_request  # noqa: F401
from codex_harness.execution.domain.invocation_outcomes import invocation_outcome  # noqa: F401
from codex_harness.execution.domain.output_contracts import IMPLEMENTATION  # noqa: F401
from codex_harness.execution.domain.progress_activity import (  # noqa: F401
    ACTIVITY_SCHEMA,
    ActivityInvalid,
    build_receipt,
    claude_result_status,
    fixed_completed_status,
    fixed_completed_type,
    fixed_last_event,
    validate_receipt,
)
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters.process_tree import ProcessTree
from codex_harness.intake.adapters.portfolio import packaged_definitions  # noqa: F401
from codex_harness.intake.adapters.portfolio import portfolio as _portfolio
from codex_harness.intake.application.portfolio import Portfolio  # noqa: F401
from codex_harness.intake.domain.backlog import BUCKET_INTENTS, new_intent  # noqa: F401
from codex_harness.intake.domain.operation_manifest import validate_manifest  # noqa: F401
from codex_harness.kernel.analysis import safe_code  # noqa: F401
from codex_harness.kernel.ids import canonical  # noqa: F401
from codex_harness.kernel.ids import utcnow as _utcnow
from codex_harness.kernel.message import envelope  # noqa: F401
from codex_harness.observation.adapters import collectors as _collectors
from codex_harness.observation.adapters import monitor_frontend_checks as module  # noqa: F401
from codex_harness.observation.adapters import (
    monitoring_readiness,  # noqa: F401
    observation_spool,  # noqa: F401
)
from codex_harness.observation.adapters import viewer_http as monitoring_web  # noqa: F401
from codex_harness.observation.adapters.collectors import (  # noqa: F401
    ACTIVITY_BODY_BYTES,
    ArtifactReader,
    audit_progress,
    container_scope,
    execution_activity,
    persisted_measurements,
    project_receipt,
    safe_text,
)
from codex_harness.observation.adapters.monitor_frontend_checks import CHECK_IDS  # noqa: F401
from codex_harness.observation.adapters.monitoring_observations import (  # noqa: F401
    BUCKET_LIMIT,
    ROW_LIMIT,
    local_facts,
    observation_facts,
    scan_bounded,
)
from codex_harness.observation.adapters.monitoring_readiness import (  # noqa: F401
    FRESH_SECONDS,
    FUTURE_TOLERANCE_SECONDS,
    MAX_SNAPSHOT_BYTES,
    SCHEMA,
    SNAPSHOT_REASONS,
    SOURCE_REASONS,
    readiness,
)
from codex_harness.observation.adapters.observation_schema import validate_observation  # noqa: F401
from codex_harness.observation.adapters.observation_spool import (  # noqa: F401
    FileSpool,
    MemorySpool,
    SpoolDirectory,
    atomic_write,
    encode_record,
    lifecycle_lock,
    run_lock_path,
    segment_identity,
    writer_alive,
)
from codex_harness.observation.adapters.viewer_http import handler  # noqa: F401
from codex_harness.observation.application.measurements import Measurements  # noqa: F401
from codex_harness.observation.application.monitoring import Monitoring, initiatives  # noqa: F401
from codex_harness.observation.application.observations import (  # noqa: F401
    Collector,
    MemoryDirectory,
    Observer,
    orphan_report,
    status_report,
)
from codex_harness.observation.domain.measurements import DEFINITIONS, evaluate  # noqa: F401
from codex_harness.observation.domain.observation import (  # noqa: F401
    REGISTRY,
    SUBTYPE_REASONS,
    TERMINAL_SUBTYPES,
    build_event,
    check_attributes,
    content_hash,
    execution_identity,
    new_process_run_id,
    redact_value,
)
from codex_harness.observation.ports import CollectorPorts, SpoolFull  # noqa: F401
from codex_harness.research.application import discovery_pressure as _discovery_pressure
from codex_harness.research.application.research_program import ResearchProgram as _ResearchProgram
from codex_harness.storage.adapters import postgres_store  # noqa: F401
from codex_harness.storage.adapters.maintenance import ArtifactMaintenance as _ArtifactMaintenance
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: F401
from codex_harness.storage.adapters.redis_bus import RedisBus  # noqa: F401

Fleet = _Fleet


class Workflow(_Workflow):
    """`m7_coordination.Workflow` with the S4 Workflow's static `_attempt_outcome` on the class, as M7's was."""

    _attempt_outcome = staticmethod(_TargetWorkflow._attempt_outcome)


class _OneWorkflow(_Messaging):
    """M7's `executor.workflow` was the one Workflow object every collaborator held: an assignment on it (a case
    replacing `complete`) lands on the Workflow the executor's ports hold."""

    def __setattr__(self, name, value):
        if name in ("workflow", "messages"):
            object.__setattr__(self, name, value)
        else:
            setattr(self.workflow, name, value)


def utcnow():
    """M7's zero-argument process clock (`adapters.executor.utcnow`); the Executor's RunTask reads it through `_ExecutorClock`."""
    return _utcnow()


class _ExecutorClock:
    """RunTask's clock port, reading this module's replaceable `utcnow` (the patch target of M7's `executor.utcnow`)."""

    def now(self):
        return datetime.fromisoformat(utcnow())


class Executor(_IntakeExecutor):
    """`m7_intake.Executor` whose `workflow` forwards assignments to the Workflow its ports hold, and whose RunTask reads
    its timestamps from `utcnow` above."""

    def __init__(self, service, git, artifacts, *args, **kwargs):
        super().__init__(service, git, artifacts, *args, **kwargs)
        self.workflow = _OneWorkflow(self.workflow.workflow)
        self.run_task.clock = _ExecutorClock()


def EvidenceInspector(artifacts, policy=None, interpreter=None):  # noqa: N802 - the M7 constructor name
    """The moved inspector with the process-tree port composition passes (S8 E-4c), as `m7_intake.Executor` wires it."""
    return _EvidenceInspector(artifacts, policy, interpreter, process_tree=ProcessTree)


def redis_url():
    return unavailable("S10", "composition.redis_url")()


CAPTURE = functools.partial(_capture, process_tree=ProcessTree)


def observe(cwd, node=None, dependencies=None, capture=None):
    """M7 `observe`: its module-level capture default is the composition's `partial(_capture, process_tree=ProcessTree)`."""
    return module.observe(cwd, node=node, dependencies=dependencies, capture=CAPTURE if capture is None else capture)


def main(argv=None):
    return module.main(argv, capture=CAPTURE)


def FleetBacklog(store, fleet=None, *args, **kwargs):  # noqa: N802 - the M7 constructor name
    """The moved class takes the Fleet's registry (M7's `Fleet` held it and `enqueue`)."""
    return _FleetBacklog(store, getattr(fleet, "registry", fleet), *args, **kwargs)


def ArtifactMaintenance(store, artifacts):  # noqa: N802 - the M7 constructor name
    """The moved class takes the event journal it appends to (a stateless owner, `EventJournal()`)."""
    return _ArtifactMaintenance(store, artifacts, EventJournal())


def docker_facts(repository, containers=None):
    """M7 `docker_facts`: the moved function run through the facade's `run_process`, read at call time."""
    return _collectors.docker_facts(repository, containers, run_process=lambda *a, **k: monitoring.run_process(*a, **k))


def _wrap_docker(replacement):
    return lambda repository, containers=None, *, run_process=None: replacement(repository, containers)


def _wrap_redis(replacement):
    return lambda url, agents, *, bus_factory=None: replacement(url, agents)


class _Monitoring(_Facade):
    """Names read from the moved module; `run_process`, `docker_facts` and `redis_facts` are the facade's own, replaceable
    names: `collect` binds the ports and, for the span of one call, runs a replaced `docker_facts`/`redis_facts` through a
    wrapper that drops the seam keyword (M7 called them with their positional arguments only), then restores the module."""

    def __init__(self):
        super().__init__(_collectors, run_process=process_groups.run_process, docker_facts=_collectors.docker_facts,
                         redis_facts=_collectors.redis_facts)

    def lane_resolver(self, host_dsn, store_factory=None):
        return _collectors.lane_resolver(host_dsn, store_factory, dsn_for=lane_dsn)

    def lane_session_facts(self, store, resolve, artifacts=None, now=None):
        return _collectors.lane_session_facts(store, resolve, artifacts, now, registered=lambda s: _Fleet(s).registered())

    def collect(self, *args, **kwargs):
        ports = CollectorPorts(
            run_process=lambda *a, **k: self.run_process(*a, **k), bus_factory=RedisBus,
            fleet=lambda store: _Fleet(store).status(), research_program=lambda store: _ResearchProgram(store).monitor(),
            portfolio=lambda store: _portfolio(store).status(),
            fleet_backlog=lambda store: _FleetBacklog(store).status(),
            host_delivery=lambda store: _HostDelivery(store).status(),
            worker_session=lambda store: _WorkerSessions(store, None).status(),
            continuation=lambda store: _Continuation(store).status(),
            discovery_pressure=_discovery_pressure.status, registered=lambda store: _Fleet(store).registered())
        originals = {name: getattr(_collectors, name) for name in ("docker_facts", "redis_facts")}
        _collectors.docker_facts = _wrap_docker(self.docker_facts) if self.docker_facts is not originals["docker_facts"] else self.docker_facts
        _collectors.redis_facts = _wrap_redis(self.redis_facts) if self.redis_facts is not originals["redis_facts"] else self.redis_facts
        try:
            return _collectors.collect(*args, ports=ports, **kwargs)
        finally:
            _collectors.docker_facts, _collectors.redis_facts = originals["docker_facts"], originals["redis_facts"]


monitoring = _Monitoring()
read_only = _collectors.read_only
