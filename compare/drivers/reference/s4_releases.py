"""Reference driver: `review.releases_units` (M7 Releases.propose/review and tickets.ticket_binding)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s4_releases  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import releases, tickets  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402

# R-D: the release receipt time is pinned (the reference file is untouched).
releases.utcnow = lambda: "2026-01-01T00:00:05+00:00"
ORG = organization()
API = SimpleNamespace(MemoryStore=MemoryStore, releases=lambda store: releases.Releases(store, ORG),
                      ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                      TicketClosed=tickets.TicketClosed)

if __name__ == "__main__":
    driver.finish("reference", "review.releases_units", s4_releases.run(API))
