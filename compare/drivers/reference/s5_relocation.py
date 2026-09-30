"""Reference driver: `coordination.fleet_relocation` (M7 Fleet relocation and host migration over MemoryStore)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s5_relocation  # noqa: E402

from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.fleet import Fleet  # noqa: E402
from codex_harness.domain import fleet as fleet_domain  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
POLICY = packaged_policy()
API = SimpleNamespace(MemoryStore=MemoryStore,
                      Fleet=lambda store, clock, token: Fleet(store, clock=clock, token=token),
                      validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY),
                      validate_config=fleet_domain.validate_config)

if __name__ == "__main__":
    driver.finish("reference", "coordination.fleet_relocation", s5_relocation.run(API))
