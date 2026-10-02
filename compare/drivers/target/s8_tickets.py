"""Target driver: `intake.tickets` on the target tree (S8 batch B2: `intake.application.tickets`, the rest of M7 `application/tickets.py` merged next to the
S4 move-ahead names).

The API mirrors the reference driver's names over the target homes: the module's names from `intake.application.tickets`, the memory store from storage,
the packaged organization from routing, the kernel's `ContractError` and `digest`. `Tickets` is built with its one injected port (R-tk2): coordination's
`Outbox` (the shape of `intake.ports.OutboxAppend`). The harness's scripted clock reaches the kernel through the `Clock` port (`kernel.ids.SYSTEM_CLOCK`:
`utcnow`, the envelope's `created_at`) and the scripted ids through `kernel.message.SYSTEM_IDS` (the message id). M7 read the patched stdlib for the ticket
id (`uuid4`); the target's standard library is never patched, so the driver substitutes that one module name with the scripted id source."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_tickets  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.intake.application import tickets as module  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = s8_tickets.SpreadIds()
ids.SYSTEM_CLOCK = PortClock(CLOCK)
message.SYSTEM_IDS = PortIds(IDS)
module.uuid4 = IDS.uuid4   # the ticket id: the harness id source, as the reference run installed it

API = SimpleNamespace(
    clock=CLOCK, reset=lambda: (CLOCK.reset(), IDS.reset()), MemoryStore=MemoryStore, organization=packaged_organization,
    new_tickets=lambda store, org: module.Tickets(store, org, outbox=Outbox()), Tickets=module.Tickets, validate_content=module.validate_content,
    render_ticket=module.render_ticket, ticket_binding=module.ticket_binding, TicketClosed=module.TicketClosed,
    TicketSuperseded=module.TicketSuperseded, TEXT_FIELDS=module.TEXT_FIELDS, LIST_FIELDS=module.LIST_FIELDS, ContractError=ContractError, digest=digest)

if __name__ == "__main__":
    driver.finish("target", "intake.tickets", s8_tickets.run(API))
