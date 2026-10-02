"""Reference driver: `observation.measurements` (M7 `domain/measurements.py` and `application/measurements.py`)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_measurements  # noqa: E402

from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.measurements import Measurements  # noqa: E402
from codex_harness.domain import measurements as dm  # noqa: E402

API = SimpleNamespace(dm=dm, Measurements=Measurements, MemoryStore=MemoryStore, FileArtifacts=FileArtifacts)

if __name__ == "__main__":
    driver.finish("reference", "observation.measurements", s9_measurements.run(API))
