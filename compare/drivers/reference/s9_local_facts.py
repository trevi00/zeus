"""Reference driver: `observation.local_facts` (M7 `adapters/monitoring_observations.py`: the read-only observation projection and the local spool facts).

No clock or id source is installed: every `now` is explicit (the one default-`now` call is normalized by the shared steps)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_local_facts  # noqa: E402

import codex_harness.adapters.monitoring_observations as module  # noqa: E402
import codex_harness.adapters.observation_spool as spool_module  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402

API = SimpleNamespace(module=module, spool_module=spool_module, SpoolDirectory=spool_module.SpoolDirectory, MemoryStore=MemoryStore)

if __name__ == "__main__":
    driver.finish("reference", "observation.local_facts", s9_local_facts.run(API))
