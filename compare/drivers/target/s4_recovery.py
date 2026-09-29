"""Target driver: `coordination.decision_guards` on the target tree (validate_decision, release_review_policy).
The related-evidence projection is not injected: these steps never reach it (it would refuse loudly)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s4_recovery  # noqa: E402
from codex_harness.coordination.application.decision_recovery import (  # noqa: E402
    release_review_policy,
)
from codex_harness.coordination.application.execution_recovery import (  # noqa: E402
    ExecutionRecovery,
)
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

ORG = packaged_organization()
API = SimpleNamespace(MemoryStore=MemoryStore, recovery=lambda store: ExecutionRecovery(store, ORG, None),
                      release_review_policy=release_review_policy)

if __name__ == "__main__":
    driver.finish("target", "coordination.decision_guards", s4_recovery.run(API))
