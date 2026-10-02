"""Target driver: `intake.ticket_lifecycle` on the target tree (S8 pilot 98: `intake.application.ticket_lifecycle`).

The API mirrors the reference driver's names over the target homes: the lifecycle and its helpers from `intake.application.ticket_lifecycle`,
`ticket_binding`/`TicketClosed`/`TicketSuperseded` from `intake.application.tickets` (the S4 move-ahead), the memory store from storage, the
kernel's `ContractError`/`canonical`/`digest`/`require`.

`Tickets` is the moved class (S8 batch B2, V30 R-tk5: the labelled stand-in of pilot 98 is rebound to `intake.application.tickets.Tickets`; the lifecycle
receives it constructed from `(store, organization)` alone, as M7's did). The scripted clock reaches the target through the kernel
`Clock` port (`kernel.ids.SYSTEM_CLOCK`: `utcnow`) and, for the module's and the domain's `datetime.now(timezone.utc)` and `datetime.fromisoformat`,
through the module-level `datetime` name each of the two owns (the target's standard library is never patched), as the reference run's patched stdlib
did."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_ticket_lifecycle  # noqa: E402
from codex_harness.intake.application import ticket_lifecycle as module  # noqa: E402
from codex_harness.intake.application.tickets import (  # noqa: E402
    TicketClosed,
    Tickets,
    TicketSuperseded,
    ticket_binding,
)
from codex_harness.intake.domain import ticket_lifecycle as domain  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError, require  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)
SCRIPTED_DATETIME = SimpleNamespace(now=CLOCK.now, fromisoformat=datetime.fromisoformat)
module.datetime = SCRIPTED_DATETIME   # `datetime.now(timezone.utc)` reads the scripted clock
domain.datetime = SCRIPTED_DATETIME   # `validate_packet`'s default `now` and `timestamp`'s `fromisoformat`


API = SimpleNamespace(
    clock=CLOCK, MemoryStore=MemoryStore, Tickets=Tickets, TicketLifecycle=module.TicketLifecycle, ticket_binding=ticket_binding,
    TicketClosed=TicketClosed, TicketSuperseded=TicketSuperseded, require_no_promotion=module.require_no_promotion,
    event_document=module.event_document, verify_chain=module.verify_chain, transition=module.transition,
    ContractError=ContractError, canonical=canonical, digest=digest, require=require)

if __name__ == "__main__":
    driver.finish("target", "intake.ticket_lifecycle", s8_ticket_lifecycle.run(API))
