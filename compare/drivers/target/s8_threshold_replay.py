"""Target driver: `research.threshold_replay` on the target tree (S8 pilot 92: `research.application.threshold_replay`).

`validate_source` is the one injected rule (V18 R-t1): context's `validate_source` (the same rule as M7's `domain.skill_import.validate_source`). `MAX_EVENTS` is
context's (the module's V9 local constant equals it, a move test).
The events' clock reaches the kernel through the `Clock` port (`kernel.ids.SYSTEM_CLOCK`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_thresholds_a as common  # noqa: E402
from codex_harness.context.domain.skills.history import MAX_EVENTS  # noqa: E402
from codex_harness.context.domain.skills.import_ import validate_source  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.research.application.threshold_replay import ThresholdReplay  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)

def replay(*args, **kwargs):
    return ThresholdReplay(*args, validate_source=validate_source, **kwargs)


API = SimpleNamespace(MemoryStore=MemoryStore, replay=replay, MAX_EVENTS=MAX_EVENTS, digest=digest)

if __name__ == "__main__":
    driver.finish("target", "research.threshold_replay", common.threshold_replay(API))
