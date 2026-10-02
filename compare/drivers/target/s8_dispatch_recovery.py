"""Target driver: `research.dispatch_recovery` on the target tree (S8 pilot 83: the pilot 73-80 moves, V12/V13).

The API mirrors the reference driver's names over the target homes, wired as the existing S8 target drivers wire them:
- `ResearchProgram`, `ProgramRunner`, `GitCapture`: as `s8_program_tick` wires them (R-p4/R-p5 ports: `ResearchLaunchFacts`, the
  `execution_fence` and `outbox_relay` modules; the dge `verify_sources`; host_os's `run_process` and `GitSource`);
- `Harness`/`Workflow`: the S5 composition's `Service` and `WorkflowAndMessages`, `CouncilRun` with its four injected ports (R-c1), as
  `s8_council` wires them; `ReadOnlySnapshot`, `ExecutionEvidence` and `EvidenceUnavailable` are the moved research adapters;
- `relay`: `outbox_relay.relay` with the composition's health, clock and id ports; `Continuation` answers `_recovery_held` through
  coordination's `ResearchAcceptance` (the static the scenario calls); `Observer` is observation's.
The clock is the harness's scripted clock made a LABELLED ticking clock (1 ms per read, as the reference driver's `TickingClock`): the
real council and workflow order rows by `(created_at, id)`. It reaches the kernel through the `Clock` port and the scripted ids through
`kernel.message.SYSTEM_IDS`."""

import functools
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_dispatch_recovery  # noqa: E402
from codex_harness.coordination.application import autonomous as base_run  # noqa: E402
from codex_harness.coordination.application import council as council_module  # noqa: E402
from codex_harness.coordination.application import execution_fence, outbox_relay  # noqa: E402
from codex_harness.coordination.application.autonomous import BUCKET as RUNS  # noqa: E402
from codex_harness.coordination.application.continuation.research import (  # noqa: E402
    ResearchAcceptance as Continuation,
)
from codex_harness.coordination.application.fleet.state import BUCKET_JOBS  # noqa: E402
from codex_harness.coordination.application.operation import Operation  # noqa: E402
from codex_harness.coordination.application.research_launch_facts import (  # noqa: E402
    ResearchLaunchFacts,
)
from codex_harness.evidence.application.inspections import EvidenceRecords  # noqa: E402
from codex_harness.host_os.adapters import git_source, process_groups  # noqa: E402
from codex_harness.intake.application.portfolio import Portfolio, family_id  # noqa: E402
from codex_harness.intake.domain.portfolio import BUCKET_INVESTIGATIONS  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import canonical, digest, utcnow  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.knowledge.application import promotion as knowledge_promotion  # noqa: E402
from codex_harness.observation.application.health import HealthRecords  # noqa: E402
from codex_harness.observation.application.observations import Observer  # noqa: E402
from codex_harness.research.adapters import dge_sources  # noqa: E402
from codex_harness.research.adapters import research_program as adapter  # noqa: E402
from codex_harness.research.adapters.autonomous_evidence import (  # noqa: E402
    EvidenceUnavailable,
    ExecutionEvidence,
)
from codex_harness.research.adapters.council_snapshot import ReadOnlySnapshot  # noqa: E402
from codex_harness.research.application import dge  # noqa: E402
from codex_harness.research.application import research_program as application  # noqa: E402
from codex_harness.research.domain.autonomous import manifest_digest  # noqa: E402
from codex_harness.research.domain.council import (  # noqa: E402
    CouncilFieldRefused,
    council_output,
    validate_any_manifest,
)
from codex_harness.research.domain.discovery_pressure import DiscoveryPaused  # noqa: E402
from codex_harness.research.domain.research_attempt_scope import KIND as ATTEMPT_SCOPE  # noqa: E402
from codex_harness.research.domain.research_hold import ATTEMPT_SCOPE_PREFIX  # noqa: E402
from codex_harness.research.domain.research_investigations import (  # noqa: E402
    FOLLOWUP_SCHEMA,
    attempted_transport,
    check_transport_proof,
)
from codex_harness.research.domain.research_program import (  # noqa: E402
    ProgramRefused,
    config_digest,
    validate_config,
)
from codex_harness.routing.adapters.provider_policy import packaged_policy  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.adapters.message_schema import validate_message  # noqa: E402
from codex_harness.storage.ports import MessageDeliveryError  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
_now = composition.CLOCK.now


def _ticking_now(tz=None):
    """LABELLED. The scripted clock advancing 1 ms per read: strictly increasing and deterministic."""
    value = _now(tz)
    composition.CLOCK.advance(0.001)
    return value


