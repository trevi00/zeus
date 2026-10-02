"""Target driver: `research.decision_feedback_registry` on the target tree (S8 pilot 91: ``research.adapters.decision_feedback` (V18 R-df1: the `GitBlobSource` Protocol replaces the `GitSource` annotation)`).

The API mirrors the reference driver's names over the target module; the body is M7's, so the scenario's fake source is passed unchanged."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_hostos_adapters as common  # noqa: E402
from codex_harness.research.adapters import decision_feedback as module  # noqa: E402

API = SimpleNamespace(load_registry=module.load_registry, MAX_REGISTRY_BYTES=module.MAX_REGISTRY_BYTES, REGULAR_BLOB=module.REGULAR_BLOB)

if __name__ == "__main__":
    driver.finish("target", "research.decision_feedback_registry", common.decision_feedback(API))
