"""Reference driver: `research.autonomous` (M7 `application.autonomous`: `AutonomousRun`, `AutonomousRefused`, `provider_labels`,
`bus_view`, `_safe_binding`, `row_digest`).

The API holds the plain M7 objects `tests/test_autonomous.py` uses:
- `adapters.store.MemoryStore`, `adapters.providers.packaged_policy`, `adapters.autonomous_evidence.EvidenceUnavailable`,
  `bootstrap.organization`; `application.autonomous`: `AutonomousRun`, `AutonomousRefused`, `BUCKET`, `OUTCOME_BY_REASON`,
  `provider_labels`, `bus_view`, `_safe_binding`, `row_digest`; `application.dge`: `DebateSessions`, `DgeRefused`;
  `application.promotion`: `promote`, `PromotionRefused`; `application.service.Harness`; `application.workflow.Workflow`;
- `domain.autonomous` (the names the tests and the module read): `AutonomousManifestError`, `validate_autonomous_manifest`,
  `verified_graph`, `role_message_id`; `domain.model`: `ContractError`, `canonical`, `envelope`; `ports.MessageDeliveryError`.
The executor, the role artifacts, the evidence source and the clock are the scenario's LABELLED doubles (the real adapters are
later families and are never run). Plain M7 objects or lambdas over them only. The clock and the id source are the harness's
(`determinism.install`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_autonomous  # noqa: E402

from codex_harness.adapters.autonomous_evidence import EvidenceUnavailable  # noqa: E402
from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import autonomous as application  # noqa: E402
from codex_harness.application.dge import DebateSessions, DgeRefused  # noqa: E402
from codex_harness.application.promotion import PromotionRefused, promote  # noqa: E402
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import autonomous as domain  # noqa: E402
from codex_harness.domain.model import ContractError, canonical, envelope  # noqa: E402
from codex_harness.ports import MessageDeliveryError  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    MemoryStore=MemoryStore, AutonomousRun=application.AutonomousRun, AutonomousRefused=application.AutonomousRefused,
    BUCKET=application.BUCKET, OUTCOME_BY_REASON=application.OUTCOME_BY_REASON, provider_labels=application.provider_labels,
    bus_view=application.bus_view, safe_binding=application._safe_binding, row_digest=application.row_digest,
    DebateSessions=DebateSessions, DgeRefused=DgeRefused, promote=promote, PromotionRefused=PromotionRefused, Harness=Harness,
    Workflow=Workflow, organization=organization, packaged_policy=packaged_policy, EvidenceUnavailable=EvidenceUnavailable,
    AutonomousManifestError=domain.AutonomousManifestError, validate_autonomous_manifest=domain.validate_autonomous_manifest,
    verified_graph=domain.verified_graph, role_message_id=domain.role_message_id, ContractError=ContractError,
    canonical=canonical, envelope=envelope, MessageDeliveryError=MessageDeliveryError)

if __name__ == "__main__":
    driver.finish("reference", "research.autonomous", s8_autonomous.run(API))
