"""Reference driver: `observation.reconciliation_guard` (M7 Observer reconciliation guard, MemoryDirectory)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s4_reconciliation_guard  # noqa: E402

from codex_harness.adapters.observation_spool import MemorySpool  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.observations import (  # noqa: E402
    MemoryDirectory,
    Observer,
    ReconciliationRequired,
)

RUN_ID = "0" * 31 + "1"
API = SimpleNamespace(MemoryStore=MemoryStore, MemoryDirectory=MemoryDirectory,
                      ReconciliationRequired=ReconciliationRequired,
                      observer=lambda store, directory: Observer(
                          store, MemorySpool(RUN_ID), component="s4-reconciliation-guard", directory=directory,
                          host="fixture-host", pid=1, clock=lambda: "2026-01-01T00:00:00+00:00"))

if __name__ == "__main__":
    driver.finish("reference", "observation.reconciliation_guard", s4_reconciliation_guard.run(API))
