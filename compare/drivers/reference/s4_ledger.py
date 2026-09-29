"""Reference driver: the invocation ledger and the call budget (REBUILD-DESIGN-v2 §5.3 S4, RESEARCH-S4 D4/D5).

Scenario family `execution.ledger`. M7 `InvocationLedger` on `MemoryStore` and M7 `CallBudget` on a
disposable directory, with a fake clock and deterministic ids. No provider, no process. Each step
reports the returned row's non-identity fields or the refusal (exception type and message).

Invocation ledger steps: reserve; a second open reservation of the same attempt (refused); settle;
the identical settle again (idempotent); a conflicting settle (refused); a second invocation of the
attempt; a new attempt supersedes an unsettled reservation (`unsettled_unknown`, usage unknown);
capacity refusal; a dead execution's reservation reclaimed; abandon; the summary counts.
Call budget steps: finite ceilings per host and total; subscription mode never refuses on counts;
an unreadable slot counts as taken and refuses subscription accounting; settle; unknown slot.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s4_ledger  # noqa: E402

from codex_harness.adapters.call_budget import CallBudget  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import invocation_ledger  # noqa: E402
from codex_harness.application.invocation_ledger import InvocationLedger  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
API = SimpleNamespace(MemoryStore=MemoryStore, InvocationLedger=InvocationLedger,
                      reservation_key=invocation_ledger.reservation_key, CallBudget=CallBudget)


def main() -> None:
    driver.finish("reference", "execution.ledger", s4_ledger.run(API, CLOCK))


if __name__ == "__main__":
    main()
