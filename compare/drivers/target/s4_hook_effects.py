"""Target driver: `research.hook_effects` on the target tree (research HookLifecycle).

Outbox and EventJournal are coordination's owner operations, wired here as composition will; clocks and ids are
the scripted ones.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s4_hook_effects  # noqa: E402
from codex_harness.coordination.application.events import EventJournal  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.research.application.hooks import HookLifecycle  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT = PortClock(CLOCK)
ORG = packaged_organization()


def reset():
    CLOCK.reset()
    IDS.reset()


API = SimpleNamespace(MemoryStore=MemoryStore, digest=digest, reset=reset,
                      envelope=lambda *a, **k: envelope(*a, **k, clock=PORT, ids=PortIds(IDS)),
                      hooks=lambda store: HookLifecycle(ORG, outbox=Outbox(), events=EventJournal(),
                                                        clock=PORT, ids=PortIds(IDS)))

if __name__ == "__main__":
    driver.finish("target", "research.hook_effects", s4_hook_effects.run(API))
