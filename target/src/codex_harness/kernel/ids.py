"""Canonical JSON, digests, timestamps and the system clock/id source.

Layer: kernel
Context: kernel
Owns: the canonical JSON form every digest and content address is computed over; identifier and
    repository-path grammars shared by coordination, research, intake and delivery (TRACE C3)
Does not own: artifact content addressing (storage.adapters.file_artifacts), message ids policy
Entry points: canonical, digest, utcnow, SystemClock, SystemIds, SYSTEM_CLOCK, SYSTEM_IDS, ID, REVISION, SHA256,
    SEGMENT, safe_relative_path
Contracts: INV-ENCODING-001

The canonical form (sorted keys, no ASCII escaping, compact separators) is a persisted identity:
receipts, message digests and bucket keys are sha256 over it, so it must never change.
"""

from __future__ import annotations

import hashlib
import json
import re
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


ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
# One path segment: the unchanged ordinary grammar, or one optional leading dot before the same
# alphanumeric start; the dot counts toward the 255-character segment budget. `.`, `..`, repeated
# leading dots, whitespace, colons (drives, ADS), backslashes and control characters never match.
SEGMENT = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9._-]{0,254}|\.[A-Za-z0-9][A-Za-z0-9._-]{0,253})$")


def safe_relative_path(value) -> bool:
    """A forward-slash relative repository path: no traversal, no `.git`, no drive or root.

    Ordinary dot-prefixed project content (`.github/workflows/ci.yml`, `.gitignore`,
    `docs/.github/GOAL.md`) is accepted; `.git` in any letter case at any depth and every
    dot-prefixed segment ending in a period (`.git.`, `.GIT..`) are refused, so no alias of the
    metadata directory passes. This is manifest grammar, not filesystem containment: symlinks,
    hard links and case collisions are the isolated staging's job (INV-ISOLATED-WORKER-001).
    """
    if type(value) is not str or not value or len(value) > 1024 or "\\" in value or value.startswith("/"):
        return False
    return all(SEGMENT.fullmatch(s) is not None and s.lower() != ".git" and not (s[0] == "." and s[-1] == ".")
               for s in value.split("/"))
