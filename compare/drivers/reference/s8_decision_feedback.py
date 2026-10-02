"""Reference driver: `research.decision_feedback` (M7 `application/decision_feedback.py`: `DecisionFeedback`).

The API holds the plain M7 module, its bucket constants, `domain.decision_feedback` (`df`), `domain.autonomous.evidence_ref_for`, `domain.model`'s
`ContractError` and `digest`, and `adapters.store.MemoryStore`. The collector's clock is the scenario's scripted callable, passed as `clock`;
nothing is patched."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_decision_feedback  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import decision_feedback as module  # noqa: E402
from codex_harness.domain import decision_feedback as df  # noqa: E402
from codex_harness.domain.autonomous import evidence_ref_for  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
determinism.install(CLOCK, determinism.FakeIds())

API = SimpleNamespace(
    MemoryStore=MemoryStore, DecisionFeedback=module.DecisionFeedback, df=df, ContractError=ContractError, digest=digest, evidence_ref_for=evidence_ref_for,
    RUNS=module.RUNS, RESERVATIONS=module.RESERVATIONS, TASKS=module.TASKS, SESSIONS=module.SESSIONS, EVENTS=module.EVENTS,
    OBSERVATIONS=module.OBSERVATIONS, GROUPS=module.GROUPS, CANDIDATES=module.CANDIDATES, CONFLICTS=module.CONFLICTS, COLLECTIONS=module.COLLECTIONS,
    READ_BUCKETS=module.READ_BUCKETS, WRITE_BUCKETS=module.WRITE_BUCKETS, ALL=module.__all__)

if __name__ == "__main__":
    driver.finish("reference", "research.decision_feedback", s8_decision_feedback.run(API))
