"""Reference driver: `intake.ticket_lifecycle` (M7 `application/ticket_lifecycle.py`: `TicketLifecycle` and its helpers).

The API holds plain M7 objects: `adapters.store.MemoryStore`, the REAL `application.tickets.Tickets` (the lifecycle receives it as it is), the module's
names, `application.tickets.ticket_binding`/`TicketClosed`/`TicketSuperseded` and `domain.model`. The authority and the artifact store are the
scenario's LABELLED fakes. The harness clock and ids are installed over every loaded `codex_harness` module, so `datetime.now(timezone.utc)` and
`utcnow` read the scripted clock the scenario advances."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_ticket_lifecycle  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import ticket_lifecycle as module  # noqa: E402
from codex_harness.application.tickets import (  # noqa: E402
    TicketClosed,
    Tickets,
    TicketSuperseded,
    ticket_binding,
)
from codex_harness.domain.model import ContractError, canonical, digest, require  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
determinism.install(CLOCK, determinism.FakeIds())

API = SimpleNamespace(
    clock=CLOCK, MemoryStore=MemoryStore, Tickets=Tickets, TicketLifecycle=module.TicketLifecycle, ticket_binding=ticket_binding,
    TicketClosed=TicketClosed, TicketSuperseded=TicketSuperseded, require_no_promotion=module.require_no_promotion,
    event_document=module.event_document, verify_chain=module.verify_chain, transition=module.transition,
    ContractError=ContractError, canonical=canonical, digest=digest, require=require)

if __name__ == "__main__":
    driver.finish("reference", "intake.ticket_lifecycle", s8_ticket_lifecycle.run(API))
