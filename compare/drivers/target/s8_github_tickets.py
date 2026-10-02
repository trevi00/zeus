"""Target driver: `intake.github_tickets` on the target tree (S8 batch B2: `intake.adapters.github_tickets`).

The API mirrors the reference driver's names over the target homes: `GitHubTickets` from `intake.adapters.github_tickets`, the moved `Tickets` and
`render_ticket` from `intake.application.tickets`, the lifecycle and `transition` from `intake.application.ticket_lifecycle`, the memory store from storage,
the kernel's `ContractError`/`canonical`/`digest`/`require`. The `gh` process is the scenario's LABELLED fake `run_process`, INJECTED (R-gh1: the keyword-only
`run_process` port, the shape of the host_os adapter); `bind_runner` is therefore a no-op here. The scripted clock reaches the target through the kernel
`Clock` port (`kernel.ids.SYSTEM_CLOCK`: `utcnow`) and, for the `datetime.now(timezone.utc)` and `datetime.fromisoformat` of the lease, the lifecycle and its
domain, through the module-level `datetime` name each of the three owns; the owner token's `uuid4` through the module-level name too (the target's standard
library is never patched), as the reference run's patched stdlib did."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_github_tickets  # noqa: E402
from codex_harness.intake.adapters import github_tickets as module  # noqa: E402
from codex_harness.intake.application import ticket_lifecycle  # noqa: E402
from codex_harness.intake.application.tickets import Tickets, render_ticket  # noqa: E402
from codex_harness.intake.domain import ticket_lifecycle as domain  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError, require  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
ids.SYSTEM_CLOCK = PortClock(CLOCK)
SCRIPTED_DATETIME = SimpleNamespace(now=CLOCK.now, fromisoformat=datetime.fromisoformat)
module.datetime = SCRIPTED_DATETIME             # the lease: `datetime.now(timezone.utc)` and `datetime.fromisoformat`
ticket_lifecycle.datetime = SCRIPTED_DATETIME   # the lifecycle's `datetime.now(timezone.utc)`
domain.datetime = SCRIPTED_DATETIME             # `validate_packet`'s default `now` and `timestamp`'s `fromisoformat`
module.uuid4 = IDS.uuid4                        # the sync owner token: the harness id source, as the reference run installed it

API = SimpleNamespace(
    clock=CLOCK, MemoryStore=MemoryStore, Tickets=Tickets, TicketLifecycle=ticket_lifecycle.TicketLifecycle, GitHubTickets=module.GitHubTickets,
    new_github=lambda tickets, artifacts, lifecycle, runner: module.GitHubTickets(tickets, artifacts, lifecycle, run_process=runner),
    bind_runner=lambda runner: None, render_ticket=render_ticket, ticket_binding=None, TicketClosed=None, TicketSuperseded=None,
    require_no_promotion=ticket_lifecycle.require_no_promotion, event_document=ticket_lifecycle.event_document,
    verify_chain=ticket_lifecycle.verify_chain, transition=ticket_lifecycle.transition,
    ContractError=ContractError, canonical=canonical, digest=digest, require=require)

if __name__ == "__main__":
    driver.finish("target", "intake.github_tickets", s8_github_tickets.run(API))
