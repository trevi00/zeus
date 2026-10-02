"""Reference driver: `research.decision_feedback_registry` (M7 `adapters/decision_feedback.py: `load_registry``).

The API holds the plain M7 objects: `adapters.decision_feedback` (`load_registry`, `MAX_REGISTRY_BYTES`, `REGULAR_BLOB`). The `source` the scenario passes is its
LABELLED fake `GitSource`.

The clock and ids are not used (no result holds a time or an id)."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_hostos_adapters as common  # noqa: E402

from codex_harness.adapters import decision_feedback as module  # noqa: E402

API = SimpleNamespace(load_registry=module.load_registry, MAX_REGISTRY_BYTES=module.MAX_REGISTRY_BYTES, REGULAR_BLOB=module.REGULAR_BLOB)

if __name__ == "__main__":
    driver.finish("reference", "research.decision_feedback_registry", common.decision_feedback(API))
