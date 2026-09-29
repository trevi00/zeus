"""The in-memory observation spool stand-in (INV-OBSERVATION-001), moved ahead in S4 unchanged.

Layer: adapters
Context: observation
Owns: RECORD_KINDS, encode_record and MemorySpool (M7 `adapters/observation_spool.py`, moved ahead in S4 unchanged:
    the spool the Observer's unit boundary and the S4 comparison drivers use)
Does not own: FileSpool, SpoolDirectory and the file functions (S9)
Entry points: MemorySpool, encode_record, RECORD_KINDS
Contracts: INV-OBSERVATION-001
"""

from __future__ import annotations

import hashlib
import json

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import canonical
from codex_harness.observation.ports import SpoolFull

RECORD_KINDS = ("event", "audit")


def encode_record(kind: str, event: dict) -> bytes:
    require(kind in RECORD_KINDS, "Unknown spool record kind")
    body = canonical(event).encode("utf-8", "surrogatepass")
    require(b"\n" not in body, "Canonical JSON never contains a raw newline")
    return hashlib.sha256(body).hexdigest().encode("ascii") + b" " + kind.encode("ascii") + b" " + body + b"\n"


class MemorySpool:
    """In-process stand-in with the same failure surface, for unit boundaries only."""

    def __init__(self, process_run_id: str, *, max_bytes: int = 1 << 20):
        self.process_run_id, self.max_bytes = process_run_id, max_bytes
        self.lines: list[bytes] = []
        self.size_bytes = 0
        self.fail_with: Exception | None = None

    def append(self, kind: str, event: dict) -> int:
        if self.fail_with is not None:
            raise self.fail_with
        line = encode_record(kind, event)
        if self.size_bytes + len(line) > self.max_bytes:
            raise SpoolFull("memory spool full")
        self.lines.append(line)
        self.size_bytes += len(line)
        return self.size_bytes

    def records(self) -> list[dict]:
        return [json.loads(line.split(b" ", 2)[2].decode("utf-8", "surrogatepass")) for line in self.lines]

    def size(self) -> int:
        return self.size_bytes

    def close(self) -> None:
        return None
