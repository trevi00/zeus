"""Reference driver: `observation.file_spool` (M7 `adapters/observation_spool.py`: FileSpool, SpoolDirectory, locks, atomic_write, read_records).

The real child processes import the plain M7 module by its import path in the reference interpreter; no clock or id source is installed (the run ids are
fixed and the two wall-clock fields are checked and symbolized by the scenario)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_file_spool  # noqa: E402

import codex_harness.adapters.observation_spool as module  # noqa: E402

API = SimpleNamespace(module=module, name="codex_harness.adapters.observation_spool")

if __name__ == "__main__":
    driver.finish("reference", "observation.file_spool", s9_file_spool.run(API))
