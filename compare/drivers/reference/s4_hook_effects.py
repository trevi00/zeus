"""Reference driver: `research.hook_effects` (M7 Harness.record_incident/review inside a caller transaction)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s4_hook_effects  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import digest, envelope  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
ORG = organization()


def reset():
    CLOCK.reset()
    IDS.reset()


API = SimpleNamespace(MemoryStore=MemoryStore, digest=digest, envelope=envelope, reset=reset,
                      hooks=lambda store: Harness(store, ORG))

if __name__ == "__main__":
    driver.finish("reference", "research.hook_effects", s4_hook_effects.run(API))
