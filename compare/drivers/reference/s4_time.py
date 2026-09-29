"""Reference driver: `coordination.execution_time` (M7 execution_time and execution_rejections)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s4_time  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import (  # noqa: E402,F401
    execution_rejections,
    execution_time,
    workflow,
)
from codex_harness.bootstrap import organization  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
DT = determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000e4e4"}})
API = SimpleNamespace(MemoryStore=MemoryStore, dt=DT, advance=CLOCK.advance, time=execution_time,
                      reconcile=execution_rejections.reconcile, org=organization())

if __name__ == "__main__":
    driver.finish("reference", "coordination.execution_time", s4_time.run(API))
