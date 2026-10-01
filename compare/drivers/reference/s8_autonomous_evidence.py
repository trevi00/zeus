"""Reference driver: `research.autonomous_evidence` (M7 `adapters/autonomous_evidence.py`: `EvidenceUnavailable`, `ExecutionEvidence`).

The API holds plain M7 objects: `adapters.autonomous_evidence` (`ExecutionEvidence`, `EvidenceUnavailable`) and `domain.model.ContractError`.
The `artifacts` store is the scenario's LABELLED fake (M7's is `FileArtifacts`); the harness clock and ids are installed but unused."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_autonomous_evidence  # noqa: E402

from codex_harness.adapters.autonomous_evidence import (  # noqa: E402
    EvidenceUnavailable,
    ExecutionEvidence,
)
from codex_harness.domain.model import ContractError  # noqa: E402

determinism.install(determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc)), determinism.FakeIds())

API = SimpleNamespace(ExecutionEvidence=ExecutionEvidence, EvidenceUnavailable=EvidenceUnavailable, ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("reference", "research.autonomous_evidence", s8_autonomous_evidence.run(API))
