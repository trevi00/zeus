"""Target driver: `research.audit_repair` on the target tree (S8 pilot 100: `research.application.audit_repair`, V18 R-ar1..R-ar4).

The API mirrors the reference driver's names over the target homes. `AuditRepair` gets its three injected ports: coordination's
`execution_notices` MODULE (R-ar1, structural), `Outbox` (R-ar3) and `EventJournal` (R-ar4). The organization is the packaged one the S5
composition builds. The scenario reads the kernel's default clock where M7 read `utcnow`, and the kernel id source where M7's `envelope`
drew a uuid; the harness's scripted clock and ids (the composition's) reach them through `kernel.ids.SYSTEM_CLOCK` and
`kernel.message.SYSTEM_IDS`. The replay and the artifacts are the scenario's LABELLED doubles (the execution adapter `replay_decode` is a
later family and never runs)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_audit_repair  # noqa: E402
from codex_harness.coordination.application import execution_notices  # noqa: E402
from codex_harness.coordination.application.events import EventJournal  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.analysis import (  # noqa: E402
    ANALYSIS_CHECKPOINTED,
    ANALYSIS_CONTENT_REJECTED,
    ANALYSIS_REJECTED,
)
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.research.application import audit_repair as application  # noqa: E402
from codex_harness.research.domain import audit_repair as domain  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT


def audit_repair(store, org, artifacts, replay=None):
    return application.AuditRepair(store, org, artifacts, replay=replay, outbox=Outbox(), events=EventJournal(), notices=execution_notices)


API = SimpleNamespace(
    MemoryStore=MemoryStore, organization=lambda: composition.ORG, audit_repair=audit_repair, repair_view=application.repair_view,
    BUCKET_ACTIVATION=application.BUCKET_ACTIVATION, BUCKET_CORRECTIONS=application.BUCKET_CORRECTIONS, SENDER=application.SENDER,
    AGENT=application.AGENT, ACTION=application.ACTION, schedule_key=domain.schedule_key, rejection_facts=domain.rejection_facts,
    family_identity=domain.family_identity, correction_identity=domain.correction_identity, notice_proof=domain.notice_proof,
    MISSING_TEST_DISPOSITION=domain.MISSING_TEST_DISPOSITION, ANALYSIS_REJECTED=ANALYSIS_REJECTED,
    ANALYSIS_CHECKPOINTED=ANALYSIS_CHECKPOINTED, ANALYSIS_CONTENT_REJECTED=ANALYSIS_CONTENT_REJECTED, ContractError=ContractError,
    canonical=canonical, digest=digest, envelope=envelope, advance=composition.CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "research.audit_repair", s8_audit_repair.run(API))
