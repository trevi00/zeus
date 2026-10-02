"""Reference driver: `research.hook_lifecycle` (M7 Harness get_hook/propose/record_canary/activate/rollback/active_hooks/
prepare_command, self-transacting, over MemoryStore)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s8_hook_lifecycle  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import digest  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
ORG = organization()


def reset():
    CLOCK.reset()
    IDS.reset()


API = SimpleNamespace(MemoryStore=MemoryStore, digest=digest, reset=reset, advance=CLOCK.advance,
                      hooks=lambda store: Harness(store, ORG))

if __name__ == "__main__":
    driver.finish("reference", "research.hook_lifecycle", s8_hook_lifecycle.run(API))
