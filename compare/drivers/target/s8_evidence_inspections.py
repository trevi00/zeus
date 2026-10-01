"""Target driver: `evidence.inspections` on the target tree (S8 pilot 66: `evidence.application.evidence_inspection`).

The API mirrors the reference driver's names over the target homes: the use case from
`evidence.application.evidence_inspection` (`require_all_checked` delegates to the S5 `EvidenceRecords`), the memory store
from storage, and `ContractError`/`digest` from the kernel. The scenario reads the kernel's default clock where M7 read
`utcnow`; the harness's scripted clock reaches it through the kernel `Clock` port: the driver sets `kernel.ids.SYSTEM_CLOCK`,
the one default `utcnow` reads (the target's standard library is never patched). The inspector is the scenario's LABELLED
double; the adapter is a later family."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_evidence_inspections  # noqa: E402
from codex_harness.evidence.application import evidence_inspection as application  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)

API = SimpleNamespace(
    MemoryStore=MemoryStore, EvidenceInspections=application.EvidenceInspections, forwards_progress=application.forwards_progress,
    BUCKET=application.BUCKET, NOTICES=application.NOTICES, ContractError=ContractError, digest=digest)

if __name__ == "__main__":
    driver.finish("target", "evidence.inspections", s8_evidence_inspections.run(API))
