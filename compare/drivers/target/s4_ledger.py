"""Target driver: `execution.ledger` on the target tree (execution invocation ledger and call budget).

The clock and the id source are injected through the kernel ports (no stdlib patching).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s4_ledger  # noqa: E402
from codex_harness.execution.adapters.call_budget import CallBudget  # noqa: E402
from codex_harness.execution.application import invocation_ledger  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
CLOCK_PORT, IDS_PORT = PortClock(CLOCK), PortIds(IDS)
API = SimpleNamespace(
    MemoryStore=MemoryStore,
    InvocationLedger=lambda store, capacity: invocation_ledger.InvocationLedger(store, capacity, clock=CLOCK_PORT),
    reservation_key=invocation_ledger.reservation_key,
    CallBudget=lambda root: CallBudget(root, clock=CLOCK_PORT, ids=IDS_PORT))

if __name__ == "__main__":
    driver.finish("target", "execution.ledger", s4_ledger.run(API, CLOCK))
