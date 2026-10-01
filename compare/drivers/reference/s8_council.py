"""Reference driver: `research.council` (M7 `application.council`: `CouncilRun` (`__init__`, `_pipeline`, `_admit`, `_role`,
`_observe`, `_guard`, `_frozen_document`, `_relay`, `_recheck`) and the module names `SNAPSHOT_SOURCE`, `SNAPSHOT_REFUSALS`,
`PROPOSAL_SECTION`, `CONSUMER_OVERFLOW`, `CONSUMER_REFUSAL_OUTCOMES`).

The API holds the plain M7 objects `tests/test_council.py` uses:
- `adapters.store.MemoryStore`, `adapters.providers.packaged_policy`, `adapters.autonomous_evidence.EvidenceUnavailable`,
  `adapters.council_snapshot`: `ReadOnlySnapshot`, `SnapshotUnavailable`; `bootstrap.organization`;
  `application.autonomous`: `AutonomousRun`, `AutonomousRefused`; `application.council`: `CouncilRun` and its module names;
  `application.promotion`: `promote`; `application.service.Harness`; `application.workflow.Workflow`;
- `domain.autonomous`: `validate_autonomous_manifest`; `domain.council`: `validate_council_manifest`, `profile`;
  `domain.model`: `ContractError`, `canonical`, `envelope`; `ports.MessageDeliveryError`.
The executor, the role artifacts, the artifact store, the evidence source and the clock are the scenario's LABELLED doubles; the
snapshot port is M7's own `ReadOnlySnapshot` over a LABELLED fake connection (as M7's tests drive it). Plain M7 objects or lambdas
over them only. The clock and the id source are the harness's (`determinism.install`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_council  # noqa: E402

from codex_harness.adapters.autonomous_evidence import EvidenceUnavailable  # noqa: E402
from codex_harness.adapters.council_snapshot import (  # noqa: E402
    ReadOnlySnapshot,
    SnapshotUnavailable,
)
from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import council as application  # noqa: E402
from codex_harness.application.autonomous import AutonomousRefused, AutonomousRun  # noqa: E402
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.autonomous import (  # noqa: E402
    AutonomousManifestError,
    validate_autonomous_manifest,
)
from codex_harness.domain.council import profile, validate_council_manifest  # noqa: E402
from codex_harness.domain.model import ContractError, canonical, envelope  # noqa: E402
from codex_harness.ports import MessageDeliveryError  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    MemoryStore=MemoryStore, CouncilRun=application.CouncilRun, AutonomousRun=AutonomousRun, AutonomousRefused=AutonomousRefused,
    SNAPSHOT_SOURCE=application.SNAPSHOT_SOURCE, SNAPSHOT_REFUSALS=application.SNAPSHOT_REFUSALS,
    PROPOSAL_SECTION=application.PROPOSAL_SECTION, CONSUMER_OVERFLOW=application.CONSUMER_OVERFLOW,
    CONSUMER_REFUSAL_OUTCOMES=application.CONSUMER_REFUSAL_OUTCOMES, ReadOnlySnapshot=ReadOnlySnapshot,
    SnapshotUnavailable=SnapshotUnavailable, Harness=Harness, Workflow=Workflow, organization=organization,
    packaged_policy=packaged_policy, EvidenceUnavailable=EvidenceUnavailable,
    AutonomousManifestError=AutonomousManifestError, validate_autonomous_manifest=validate_autonomous_manifest,
    validate_council_manifest=validate_council_manifest, profile=profile, ContractError=ContractError, canonical=canonical,
    envelope=envelope, MessageDeliveryError=MessageDeliveryError)

if __name__ == "__main__":
    driver.finish("reference", "research.council", s8_council.run(API))
