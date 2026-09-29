"""Reference driver: `coordination.decision_guards` (M7 ExecutionRecovery.validate_decision, release_review_policy)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s4_recovery  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.decision_recovery import release_review_policy  # noqa: E402
from codex_harness.application.execution_recovery import ExecutionRecovery  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402

ORG = organization()
API = SimpleNamespace(MemoryStore=MemoryStore, recovery=lambda store: ExecutionRecovery(store, ORG, None),
                      release_review_policy=release_review_policy)

if __name__ == "__main__":
    driver.finish("reference", "coordination.decision_guards", s4_recovery.run(API))