composition.CLOCK.now = _ticking_now
ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT
application.uuid4 = composition.IDS.uuid4   # the default cycle owner token: the harness id source, as the reference run installed it
EVIDENCE_RECORDS = EvidenceRecords()
# the module (and its base class) read `time.monotonic()` for recorded durations: substitute the module's `time` name, as `s8_council` does
base_run.time = SimpleNamespace(monotonic=composition.CLOCK.monotonic)


def _ports(service):
    def operation_factory(executor, bus, workflow, budget, collector, observer=None):
        return Operation(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                         executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector, observer=observer,
                         design_gate=SimpleNamespace(check=dge.design_gate), evidence_records=EVIDENCE_RECORDS,
                         clock=composition.PORT, ids=composition.IDPORT)

    return dict(sessions_factory=dge.DebateSessions, evidence_records=EVIDENCE_RECORDS, promotion=knowledge_promotion,
                operation_factory=operation_factory)


class CouncilRun(council_module.CouncilRun):
    def __init__(self, service, *args, **kwargs):
        super().__init__(service, *args, **_ports(service), **kwargs)


class ResearchProgram(application.ResearchProgram):
    """The moved class with its three composition ports wired (a subclass: the scenario builds it from the store alone)."""

    def __init__(self, store, **kwargs):
        super().__init__(store, launch_facts=ResearchLaunchFacts(), fences=execution_fence, outbox_quarantine=outbox_relay,
                         **kwargs)


class GitCapture(adapter.GitCapture):
    def __init__(self, repository, *args, **kwargs):
        super().__init__(repository, *args, run_process=process_groups.run_process, git_source=git_source.GitSource, **kwargs)


class ProgramRunner(adapter.ProgramRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, verify_sources=dge_sources.verify_sources, **kwargs)


API = SimpleNamespace(
    MemoryStore=MemoryStore, ResearchProgram=ResearchProgram, ProgramRunner=ProgramRunner, GitCapture=GitCapture,
    TransportProbe=adapter.TransportProbe, GitSource=git_source.GitSource, FileArtifacts=FileArtifacts,
    BUCKET_PROGRAMS=application.BUCKET_PROGRAMS, BUCKET_CANDIDATES=application.BUCKET_CANDIDATES,
    BUCKET_CYCLES=application.BUCKET_CYCLES, BUCKET_DISPATCHES=application.BUCKET_DISPATCHES,
    BUCKET_RECOVERIES=application.BUCKET_RECOVERIES, BUCKET_SUCCESSORS=application.BUCKET_SUCCESSORS,
    BUCKET_HEADS=application.BUCKET_HEADS, RUNS=RUNS, BUCKET_INVESTIGATIONS=BUCKET_INVESTIGATIONS, BUCKET_JOBS=BUCKET_JOBS,
    Portfolio=Portfolio, family_id=family_id, CouncilRun=CouncilRun, Workflow=lambda store, org: composition.WorkflowAndMessages(store),
    Harness=lambda store, org: composition.Service(store), organization=lambda: composition.ORG,
    relay=functools.partial(outbox_relay.relay, health=HealthRecords().record, clock=composition.PORT, ids=composition.IDPORT), council_module=council_module,
    council_output=council_output, CouncilFieldRefused=CouncilFieldRefused, validate_any_manifest=validate_any_manifest,
    manifest_digest=manifest_digest, DiscoveryPaused=DiscoveryPaused, validate_message=validate_message,
    MessageDeliveryError=MessageDeliveryError, ExecutionEvidence=ExecutionEvidence, EvidenceUnavailable=EvidenceUnavailable,
    ReadOnlySnapshot=ReadOnlySnapshot, execution_fence_advance=execution_fence.advance, Continuation=Continuation,
    Observer=Observer, ContractError=ContractError, ProgramRefused=ProgramRefused, validate_config=validate_config,
    config_digest=config_digest, attempted_transport=attempted_transport, check_transport_proof=check_transport_proof,
    FOLLOWUP_SCHEMA=FOLLOWUP_SCHEMA, ATTEMPT_SCOPE_PREFIX=ATTEMPT_SCOPE_PREFIX, ATTEMPT_SCOPE=ATTEMPT_SCOPE,
    canonical=canonical, digest=digest, envelope=envelope, utcnow=utcnow, POLICY=packaged_policy(),
    reset=lambda: (composition.CLOCK.reset(), composition.IDS.reset()))

if __name__ == "__main__":
    driver.finish("target", "research.dispatch_recovery", s8_dispatch_recovery.run(API))
