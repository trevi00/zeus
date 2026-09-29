"""Ticket provenance binding: find and validate the same ticket revision across plan/rework/review (INV-TICKET-001).

Layer: application
Context: intake
Owns: TicketSuperseded, TicketClosed, ticket_binding (M7 `application/tickets.py`, moved ahead in S4 unchanged:
    lead decision Option A, an owner operation the S4 units call)
Does not own: the rest of M7 `application/tickets.py` (validate_content, Tickets: S8), the ticket rows'
    writers (S8)
Entry points: TicketSuperseded, TicketClosed, ticket_binding
Contracts: INV-TICKET-001

Other contexts reach `ticket_binding` through an injected callable (§2.4: no other application imports it).
Ticket feedback is advisory, never release authority.
"""

from __future__ import annotations

from copy import deepcopy

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest


class TicketSuperseded(ContractError):
    """The request changed; retain execution evidence without downstream authority."""


class TicketClosed(TicketSuperseded):
    """Acceptance ended this work cycle; preserve results and stop downstream work."""


def ticket_binding(tx, value):
    """INV-TICKET-001: find and validate the same provenance across plan/rework/review."""
    bindings = []
    def visit(item):
        if isinstance(item, dict):
            if "zeus_ticket" in item:
                bound = item["zeus_ticket"]
                require(isinstance(bound, dict) and set(bound) in ({"id", "revision", "content_hash"},
                        {"id", "revision", "content_hash", "lifecycle_sequence"}),
                        "Invalid Zeus ticket binding")
                bindings.append(bound)
            for key, child in item.items():
                if key != "zeus_ticket":
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    if not bindings:
        return None
    require(all(row == bindings[0] for row in bindings), "Conflicting ticket revisions")
    bound = bindings[0]
    current = tx.get("tickets", bound["id"])
    require(current is not None, "Ticket missing")
    if current["status"] == "closed":
        raise TicketClosed("Ticket closed; downstream work stopped")
    if (type(bound.get("lifecycle_sequence", 0)) is not int
            or bound.get("lifecycle_sequence", 0) != current.get("lifecycle_sequence", 0)):
        raise TicketSuperseded("Ticket lifecycle changed; old work cannot resume")
    if current["revision"] != bound["revision"] or current["content_hash"] != bound["content_hash"]:
        raise TicketSuperseded("Ticket changed; reassessment required")
    revision = tx.get("ticket_revisions", f'{bound["id"]}:{bound["revision"]}')
    require(revision and digest(revision["content"]) == bound["content_hash"], "Ticket revision corrupted")
    return deepcopy(bound)
