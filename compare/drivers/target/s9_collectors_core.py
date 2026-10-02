"""Target driver: `observation.collectors_core` on the target tree (`observation.adapters.collectors`, the moved U6 core collectors)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s9_collectors_core  # noqa: E402
from codex_harness.execution.domain.progress_activity import build_receipt  # noqa: E402
from codex_harness.kernel.ids import canonical  # noqa: E402
from codex_harness.observation.adapters import collectors as module  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

API = SimpleNamespace(module=module, MemoryStore=MemoryStore, FileArtifacts=FileArtifacts, build_receipt=build_receipt, canonical=canonical)

if __name__ == "__main__":
    driver.finish("target", "observation.collectors_core", s9_collectors_core.run(API))
