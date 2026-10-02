"""Target driver: `research.decision_feedback` on the target tree (S8 batch B4: `research.application.decision_feedback`).

The API mirrors the reference driver's names over the target homes: the module and its bucket constants (RUNS and RESERVATIONS the V9 constants of
R-df1), `research.domain.decision_feedback` (`df`), `research.domain.autonomous.evidence_ref_for`, the kernel's `ContractError` and `digest`, and
the storage `MemoryStore`. The collector's clock is the scenario's scripted callable, passed as `clock`; nothing is patched."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_decision_feedback  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.research.application import decision_feedback as module  # noqa: E402
from codex_harness.research.domain import decision_feedback as df  # noqa: E402
from codex_harness.research.domain.autonomous import evidence_ref_for  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

API = SimpleNamespace(
    MemoryStore=MemoryStore, DecisionFeedback=module.DecisionFeedback, df=df, ContractError=ContractError, digest=digest, evidence_ref_for=evidence_ref_for,
    RUNS=module.RUNS, RESERVATIONS=module.RESERVATIONS, TASKS=module.TASKS, SESSIONS=module.SESSIONS, EVENTS=module.EVENTS,
    OBSERVATIONS=module.OBSERVATIONS, GROUPS=module.GROUPS, CANDIDATES=module.CANDIDATES, CONFLICTS=module.CONFLICTS, COLLECTIONS=module.COLLECTIONS,
    READ_BUCKETS=module.READ_BUCKETS, WRITE_BUCKETS=module.WRITE_BUCKETS, ALL=module.__all__)

if __name__ == "__main__":
    driver.finish("target", "research.decision_feedback", s8_decision_feedback.run(API))
