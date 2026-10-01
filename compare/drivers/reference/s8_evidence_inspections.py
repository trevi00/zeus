"""Reference driver: `evidence.inspections` (M7 `application.evidence_inspection`: `EvidenceInspections`, `forwards_progress`).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `application.evidence_inspection`: `EvidenceInspections`, `forwards_progress`, `BUCKET`, `NOTICES`;
- `domain.model`: `ContractError`, `digest` (the key and the notice id are digests of it).
The inspector is the scenario's LABELLED double (the adapter is a later family and is never imported). Plain M7 objects or
lambdas over them only. The clock is the harness's (`determinism.install`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_evidence_inspections  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import evidence_inspection as application  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    MemoryStore=MemoryStore, EvidenceInspections=application.EvidenceInspections, forwards_progress=application.forwards_progress,
    BUCKET=application.BUCKET, NOTICES=application.NOTICES, ContractError=ContractError, digest=digest)

if __name__ == "__main__":
    driver.finish("reference", "evidence.inspections", s8_evidence_inspections.run(API))
