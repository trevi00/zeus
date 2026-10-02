"""Reference driver: `intake.github_tickets` (M7 `adapters/github_tickets.py`: `GitHubTickets`).

The API holds plain M7 objects: `adapters.store.MemoryStore`, the REAL `application.tickets.Tickets` and `application.ticket_lifecycle.TicketLifecycle`, the
module's `GitHubTickets`, `domain.model`. The `gh` process is the scenario's LABELLED fake `run_process`: M7 calls the module-level name `run_process`, so
the driver binds the fake there before each observed call (`bind_runner`); no real `gh` is ever started. The harness clock and ids are installed over every
loaded `codex_harness` module, so `utcnow`, the lease's `datetime.now(timezone.utc)` and the owner token's `uuid4` read the scripted sources."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_github_tickets  # noqa: E402

from codex_harness.adapters import github_tickets as module  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import ticket_lifecycle  # noqa: E402
from codex_harness.application.tickets import Tickets, render_ticket  # noqa: E402
from codex_harness.domain.model import ContractError, canonical, digest, require  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
determinism.install(CLOCK, determinism.FakeIds())


def bind_runner(runner):
    module.run_process = runner   # the one spawn point of M7's module: the labelled fake `gh`


API = SimpleNamespace(
    clock=CLOCK, MemoryStore=MemoryStore, Tickets=Tickets, TicketLifecycle=ticket_lifecycle.TicketLifecycle, GitHubTickets=module.GitHubTickets,
    new_github=lambda tickets, artifacts, lifecycle, runner: module.GitHubTickets(tickets, artifacts, lifecycle), bind_runner=bind_runner,
    render_ticket=render_ticket, ticket_binding=None, TicketClosed=None, TicketSuperseded=None, require_no_promotion=ticket_lifecycle.require_no_promotion,
    event_document=ticket_lifecycle.event_document, verify_chain=ticket_lifecycle.verify_chain, transition=ticket_lifecycle.transition,
    ContractError=ContractError, canonical=canonical, digest=digest, require=require)

if __name__ == "__main__":
    driver.finish("reference", "intake.github_tickets", s8_github_tickets.run(API))
