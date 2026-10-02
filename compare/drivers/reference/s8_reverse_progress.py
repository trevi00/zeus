"""Reference driver: `research.reverse_progress` (M7 `application.reverse_progress`: `ReverseProgress`).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `adapters.artifacts.FileArtifacts` (over a run-scoped directory, as the M7 tests build it);
  `application.reverse_progress`: `ReverseProgress`, `STAGES`, `STATUSES`; `domain.model`: `ContractError`, `digest`.
The clock for the rows' `at` is the harness's (`determinism.install`); `advance` ticks the fake clock."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_reverse_progress  # noqa: E402

from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import reverse_progress as application  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    MemoryStore=MemoryStore, FileArtifacts=FileArtifacts, ReverseProgress=application.ReverseProgress, STAGES=application.STAGES,
    STATUSES=application.STATUSES, ContractError=ContractError, digest=digest, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "research.reverse_progress", s8_reverse_progress.run(API))
