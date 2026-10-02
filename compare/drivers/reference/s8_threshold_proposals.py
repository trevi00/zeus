"""Reference driver: `research.threshold_proposals` (M7 `application/threshold_proposals.py`: `ThresholdProposals.collect`).

The API holds the plain M7 objects (`adapters.store.MemoryStore`, `ThresholdProposals` over M7's own `validate_source`, `MAX_EVENTS`, `digest`). The clock for the records' `created_at` is the harness's (`determinism.install`).
Artifacts, the policy provider and the native evaluator are the scenario's LABELLED fakes."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_thresholds_a as common  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.threshold_proposals import ThresholdProposals  # noqa: E402
from codex_harness.domain.model import digest  # noqa: E402
from codex_harness.domain.skill_history import MAX_EVENTS  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(MemoryStore=MemoryStore, proposals=ThresholdProposals, MAX_EVENTS=MAX_EVENTS, digest=digest)

if __name__ == "__main__":
    driver.finish("reference", "research.threshold_proposals", common.threshold_proposals(API))
