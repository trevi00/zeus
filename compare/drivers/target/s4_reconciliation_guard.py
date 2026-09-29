"""Target driver: `observation.reconciliation_guard` on the target tree (observation Observer reconciliation guard).
The spool is only asked for its process run id here (the spool itself moves with S9)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s4_reconciliation_guard  # noqa: E402
from codex_harness.observation.application.observations import (  # noqa: E402
    MemoryDirectory,
    Observer,
    ReconciliationRequired,
)
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

RUN_ID = "0" * 31 + "1"
API = SimpleNamespace(MemoryStore=MemoryStore, MemoryDirectory=MemoryDirectory,
                      ReconciliationRequired=ReconciliationRequired,
                      observer=lambda store, directory: Observer(
                          store, SimpleNamespace(process_run_id=RUN_ID), component="s4-reconciliation-guard",
                          directory=directory, host="fixture-host", pid=1,
                          clock=lambda: "2026-01-01T00:00:00+00:00"))

if __name__ == "__main__":
    driver.finish("target", "observation.reconciliation_guard", s4_reconciliation_guard.run(API))
