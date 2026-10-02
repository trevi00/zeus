"""Reference driver: `intake.tickets` (M7 `application/tickets.py`: `validate_content`, `Tickets`, `render_ticket`, with `ticket_binding`, `TicketClosed` and
`TicketSuperseded`).

The API holds plain M7 objects: `adapters.store.MemoryStore`, the module's names, `bootstrap.organization` (the packaged agent graph) and `domain.model`.
The harness clock and ids are installed over every loaded `codex_harness` module, so `utcnow`, the ticket id (`uuid4`) and the envelope's message id read
the scripted sources the scenario advances and resets."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_tickets  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import tickets as module  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = s8_tickets.SpreadIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    clock=CLOCK, reset=lambda: (CLOCK.reset(), IDS.reset()), MemoryStore=MemoryStore, organization=organization,
    new_tickets=lambda store, org: module.Tickets(store, org), Tickets=module.Tickets, validate_content=module.validate_content,
    render_ticket=module.render_ticket, ticket_binding=module.ticket_binding, TicketClosed=module.TicketClosed,
    TicketSuperseded=module.TicketSuperseded, TEXT_FIELDS=module.TEXT_FIELDS, LIST_FIELDS=module.LIST_FIELDS, ContractError=ContractError, digest=digest)

if __name__ == "__main__":
    driver.finish("reference", "intake.tickets", s8_tickets.run(API))
