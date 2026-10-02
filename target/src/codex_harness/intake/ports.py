"""Intake ports: the buckets intake owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: intake
Owns: OWNED_BUCKETS of the intake context (S6: the Portfolio lineage rows; S8 pilot 63: the Portfolio acceptances, investigations and followups; S8 pilot 84 (V16): the four `desk_*` front-door buckets); OutboxAppend, the consumer-declared shape of coordination's outbox append that FrontDesk.submit joins
Does not own: the Protocols other contexts declare for intake's operations (coordination.ports.PortfolioLineage, coordination.ports.DeskQueue)
Entry points: OWNED_BUCKETS, OutboxAppend
Contracts: INV-CONTINUATION-001
"""

from __future__ import annotations

from typing import Protocol

OWNED_BUCKETS = ("portfolio_bindings", "portfolio_acceptances", "portfolio_investigations",
                 "portfolio_followups",
                 # S8 pilot 84 (DESIGN-s8 §11 V16): the sessions, requests, events and receipts only intake.application.frontdesk writes
                 "desk_sessions", "desk_requests", "desk_events", "desk_receipts")


class OutboxAppend(Protocol):
    """Coordination's `Outbox.append(tx, message)` (V16 R-f1): the assignment joins the user's turn transaction."""

    def append(self, tx, message: dict) -> None: ...
