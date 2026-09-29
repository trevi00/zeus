"""Target driver: `observation.termination_markers` on the target tree (observation Observer marker operations).
The spool is only asked for its process run id here (the spool itself moves with S9)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s4_markers  # noqa: E402
from codex_harness.observation.application.observations import Observer  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

RUN_ID = "0" * 31 + "1"
API = SimpleNamespace(MemoryStore=MemoryStore, observer=lambda store: Observer(
    store, SimpleNamespace(process_run_id=RUN_ID), component="s4-markers", directory=None, host="fixture-host",
    pid=1, clock=lambda: "2026-01-01T00:00:00+00:00"))

if __name__ == "__main__":
    driver.finish("target", "observation.termination_markers", s4_markers.run(API))
