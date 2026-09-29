"""Canonical JSON, digests, timestamps and the system clock/id source.

Layer: kernel
Context: kernel
Owns: the canonical JSON form every digest and content address is computed over
Does not own: artifact content addressing (storage.adapters.file_artifacts), message ids policy
Entry points: canonical, digest, utcnow, SystemClock, SystemIds, SYSTEM_CLOCK, SYSTEM_IDS
Contracts: INV-ENCODING-001

The canonical form (sorted keys, no ASCII escaping, compact separators) is a persisted identity:
receipts, message digests and bucket keys are sha256 over it, so it must never change.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from codex_harness.kernel.ports import Clock


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class SystemClock:
    """The host's wall clock, always timezone-aware UTC."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SystemIds:
    """Random version-4 UUIDs from the standard library."""

    def uuid4(self) -> uuid.UUID:
        return uuid.uuid4()


SYSTEM_CLOCK = SystemClock()
SYSTEM_IDS = SystemIds()


def utcnow(clock: Clock | None = None) -> str:
    """ISO-8601 UTC timestamp (the M7 record format, e.g. `2026-01-01T00:00:00+00:00`)."""
    return (clock or SYSTEM_CLOCK).now().astimezone(timezone.utc).isoformat()
