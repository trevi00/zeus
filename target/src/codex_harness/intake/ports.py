"""Intake ports: the buckets intake owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: intake
Owns: OWNED_BUCKETS of the intake context (S6: the Portfolio lineage rows; S8 pilot 63: the Portfolio acceptances, investigations and followups; S8 pilot 84 (V16): the four `desk_*` front-door buckets; S8 pilot 98 (V11): the eight ticket buckets; S8 batch B2 (V30 R-tk3): the five ticket buckets of `Tickets` and `GitHubTickets`); OutboxAppend, the consumer-declared shape of coordination's outbox append that FrontDesk.submit joins
Does not own: the Protocols other contexts declare for intake's operations (coordination.ports.PortfolioLineage, coordination.ports.DeskQueue)
Entry points: OWNED_BUCKETS, OutboxAppend
Contracts: INV-CONTINUATION-001
"""

from __future__ import annotations

from typing import Protocol

OWNED_BUCKETS = ("portfolio_bindings", "portfolio_acceptances", "portfolio_investigations",
                 "portfolio_followups",
                 # S8 pilot 84 (DESIGN-s8 §11 V16): the sessions, requests, events and receipts only intake.application.frontdesk writes
                 "desk_sessions", "desk_requests", "desk_events", "desk_receipts",
                 # S8 pilot 98 (DESIGN-s8 §6 V11): the ticket rows and the lifecycle's decision, closure, reopen and pin rows only
                 # intake.application.ticket_lifecycle writes (the ticket rows' other writers join with `Tickets`)
                 "tickets", "ticket_dispatches", "ticket_closures", "ticket_closure_sequences", "ticket_reopens", "ticket_github",
                 "ticket_lifecycle_events", "ticket_trust_anchors",
                 # S8 batch B2 (DESIGN-s8 §25 V30 R-tk3): `Tickets` writes the revisions and reviews (and, with the lifecycle, `tickets` and
                 # `ticket_dispatches`); `GitHubTickets` writes the remote creations, observations and syncs (and, with the lifecycle, `ticket_github`)
                 "ticket_reviews", "ticket_revisions", "ticket_remote_creations", "ticket_remote_observations", "ticket_syncs")


class OutboxAppend(Protocol):
    """Coordination's `Outbox.append(tx, message)` (V16 R-f1): the assignment joins the user's turn transaction."""

    def append(self, tx, message: dict) -> None: ...
