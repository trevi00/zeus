"""Target driver: `observation.file_spool` on the target tree (`observation.adapters.observation_spool`).

The real child processes import the target module by its import path in the target interpreter; the harness patches nothing of the target (the two
wall-clock fields are checked and symbolized by the scenario, as on the reference side)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import codex_harness.observation.adapters.observation_spool as module  # noqa: E402
import s9_file_spool  # noqa: E402

API = SimpleNamespace(module=module, name="codex_harness.observation.adapters.observation_spool")

if __name__ == "__main__":
    driver.finish("target", "observation.file_spool", s9_file_spool.run(API))
