"""Target driver: `observation.measurements` on the target tree (`observation.domain.measurements`, `observation.application.measurements`)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s9_measurements  # noqa: E402
from codex_harness.observation.application.measurements import Measurements  # noqa: E402
from codex_harness.observation.domain import measurements as dm  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

API = SimpleNamespace(dm=dm, Measurements=Measurements, MemoryStore=MemoryStore, FileArtifacts=FileArtifacts)

if __name__ == "__main__":
    driver.finish("target", "observation.measurements", s9_measurements.run(API))
