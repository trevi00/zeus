"""Reference driver: `research.scheduling` (M7 `application.scheduling`: `schedule_research`, `schedule_audits`).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `bootstrap.organization` (the packaged organization); `application.audit_gate.binding` (SOURCE gate, used to
  bind the planted approvals); `domain.model.digest`; `application.scheduling`: `schedule_research`, `schedule_audits`;
- `ports(store, org)`: the keywords the side's call takes beyond M7's: none (M7 builds `Releases(store, org)` for `reconcile_audits` and writes
  the outbox rows inline itself).
The clock and the id source are the harness's (`determinism.install`); `advance` ticks the fake clock."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_scheduling  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import audit_gate, scheduling  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import digest  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    MemoryStore=MemoryStore, organization=organization, binding=audit_gate.binding, digest=digest,
    schedule_research=scheduling.schedule_research, schedule_audits=scheduling.schedule_audits,
    ports=lambda store, org: {}, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "research.scheduling", s8_scheduling.run(API))
