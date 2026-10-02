"""Reference driver: `research.audit_repair` (M7 `application.audit_repair`: `AuditRepair`, `repair_view`).

The API holds plain M7 objects:
- `adapters.store`: `MemoryStore`; `bootstrap.organization` (the packaged organization);
- `application.audit_repair`: `AuditRepair` (over M7's own `execution_notices.record`, outbox and event puts), `repair_view`,
  `BUCKET_ACTIVATION`, `BUCKET_CORRECTIONS`, `SENDER`, `AGENT`, `ACTION`;
- `domain.audit_repair`: `schedule_key`, `rejection_facts`, `family_identity`, `correction_identity`, `notice_proof`,
  `MISSING_TEST_DISPOSITION`; `domain.observation`: `ANALYSIS_REJECTED`, `ANALYSIS_CHECKPOINTED`, `ANALYSIS_CONTENT_REJECTED`;
  `domain.model`: `ContractError`, `canonical`, `digest`, `envelope`.
The replay and the artifacts are the scenario's LABELLED doubles (the M7 adapter `replay_decode` is a later family and never runs). The
clock and the id source are the harness's (`determinism.install`); `advance` ticks the fake clock."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_audit_repair  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import audit_repair as application  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import audit_repair as domain  # noqa: E402
from codex_harness.domain.model import ContractError, canonical, digest, envelope  # noqa: E402
from codex_harness.domain.observation import (  # noqa: E402
    ANALYSIS_CHECKPOINTED,
    ANALYSIS_CONTENT_REJECTED,
    ANALYSIS_REJECTED,
)

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)


def audit_repair(store, org, artifacts, replay=None):
    return application.AuditRepair(store, org, artifacts, replay=replay)


API = SimpleNamespace(
    MemoryStore=MemoryStore, organization=organization, audit_repair=audit_repair, repair_view=application.repair_view,
    BUCKET_ACTIVATION=application.BUCKET_ACTIVATION, BUCKET_CORRECTIONS=application.BUCKET_CORRECTIONS, SENDER=application.SENDER,
    AGENT=application.AGENT, ACTION=application.ACTION, schedule_key=domain.schedule_key, rejection_facts=domain.rejection_facts,
    family_identity=domain.family_identity, correction_identity=domain.correction_identity, notice_proof=domain.notice_proof,
    MISSING_TEST_DISPOSITION=domain.MISSING_TEST_DISPOSITION, ANALYSIS_REJECTED=ANALYSIS_REJECTED,
    ANALYSIS_CHECKPOINTED=ANALYSIS_CHECKPOINTED, ANALYSIS_CONTENT_REJECTED=ANALYSIS_CONTENT_REJECTED, ContractError=ContractError,
    canonical=canonical, digest=digest, envelope=envelope, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "research.audit_repair", s8_audit_repair.run(API))
