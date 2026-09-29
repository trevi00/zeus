"""Reference driver: `coordination.execution_owners` (M7 execution_fence, execution_budget, execution_notices)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s4_owners  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import (  # noqa: E402
    execution_budget,
    execution_fence,
    execution_notices,
)
from codex_harness.bootstrap import organization  # noqa: E402

# R-D: only the fence's receipt time reads the clock here; the driver pins it (the reference file is untouched).
# The stdlib datetime is NOT replaced: the steps pass aware datetimes, and M7's isinstance checks must see them.
execution_fence.utcnow = lambda: s4_owners.NOW.isoformat()
API = SimpleNamespace(MemoryStore=MemoryStore, fence=execution_fence, budget=execution_budget,
                      notices=execution_notices, org=organization())

if __name__ == "__main__":
    driver.finish("reference", "coordination.execution_owners", s4_owners.run(API))
