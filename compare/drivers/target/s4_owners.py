"""Target driver: `coordination.execution_owners` on the target tree (the moved-ahead coordination owners).

The fence receipt time comes from an injected clock pinned to the scenario's instant (the reference driver
pins M7's `utcnow` to the same instant).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import functools  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import s4_owners  # noqa: E402
from codex_harness.coordination.application import (  # noqa: E402
    execution_budget,
    execution_fence,
    execution_notices,
)
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

PINNED = SimpleNamespace(now=lambda: s4_owners.NOW)
FENCE = SimpleNamespace(BUCKET=execution_fence.BUCKET, key=execution_fence.key, current=execution_fence.current,
                        require_unused=execution_fence.require_unused,
                        require_current=execution_fence.require_current,
                        advance=functools.partial(execution_fence.advance, clock=PINNED))
API = SimpleNamespace(MemoryStore=MemoryStore, fence=FENCE, budget=execution_budget, notices=execution_notices,
                      org=packaged_organization())

if __name__ == "__main__":
    driver.finish("target", "coordination.execution_owners", s4_owners.run(API))
