"""Research ports: the buckets research owns and the owner operations it consumes (REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: research
Owns: OWNED_BUCKETS of the research context; OutboxAppend and EventAppend, the consumer-declared shapes of
    coordination's Outbox.append and EventJournal.append
Does not own: the outbox and events bucket bodies (coordination)
Entry points: OWNED_BUCKETS, OutboxAppend, EventAppend
Contracts: INV-RECURRENCE-001, INV-MESSAGE-001
"""

from __future__ import annotations

from typing import Protocol

OWNED_BUCKETS = ("inbox", "incidents", "hooks", "research_programs", "dge_sessions",
                 "dge_events")  # S6: ProgramState.resume; S8 pilot 65: the debate sessions


class OutboxAppend(Protocol):
    def append(self, tx, message: dict) -> None: ...


class EventAppend(Protocol):
    def append(self, tx, identity: str, body: dict) -> None: ...
