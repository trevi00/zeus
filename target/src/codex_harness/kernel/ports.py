"""Kernel ports: the clock, the id source and the observation sink every context may depend on.

Layer: kernel
Context: kernel
Owns: the Protocols only; `kernel.ids` holds the system implementations
Does not own: the observation spool itself (observation context, S9)
Entry points: Clock.now, IdSource.uuid4, ObservationSink.append

Time and identifiers are injected (REBUILD-DESIGN-v2 §5.2 R-D): target code that records a time or
mints an id takes a Clock/IdSource, so a differential run supplies the scripted fakes instead of
patching the standard library.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time as an aware UTC datetime."""
        ...


class IdSource(Protocol):
    def uuid4(self) -> UUID:
        """A fresh random (version 4) UUID."""
        ...


class ObservationSink(Protocol):
    """Append-only observation records of one process run (INV-OBSERVATION-001 is owned by
    observation; this is the narrow write side other contexts are allowed to see)."""

    def append(self, kind: str, event: dict) -> int: ...
