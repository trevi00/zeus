"""Target driver: `research.autonomous_evidence` on the target tree (S8 pilot 80: `research.adapters.autonomous_evidence`).

The API mirrors the reference driver's names over the target homes: `ExecutionEvidence` and `EvidenceUnavailable` from
`research.adapters.autonomous_evidence` and `ContractError` from the kernel. The `artifacts` store is the scenario's LABELLED fake."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_autonomous_evidence  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.research.adapters.autonomous_evidence import (  # noqa: E402
    EvidenceUnavailable,
    ExecutionEvidence,
)

API = SimpleNamespace(ExecutionEvidence=ExecutionEvidence, EvidenceUnavailable=EvidenceUnavailable, ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("target", "research.autonomous_evidence", s8_autonomous_evidence.run(API))
