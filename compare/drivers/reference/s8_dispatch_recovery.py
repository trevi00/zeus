"""Reference driver: `research.dispatch_recovery` (M7 `ResearchProgram.recover_dispatch` and its family:
`_revoke_dispatch`, `_succeed_dispatch`, `_successor_replay`, `_follow_up` (strict request only), `_recovery_check`,
`_lineage`, `_authorized_successor`, `_revocation_held`, `_refuse_scope_lineage`, the domain transport rules and the
read-only `TransportProbe` of `adapters/research_program.py`).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `adapters.research_program`: `ProgramRunner`, `GitCapture`, `TransportProbe`;
  `adapters.operation_cli.GitSource`; `adapters.artifacts.FileArtifacts`; `adapters.contracts.validate_message`;
  `adapters.autonomous_evidence`: `ExecutionEvidence`, `EvidenceUnavailable`; `adapters.council_snapshot.ReadOnlySnapshot`;
- `application.research_program`: `ResearchProgram` and the bucket names (`BUCKET_PROGRAMS`, `BUCKET_CANDIDATES`,
  `BUCKET_CYCLES`, `BUCKET_DISPATCHES`, `BUCKET_RECOVERIES`, `BUCKET_SUCCESSORS`, `BUCKET_HEADS`); `application.autonomous.BUCKET`
  (`RUNS`); `application.council.CouncilRun` (and the module, the labelled legacy-consumer seam `council_output`);
  `application.workflow.Workflow`; `application.service.Harness`; `application.outbox.relay`;
  `application.execution_fence.advance`; `application.continuation.Continuation`; `application.observations.Observer`;
  `application.portfolio`: `Portfolio`, `family_id`, `BUCKET_INVESTIGATIONS`; `application.fleet.BUCKET_JOBS`;
- `bootstrap.organization`; `ports.MessageDeliveryError`; `domain.model`: `ContractError`, `canonical`, `digest`,
  `envelope`, `utcnow`; `domain.council`: `CouncilFieldRefused`, `council_output`, `validate_any_manifest`;
  `domain.research_program`: `ProgramRefused`, `validate_config`, `config_digest`; `domain.research_investigations`:
  `attempted_transport`, `check_transport_proof`, `FOLLOWUP_SCHEMA`; `domain.continuation.ATTEMPT_SCOPE_PREFIX`;
  `domain.research_attempt_scope.KIND` (`ATTEMPT_SCOPE`);
- `POLICY` = `adapters.providers.packaged_policy()` (the `POLICY` of M7's research-program tests).
Plain M7 objects or lambdas over them only. The clock and the id source are the harness's (`determinism.install`), with a
LABELLED ticking clock: the real `CouncilRun` and `Workflow` order rows by `(created_at, id)`, so a frozen clock would tie
every timestamp (memory `rebuild-recorded-fixture-determinism`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_dispatch_recovery  # noqa: E402

from codex_harness.adapters import research_program as adapter  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.autonomous_evidence import (  # noqa: E402
    EvidenceUnavailable,
    ExecutionEvidence,
)
from codex_harness.adapters.contracts import validate_message  # noqa: E402
from codex_harness.adapters.council_snapshot import ReadOnlySnapshot  # noqa: E402
from codex_harness.adapters.operation_cli import GitSource  # noqa: E402
from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import council as council_module  # noqa: E402
from codex_harness.application import research_program as application  # noqa: E402
from codex_harness.application.autonomous import BUCKET as RUNS  # noqa: E402
from codex_harness.application.continuation import Continuation  # noqa: E402
from codex_harness.application.council import CouncilRun  # noqa: E402
from codex_harness.application.execution_fence import (  # noqa: E402
    advance as execution_fence_advance,
)
from codex_harness.application.fleet import BUCKET_JOBS  # noqa: E402
from codex_harness.application.observations import Observer  # noqa: E402
from codex_harness.application.outbox import relay  # noqa: E402
from codex_harness.application.portfolio import (  # noqa: E402
    BUCKET_INVESTIGATIONS,
    Portfolio,
    family_id,
)
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.autonomous import manifest_digest  # noqa: E402
from codex_harness.domain.continuation import ATTEMPT_SCOPE_PREFIX  # noqa: E402
from codex_harness.domain.council import (  # noqa: E402
    CouncilFieldRefused,
    council_output,
    validate_any_manifest,
)
from codex_harness.domain.discovery_pressure import DiscoveryPaused  # noqa: E402
from codex_harness.domain.model import (  # noqa: E402
    ContractError,
    canonical,
    digest,
    envelope,
    utcnow,
)
from codex_harness.domain.research_attempt_scope import KIND as ATTEMPT_SCOPE  # noqa: E402
from codex_harness.domain.research_investigations import (  # noqa: E402
    FOLLOWUP_SCHEMA,
    attempted_transport,
    check_transport_proof,
)
from codex_harness.domain.research_program import (  # noqa: E402
    ProgramRefused,
    config_digest,
    validate_config,
)
from codex_harness.ports import MessageDeliveryError  # noqa: E402


class TickingClock(determinism.FakeClock):
    """LABELLED. The harness clock advancing 1 ms per read: strictly increasing and deterministic (the real council and
    workflow order rows by `(created_at, id)`)."""

    def now(self, tz=None):
        value = super().now(tz)
        self.advance(0.001)
        return value


CLOCK = TickingClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    MemoryStore=MemoryStore, ResearchProgram=application.ResearchProgram, ProgramRunner=adapter.ProgramRunner,
    GitCapture=adapter.GitCapture, TransportProbe=adapter.TransportProbe, GitSource=GitSource, FileArtifacts=FileArtifacts,
    BUCKET_PROGRAMS=application.BUCKET_PROGRAMS, BUCKET_CANDIDATES=application.BUCKET_CANDIDATES,
    BUCKET_CYCLES=application.BUCKET_CYCLES, BUCKET_DISPATCHES=application.BUCKET_DISPATCHES,
    BUCKET_RECOVERIES=application.BUCKET_RECOVERIES, BUCKET_SUCCESSORS=application.BUCKET_SUCCESSORS,
    BUCKET_HEADS=application.BUCKET_HEADS, RUNS=RUNS, BUCKET_INVESTIGATIONS=BUCKET_INVESTIGATIONS, BUCKET_JOBS=BUCKET_JOBS,
    Portfolio=Portfolio, family_id=family_id, CouncilRun=CouncilRun, Workflow=Workflow, Harness=Harness,
    organization=organization, relay=relay, council_module=council_module, council_output=council_output,
    CouncilFieldRefused=CouncilFieldRefused, validate_any_manifest=validate_any_manifest, manifest_digest=manifest_digest,
    DiscoveryPaused=DiscoveryPaused, validate_message=validate_message, MessageDeliveryError=MessageDeliveryError,
    ExecutionEvidence=ExecutionEvidence, EvidenceUnavailable=EvidenceUnavailable, ReadOnlySnapshot=ReadOnlySnapshot,
    execution_fence_advance=execution_fence_advance, Continuation=Continuation, Observer=Observer,
    ContractError=ContractError, ProgramRefused=ProgramRefused, validate_config=validate_config, config_digest=config_digest,
    attempted_transport=attempted_transport, check_transport_proof=check_transport_proof, FOLLOWUP_SCHEMA=FOLLOWUP_SCHEMA,
    ATTEMPT_SCOPE_PREFIX=ATTEMPT_SCOPE_PREFIX, ATTEMPT_SCOPE=ATTEMPT_SCOPE, canonical=canonical, digest=digest,
    envelope=envelope, utcnow=utcnow, POLICY=packaged_policy(), reset=lambda: (CLOCK.reset(), IDS.reset()))

if __name__ == "__main__":
    driver.finish("reference", "research.dispatch_recovery", s8_dispatch_recovery.run(API))
