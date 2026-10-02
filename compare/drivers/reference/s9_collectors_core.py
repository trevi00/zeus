"""Reference driver: `observation.collectors_core` (M7 `adapters/monitoring.py` U6: the read-only wrappers, the database facts, the activity projection and `lane_view`).

No clock or id source is installed: every `now` is explicit (the two default-`now` calls are normalized by the shared steps)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_collectors_core  # noqa: E402

import codex_harness.adapters.monitoring as module  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.domain.model import canonical  # noqa: E402
from codex_harness.domain.progress_activity import build_receipt  # noqa: E402

API = SimpleNamespace(module=module, MemoryStore=MemoryStore, FileArtifacts=FileArtifacts, build_receipt=build_receipt, canonical=canonical)

if __name__ == "__main__":
    driver.finish("reference", "observation.collectors_core", s9_collectors_core.run(API))
