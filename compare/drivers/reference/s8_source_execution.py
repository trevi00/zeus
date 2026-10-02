"""Reference driver: `research.source_execution` (M7 `application.source_execution`: `SourceExecutions`).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `application.workflow.Workflow` over `bootstrap.organization` (the real task ownership, as the M7 tests use it);
  `application.source_execution.SourceExecutions`; `domain.research`: `SourceIdentity`, `ExecutionReceipt`; `domain.model`: `ContractError`,
  `digest`, `envelope`; `domain.policy.POLICY`.
The clock and the id source are the harness's (`determinism.install`, with the import-time execution domain pinned); `advance` ticks the fake
clock and `now` reads it (the labelled seam of a backdated `started_at`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_source_execution  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import source_execution as application  # noqa: E402
from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import research as domain  # noqa: E402
from codex_harness.domain.model import ContractError, digest, envelope  # noqa: E402
from codex_harness.domain.policy import POLICY  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000a0d1"}})

API = SimpleNamespace(
    MemoryStore=MemoryStore, Workflow=Workflow, organization=organization, SourceExecutions=application.SourceExecutions,
    SourceIdentity=domain.SourceIdentity, ExecutionReceipt=domain.ExecutionReceipt, ContractError=ContractError, digest=digest, envelope=envelope,
    POLICY=POLICY, now=lambda: CLOCK.now(timezone.utc), advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "research.source_execution", s8_source_execution.run(API))
