"""Reference driver: `observation.termination_markers` (M7 Observer marker operations)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s4_markers  # noqa: E402

from codex_harness.adapters.observation_spool import MemorySpool  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.observations import MemoryDirectory, Observer  # noqa: E402

RUN_ID = "0" * 31 + "1"
API = SimpleNamespace(MemoryStore=MemoryStore, observer=lambda store: Observer(
    store, MemorySpool(RUN_ID), component="s4-markers", directory=MemoryDirectory(), host="fixture-host", pid=1,
    clock=lambda: "2026-01-01T00:00:00+00:00"))

if __name__ == "__main__":
    driver.finish("reference", "observation.termination_markers", s4_markers.run(API))
