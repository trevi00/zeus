"""Target-side injection helpers for the S1 drivers (REBUILD-DESIGN-v2 §5.2 R-D).

Layer: harness (never shipped); standard library only.

The target never has its standard library patched: the scripted fake clock and id source reach it
through the kernel `Clock`/`IdSource` ports. These adapters present the harness fakes as those
ports, so both sides see the same instants and the same ids.
"""

from __future__ import annotations

from datetime import timezone


class PortClock:
    def __init__(self, fake):
        self.fake = fake

    def now(self):
        return self.fake.now(timezone.utc)


class PortIds:
    def __init__(self, fake):
        self.fake = fake

    def uuid4(self):
        return self.fake.uuid4()


class FixtureEventJournal:
    """Stands in for coordination's `EventJournal` (implemented in S5) with the M7 write rule:
    `tx.get("events", id) is None` then `tx.put("events", id, body)`, inside the caller's unit."""

    def append(self, tx, event_id, body):
        if tx.get("events", event_id) is None:
            tx.put("events", event_id, body)
