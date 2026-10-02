"""Target driver: `observation.local_facts` on the target tree (`observation.adapters.monitoring_observations` over the moved file spool)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s9_local_facts  # noqa: E402
from codex_harness.observation.adapters import monitoring_observations as module  # noqa: E402
from codex_harness.observation.adapters import observation_spool as spool_module  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

API = SimpleNamespace(module=module, spool_module=spool_module, SpoolDirectory=spool_module.SpoolDirectory, MemoryStore=MemoryStore)

if __name__ == "__main__":
    driver.finish("target", "observation.local_facts", s9_local_facts.run(API))
