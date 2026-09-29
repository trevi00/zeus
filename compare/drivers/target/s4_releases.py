"""Target driver: `review.releases_units` on the target tree (review Releases.propose/review, intake ticket_binding).

The release receipt time comes from an injected clock pinned to the reference's pinned instant; intake's
ticket_binding is injected into Releases as composition will.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s4_releases  # noqa: E402
from codex_harness.intake.application import tickets  # noqa: E402
from codex_harness.review.application.releases import Releases  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

PINNED = SimpleNamespace(now=lambda: datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc))
ORG = packaged_organization()
API = SimpleNamespace(MemoryStore=MemoryStore,
                      releases=lambda store: Releases(store, ORG, ticket_binding=tickets.ticket_binding, clock=PINNED),
                      ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                      TicketClosed=tickets.TicketClosed)

if __name__ == "__main__":
    driver.finish("target", "review.releases_units", s4_releases.run(API))
