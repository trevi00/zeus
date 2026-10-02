"""Target driver: `review.releases_audits` on the target tree (S8 pilot 106: review `Releases.reconcile_audits` and `request_reverification`,
DESIGN-s8 §19.1 R-ra1..R-ra4).

The API mirrors the reference driver's names over the target homes. `Releases` is built as the S7 composition builds it (S4's driver and
`s7_delivery_composition.releases_for`): intake's `ticket_binding`, the scripted clock port (the harness's fake clock, started at the instant the
reference run's clock starts and ticked by `advance`) and coordination's `EventJournal` as `events` (R-ra3)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_releases_audits  # noqa: E402
from codex_harness.coordination.application.events import EventJournal  # noqa: E402
from codex_harness.intake.application import tickets  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.review.application.releases import Releases  # noqa: E402
from codex_harness.review.domain.releases import (  # noqa: E402
    environment_successor_id,
    evaluator_successor_id,
    reverification_successor_id,
)
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
PORT = PortClock(CLOCK)
ORG = packaged_organization()
API = SimpleNamespace(MemoryStore=MemoryStore,
                      releases=lambda store: Releases(store, ORG, ticket_binding=tickets.ticket_binding, clock=PORT, events=EventJournal()),
                      digest=digest, reverification_successor_id=reverification_successor_id,
                      evaluator_successor_id=evaluator_successor_id, environment_successor_id=environment_successor_id,
                      advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "review.releases_audits", s8_releases_audits.run(API))
