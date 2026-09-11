"""Durable, bounded, per-process observation spool under the configured runtime directory.

One process run owns one append-only spool file, so there is never a concurrent appender on a
file: Windows and Linux differ in how concurrent appends interleave, and a single writer with
one `write` call per record sidesteps that difference. Each record is one line
`<sha256 of body> <kind> <body>\\n`; a reader tells a complete record from a truncated tail (no
newline yet, or the process died mid-write) and from a corrupt line (hash or JSON mismatch), so a
crash loses at most the partial tail and never a completed record. Consumption is acknowledged
by an offset file written with an atomic replace, so a collector that dies after committing to the
sink but before acknowledging re-reads and deduplicates instead of losing or doubling records.
Post-execution termination evidence and the process health record use the same atomic-replace
writes; they are the protected local path that must work when PostgreSQL and Redis do not.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from codex_harness.domain.model import ContractError, canonical, require, utcnow
from codex_harness.ports import SpoolFull

RECORD_KINDS = ("event", "audit")
LINE = re.compile(rb"^([0-9a-f]{64}) (event|audit) (.*)$", re.S)
RECORD_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


def atomic_write(path: Path, text: str) -> None:
    """Write via a temporary file and os.replace, which is atomic on both Windows and POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def encode_record(kind: str, event: dict) -> bytes:
    require(kind in RECORD_KINDS, "Unknown spool record kind")
    body = canonical(event).encode("utf-8", "surrogatepass")
    require(b"\n" not in body, "Canonical JSON never contains a raw newline")
    return hashlib.sha256(body).hexdigest().encode("ascii") + b" " + kind.encode("ascii") + b" " + body + b"\n"


def read_records(path: Path, offset: int = 0):
    """Yield (start, end, status, kind, event, defect) for every line from `offset`.

    status is `complete`, `corrupt` (consumed and quarantined by the reader's caller) or
    `truncated_tail` (not consumed: the writer may still be alive, or died mid-write).
    """
    with path.open("rb") as stream:
        stream.seek(offset)
        position = offset
        while True:
            line = stream.readline()
            if not line:
                return
            start, position = position, position + len(line)
            if not line.endswith(b"\n"):
                yield start, position, "truncated_tail", None, None, "no newline"
                return
            match = LINE.match(line[:-1])
            if not match:
                yield start, position, "corrupt", None, None, "line shape"
                continue
            claimed, kind, body = match.group(1).decode("ascii"), match.group(2).decode("ascii"), match.group(3)
            if hashlib.sha256(body).hexdigest() != claimed:
                yield start, position, "corrupt", kind, None, "hash mismatch"
                continue
            try:
                event = json.loads(body.decode("utf-8", "surrogatepass"))
            except (ValueError, UnicodeError):
                yield start, position, "corrupt", kind, None, "invalid json"
                continue
            if not isinstance(event, dict):
                yield start, position, "corrupt", kind, None, "not an object"
                continue
            yield start, position, "complete", kind, event, None


class FileSpool:
    """The spool of one process run. `append` is the only writer; readers are separate."""

    def __init__(self, root, process_run_id: str, *, max_bytes: int, fsync: bool = True):
        require(type(max_bytes) is int and max_bytes > 0, "Spool limit must be a positive byte count")
        self.root = Path(root)
        self.process_run_id = process_run_id
        self.max_bytes, self.fsync = max_bytes, fsync
        self.path = self.root / "spool" / (process_run_id + ".jsonl")
        self._descriptor = None

    def _open(self):
        if self._descriptor is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
            self._descriptor = os.open(self.path, flags, 0o600)
        return self._descriptor

    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def append(self, kind: str, event: dict) -> int:
        """Append one record; returns the byte offset after the record. Raises SpoolFull when bounded out."""
        line = encode_record(kind, event)
        descriptor = self._open()
        size = os.fstat(descriptor).st_size
        if size + len(line) > self.max_bytes:
            raise SpoolFull(f"spool {self.path.name} holds {size} of {self.max_bytes} bytes")
        written = os.write(descriptor, line)
        require(written == len(line), "Short spool write")
        if self.fsync:
            os.fsync(descriptor)
        return size + written

    def close(self) -> None:
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None


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

    def close(self) -> None:
        return None


class SpoolDirectory:
    """Everything a collector or an operator reads: spool files, acknowledgements, health, terminations."""

    def __init__(self, root):
        self.root = Path(root)

    def spool_files(self) -> list[Path]:
        directory = self.root / "spool"
        return sorted(directory.glob("*.jsonl")) if directory.is_dir() else []

    def read(self, path: Path, offset: int = 0):
        return read_records(path, offset)

    def acknowledged(self, path: Path) -> int:
        ack = path.with_suffix(".ack")
        try:
            value = json.loads(ack.read_text("utf-8"))
            offset = value.get("offset")
            require(type(offset) is int and 0 <= offset, "Invalid acknowledgement offset")
            return offset
        except FileNotFoundError:
            return 0
        except (ValueError, ContractError, OSError):
            return 0  # an unreadable acknowledgement re-reads; the sink deduplicates by event id

    def acknowledge(self, path: Path, offset: int, consumed: int) -> None:
        atomic_write(path.with_suffix(".ack"), canonical({"offset": offset, "consumed": consumed,
                                                          "updated_at": utcnow()}) + "\n")

    def write_health(self, process_run_id: str, record: dict) -> Path:
        path = self.root / "health" / (process_run_id + ".json")
        atomic_write(path, canonical(record) + "\n")
        return path

    def read_health(self) -> list[dict]:
        directory = self.root / "health"
        rows = []
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            try:
                value = json.loads(path.read_text("utf-8"))
            except (ValueError, OSError):
                value = {"process_run_id": path.stem, "unreadable": True}
            rows.append(value)
        return rows

    def record_termination(self, record_id: str, record: dict) -> Path:
        """Create-only: a termination record is evidence, never overwritten."""
        require(RECORD_ID.fullmatch(record_id) is not None, "Invalid termination record id")
        path = self.root / "terminations" / (record_id + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return path

    def pending_terminations(self, task_id: str | None = None) -> list[dict]:
        directory = self.root / "terminations"
        rows = []
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            try:
                value = json.loads(path.read_text("utf-8"))
            except (ValueError, OSError):
                value = {"record_id": path.stem, "unreadable": True, "task_id": None}
            if task_id is None or value.get("task_id") == task_id or value.get("unreadable"):
                rows.append(value)
        return rows

    def resolve_termination(self, record_id: str, resolution: dict) -> dict:
        require(RECORD_ID.fullmatch(record_id) is not None, "Invalid termination record id")
        path = self.root / "terminations" / (record_id + ".json")
        require(path.is_file(), "Unknown termination record")
        record = json.loads(path.read_text("utf-8"))
        resolved = {**record, "resolution": resolution}
        target = self.root / "terminations" / "resolved" / (record_id + ".json")
        atomic_write(target, canonical(resolved) + "\n")
        os.unlink(path)
        return resolved
