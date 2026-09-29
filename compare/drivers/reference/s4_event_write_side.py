"""Reference driver: `observation.event_write_side` (M7 Observer emit/audit/alert/sink/health, record_termination,
reconciliation reads, build_event)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s4_event_write_side  # noqa: E402

from codex_harness.adapters.observation_spool import MemorySpool  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.observations import (  # noqa: E402
    MemoryDirectory,
    Observer,
    PostExecutionRecordFailure,
)
from codex_harness.ports import SpoolFull  # noqa: E402

RUN_ID = "0" * 31 + "1"
API = SimpleNamespace(MemoryStore=MemoryStore, MemoryDirectory=MemoryDirectory, MemorySpool=MemorySpool,
                      SpoolFull=SpoolFull, PostExecutionRecordFailure=PostExecutionRecordFailure,
                      observer=lambda store, spool, directory, monotonic: Observer(
                          store, spool, component="s4-event-write-side", role="s4-event-write-side",
                          directory=directory,
                          host="fixture-host", pid=1, clock=lambda: "2026-01-01T00:00:00+00:00",
                          monotonic=monotonic))

if __name__ == "__main__":
    driver.finish("reference", "observation.event_write_side", s4_event_write_side.run(API))
