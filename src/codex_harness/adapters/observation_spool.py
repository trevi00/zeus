"""Durable, bounded, per-process observation spool under the configured runtime directory.

One process run owns one sequence of append-only segment files, so there is never a concurrent
appender on a file: Windows and Linux differ in how concurrent appends interleave, and a single
writer with one `write` call per record sidesteps that difference. Each record is one line
`<sha256 of body> <kind> <body>\\n`; a reader tells a complete record from a truncated tail (no
newline yet, or the process died mid-write) and from a corrupt line (hash or JSON mismatch), so a
crash loses at most the partial tail and never a completed record.

Space is bounded by *unacknowledged* bytes, not by file size: the writer rotates to a new segment
when the current one reaches the segment size, the collector acknowledges each segment by an
offset file written with an atomic replace, and a segment that is fully acknowledged and no longer
the writer's current one (a later segment exists, or the run wrote its `closed` marker) is
reclaimed by the collector. A writer that keeps producing while the collector keeps consuming
never fills up; a writer whose collector is gone stops at the byte limit and reports it. An active
segment is never truncated, so writer and reader offsets stay valid.

Post-execution termination evidence, pending alerts and the process health record use the same
atomic-replace writes; they are the protected local path that must work when PostgreSQL and
Redis do not.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

from filelock import FileLock, Timeout

from codex_harness.domain.model import ContractError, canonical, require, utcnow
from codex_harness.domain.policy import POLICY
from codex_harness.ports import SpoolFull


def run_lock_path(root: Path, process_run_id: str) -> Path:
    return root / "spool" / (process_run_id + ".lock")


LIFECYCLE_TIMEOUT = 10.0  # seconds a writer or collector waits for the directory lifecycle lock


def lifecycle_lock(root: Path) -> FileLock:
    """The directory's lifecycle lock: serializes writer registration (run lock + active segment),
    writer close, liveness probes and garbage collection of a run's files.

    A run's own lock proves its writer is alive, but a decision taken from that proof and the file
    changes that follow it are two steps; a writer that registers between them (opens the run lock
    file, acquires it, opens its first segment) would have its active file deleted by a collector
    still acting on the earlier answer. Both sides therefore work under this one lock: a writer
    registers or finishes inside it, a collector decides and deletes inside it. The lock is one
    object per path in this process (reentrant within a thread), exclusive across threads and
    processes, independent of any run's lifetime and never removed by run garbage collection.
    """
    path = Path(root) / "spool" / ".lifecycle.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path), is_singleton=True)


def writer_alive(root: Path, process_run_id: str) -> bool:
    """Liveness proof for a run's writer: its lock is held by a live process.

    The lock is released by the operating system when the holder dies (BSD flock on Linux/WSL,
    LockFileEx region locking on Windows), so a free lock is proof that no writer remains, and a
    held lock is proof that one does — file age proves neither. The probe runs under the lifecycle
    lock so it never overlaps a writer's registration; a busy lifecycle lock is not proof of
    absence and answers "alive".
    """
    path = run_lock_path(root, process_run_id)
    guard = lifecycle_lock(root)
    try:
        guard.acquire(timeout=LIFECYCLE_TIMEOUT)
    except (Timeout, OSError):
        return True
    try:
        probe = FileLock(str(path), is_singleton=False)
        try:
            probe.acquire(timeout=0)
        except Timeout:
            return True
        except OSError:
            return True  # cannot prove absence: treat the writer as alive
        probe.release()
        return False
    finally:
        guard.release()

RECORD_KINDS = ("event", "audit")
LINE = re.compile(rb"^([0-9a-f]{64}) (event|audit) (.*)$", re.S)
RECORD_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
IDENTIFIER_NAME = re.compile(r"^[0-9a-f]{32}$")
# The writer names segments with at least four digits; the reader accepts any width and orders
# numerically, so index 10000 follows 9999 instead of disappearing or sorting before it.
SEGMENT = re.compile(r"^(?P<run>[0-9a-f]{32})\.(?P<segment>\d{4,})\.jsonl$")


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


def segment_path(root: Path, process_run_id: str, segment: int) -> Path:
    return root / "spool" / f"{process_run_id}.{segment:04d}.jsonl"


def segment_identity(path: Path):
    match = SEGMENT.match(path.name)
    return (match.group("run"), int(match.group("segment"))) if match else None


def read_acknowledged(path: Path) -> int:
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


class FileSpool:
    """The spool of one process run: rotating segments, bounded by unacknowledged bytes."""

    def __init__(self, root, process_run_id: str, *, max_bytes: int,
                 segment_bytes: int = POLICY.observation_segment_bytes, fsync: bool = True):
        require(type(max_bytes) is int and max_bytes > 0, "Spool limit must be a positive byte count")
        require(type(segment_bytes) is int and segment_bytes > 0, "Segment size must be positive")
        self.root = Path(root)
        self.process_run_id = process_run_id
        # A segment never exceeds the spool limit; a small limit simply rotates more often.
        self.max_bytes, self.segment_bytes, self.fsync = max_bytes, min(segment_bytes, max_bytes), fsync
        self.segment = 0
        self._descriptor = None
        self._size = 0            # bytes in the current segment
        self._unacked = 0         # upper bound of unacknowledged bytes across this run's segments
        self.rotations = 0
        self._lock = None
        self.closed = False

    @property
    def path(self) -> Path:
        return segment_path(self.root, self.process_run_id, self.segment)

    @property
    def owns_run(self) -> bool:
        """True only while this object holds the run lock: the sole writer allowed to finish the run."""
        return self._lock is not None

    def _hold_lock(self):
        """The run's lock is the writer's liveness proof; it is held for the life of the process."""
        if self._lock is None:
            path = run_lock_path(self.root, self.process_run_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = FileLock(str(path), is_singleton=False)
            try:
                lock.acquire(timeout=0)
            except Timeout as exc:
                raise ContractError("Another live writer holds this observation run") from exc
            self._lock = lock

    def _open(self):
        """Open the active segment. Registration (run lock + first open) and every later segment
        open happen under the directory lifecycle lock, so a collector never sees a run between
        'no owner' and 'owner with an active file'."""
        if self._descriptor is None:
            guard = lifecycle_lock(self.root)
            try:
                guard.acquire(timeout=LIFECYCLE_TIMEOUT)
            except Timeout as exc:
                raise ContractError("The observation directory is busy; this run cannot register now") from exc
            try:
                self._hold_lock()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
                self._descriptor = os.open(self.path, flags, 0o600)
                self._size = os.fstat(self._descriptor).st_size
            finally:
                guard.release()
        return self._descriptor

    def segments(self) -> list[Path]:
        directory = self.root / "spool"
        return sorted(directory.glob(self.process_run_id + ".*.jsonl")) if directory.is_dir() else []

    def unacknowledged_bytes(self) -> int:
        """Exact unacknowledged bytes: segment sizes minus their acknowledged offsets."""
        total = 0
        for path in self.segments():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            total += max(0, size - min(read_acknowledged(path), size))
        return total

    def size(self) -> int:
        return self.unacknowledged_bytes()

    def _rotate(self):
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None
        self.segment += 1
        self.rotations += 1
        self._size = 0

    def append(self, kind: str, event: dict) -> int:
        """Append one record; returns the offset after it in the current segment. Raises SpoolFull."""
        require(not self.closed, "This observation run was closed by its writer and cannot be resumed")
        line = encode_record(kind, event)
        self._open()
        if self._size and self._size + len(line) > self.segment_bytes:
            self._rotate()
            self._open()
        if self._unacked + len(line) > self.max_bytes:
            # The estimate only grows between checks; recompute from disk before refusing.
            self._unacked = self.unacknowledged_bytes()
            if self._unacked + len(line) > self.max_bytes:
                raise SpoolFull(f"spool {self.process_run_id} holds {self._unacked} unacknowledged "
                                f"of {self.max_bytes} bytes")
        written = os.write(self._descriptor, line)
        require(written == len(line), "Short spool write")
        if self.fsync:
            os.fsync(self._descriptor)
        self._size += written
        self._unacked += written
        return self._size

    def close(self) -> None:
        """Finish the run: close the active file, write the closed marker, release the lock.

        Only the run's owner (the object holding the lock) may write the marker; an object that
        never acquired the lock — a refused second writer, or one that never appended — cleans up
        nothing shared, because the marker would finish another writer's live run. Repeated close
        is a no-op and a closed object refuses further appends.
        """
        if self.closed:
            return
        self.closed = True
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None
        if self._lock is None:
            return
        guard = lifecycle_lock(self.root)
        try:
            guard.acquire(timeout=LIFECYCLE_TIMEOUT)
        except (Timeout, OSError):
            guard = None  # finishing is safe unserialized: appends are refused and the run lock is still held
        try:
            self._finish()
        finally:
            if guard is not None:
                guard.release()

    def _finish(self) -> None:
        try:
            atomic_write(self.root / "spool" / (self.process_run_id + ".closed"),
                         canonical({"closed_at": utcnow(), "segments": self.segment + 1}) + "\n")
        except OSError:
            pass  # a missing marker only delays reclamation of the last segment until the lock frees
        try:
            self._lock.release()
        except OSError:
            pass
        self._lock = None


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


class SpoolDirectory:
    """Everything a collector or an operator reads: segments, acknowledgements, health, terminations, alerts."""

    def __init__(self, root):
        self.root = Path(root)

    # ---- segments -----------------------------------------------------------------------------
    def spool_files(self) -> list[Path]:
        directory = self.root / "spool"
        if not directory.is_dir():
            return []
        return sorted((path for path in directory.glob("*.jsonl") if segment_identity(path)),
                      key=lambda path: segment_identity(path))

    def writer_alive(self, process_run_id: str) -> bool:
        return writer_alive(self.root, process_run_id)

    def _run_files(self, process_run_id: str) -> list[Path]:
        """Files the writer itself wrote: segments, closed marker, health. The lock file and the
        acknowledgement files are excluded: a liveness probe truncates the lock file and a
        collector writes acknowledgements, and neither is the writer's last durable record."""
        files = [path for path in self.spool_files() if segment_identity(path)[0] == process_run_id]
        for candidate in (self.root / "spool" / (process_run_id + ".closed"),
                          self.root / "health" / (process_run_id + ".json")):
            if candidate.is_file():
                files.append(candidate)
        return files

    def known_runs(self) -> set[str]:
        runs = {segment_identity(path)[0] for path in self.spool_files()}
        spool = self.root / "spool"
        for suffix in (".closed", ".lock"):
            runs.update(path.name[:-len(suffix)] for path in (spool.glob("*" + suffix) if spool.is_dir() else [])
                        if IDENTIFIER_NAME.fullmatch(path.name[:-len(suffix)]))
        health = self.root / "health"
        runs.update(path.stem for path in (health.glob("*.json") if health.is_dir() else [])
                    if IDENTIFIER_NAME.fullmatch(path.stem))
        return runs

    def run_age(self, process_run_id: str, now: float | None = None) -> float | None:
        """Seconds since the writer's newest durable record (segments, marker, health) was modified.

        Reading and probing never move this clock: the age is computed before any lock probe and
        from writer-owned files only, so a collector that checks more often than the retention
        window cannot keep deferring a dead run's cleanup."""
        moment = time.time() if now is None else now
        newest = 0.0
        for path in self._run_files(process_run_id):
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
        return moment - newest if newest else None

    def run_finished(self, process_run_id: str, now: float | None = None,
                     retention_seconds: int = POLICY.observation_retention_seconds) -> bool:
        """A run is finished when it wrote its closed marker, or when no live writer holds its lock
        and its last write is older than the retention window. Age alone never finishes a run: a
        process that is merely idle, paused or on a moved clock still holds the lock."""
        if self.closed(process_run_id):
            return True
        age = self.run_age(process_run_id, now)  # measured before the probe, from writer-owned files
        if self.writer_alive(process_run_id):
            return False
        if age is None:
            return True  # nothing the writer wrote remains (a leftover lock file at most) and nobody holds it
        return age > retention_seconds

    def live_runs(self) -> list[str]:
        """Runs whose writer still holds the lock: never pruned, reported instead."""
        runs = {segment_identity(path)[0] for path in self.spool_files()}
        return sorted(run for run in runs if not self.closed(run) and self.writer_alive(run))

    def prune(self, now: float | None = None,
              retention_seconds: int = POLICY.observation_retention_seconds) -> dict:
        """Directory-wide retention for finished runs: reclaim what is acknowledged, drop stale leftovers.

        The per-run byte limit bounds live producers; this bounds what finished producers leave
        behind (segments, ack files, closed markers, health records, fully acknowledged pending
        alert files). Unacknowledged segments of a finished run are never deleted here; the
        collector consumes them first (a truncated tail of a finished run is finalized there).
        """
        counts = {"runs": 0, "segments": 0, "files": 0, "skipped": 0}
        moment = time.time() if now is None else now
        for run in sorted(self.known_runs()):
            guard = lifecycle_lock(self.root)
            try:
                guard.acquire(timeout=LIFECYCLE_TIMEOUT)
            except (Timeout, OSError):
                counts["skipped"] += 1  # a writer is registering or finishing: decide this run next time
                continue
            try:
                self._prune_run(run, moment, retention_seconds, counts)
            finally:
                guard.release()
        return counts

    def _prune_run(self, run: str, moment: float, retention_seconds: int, counts: dict) -> None:
        """Decide and delete for one run while holding the lifecycle lock: the finish check and every
        file change it justifies are one step from a registering writer's point of view."""
        if not self.run_finished(run, moment, retention_seconds):
            return
        segments = [path for path in self.spool_files() if segment_identity(path)[0] == run]
        remaining = []
        for path in segments:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if read_acknowledged(path) >= size:
                os.unlink(path)
                counts["segments"] += 1
                try:
                    os.unlink(path.with_suffix(".ack"))
                except FileNotFoundError:
                    pass
            else:
                remaining.append(path)
        if remaining:
            return  # still holds unacknowledged records; the collector must consume them first
        counts["runs"] += 1
        for leftover in (self.root / "spool" / (run + ".closed"), self.root / "health" / (run + ".json")):
            try:
                os.unlink(leftover)
                counts["files"] += 1
            except FileNotFoundError:
                pass
        counts["files"] += self._remove_lock_file(run)
        if not self.read_pending_alerts().get(run):
            for path in (self.root / "pending-alerts").glob(run + "*.json") if (self.root / "pending-alerts").is_dir() else []:
                try:
                    os.unlink(path)
                    counts["files"] += 1
                except FileNotFoundError:
                    pass

    def _remove_lock_file(self, process_run_id: str) -> int:
        """Unlink a finished run's lock file only while holding its lock.

        Deleting a lock file that a live writer holds would let a second writer lock a different
        inode for the same run, so the file is removed under the lock and never otherwise; a writer
        that appears between the finish check and this acquire keeps its file. Returns files removed.
        """
        path = run_lock_path(self.root, process_run_id)
        if not path.exists():
            return 0
        probe = FileLock(str(path), is_singleton=False)
        try:
            probe.acquire(timeout=0)
        except (Timeout, OSError):
            return 0  # held by a live writer (or unprovable): leave it
        removed = 0
        try:
            os.unlink(path)  # POSIX: the held inode goes away with the directory entry
            removed = 1
        except OSError:
            pass  # Windows keeps an open file in place; filelock unlinks it on release below
        finally:
            try:
                probe.release()
            except OSError:
                pass
        if removed == 0 and not path.exists():
            removed = 1
        return removed

    def total_bytes(self) -> int:
        total = 0
        for path in self.root.rglob("*") if self.root.is_dir() else []:
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
        return total

    def read(self, path: Path, offset: int = 0):
        return read_records(path, offset)

    def acknowledged(self, path: Path) -> int:
        return read_acknowledged(path)

    def acknowledge(self, path: Path, offset: int, consumed: int) -> None:
        atomic_write(path.with_suffix(".ack"), canonical({"offset": offset, "consumed": consumed,
                                                          "updated_at": utcnow()}) + "\n")

    def closed(self, process_run_id: str) -> bool:
        return (self.root / "spool" / (process_run_id + ".closed")).is_file()

    def reclaimable(self, path: Path) -> bool:
        """Fully acknowledged and no longer the writer's current segment (rotated past, or run closed)."""
        identity = segment_identity(path)
        if identity is None:
            return False
        run, number = identity
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if read_acknowledged(path) < size:
            return False
        later = any(segment_identity(other) == (run, number + 1) or
                    (segment_identity(other) or (None, -1))[1] > number
                    for other in self.spool_files() if other != path and segment_identity(other)
                    and segment_identity(other)[0] == run)
        # A rotated-past segment is sealed. The last segment is reclaimable only with proof that
        # nobody can still append to it: the closed marker, or no live writer holding the run lock.
        return later or self.closed(run) or not self.writer_alive(run)

    def reclaim(self, path: Path) -> bool:
        """Delete a reclaimable segment; the check and the unlink are one step under the lifecycle
        lock, so a writer registering in between cannot lose its active file."""
        guard = lifecycle_lock(self.root)
        try:
            guard.acquire(timeout=LIFECYCLE_TIMEOUT)
        except (Timeout, OSError):
            return False  # a writer is registering or finishing: reclaim next time
        try:
            if not self.reclaimable(path):
                return False
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            try:
                os.unlink(path.with_suffix(".ack"))
            except FileNotFoundError:
                pass
            return True
        finally:
            guard.release()

    def unacknowledged_bytes(self) -> int:
        total = 0
        for path in self.spool_files():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            total += max(0, size - min(read_acknowledged(path), size))
        return total

    # ---- health ---------------------------------------------------------------------------------
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

    # ---- pending alerts (survive a process restart) --------------------------------------------
    # Ownership: only the origin process rewrites `<origin>.json`. A process that replays another
    # origin's debt writes its own `<origin>.acked.<replayer>.json` with the event ids it committed;
    # readers subtract every ack file from the origin list, so a live origin adding new alerts and a
    # replayer acknowledging old ones never clobber each other.
    def _pending_path(self, process_run_id: str) -> Path:
        return self.root / "pending-alerts" / (process_run_id + ".json")

    def acknowledged_alerts(self, origin: str) -> set[str]:
        directory = self.root / "pending-alerts"
        acked: set[str] = set()
        for path in directory.glob(origin + ".acked.*.json") if directory.is_dir() else []:
            try:
                value = json.loads(path.read_text("utf-8"))
            except (ValueError, OSError):
                continue
            if isinstance(value, list):
                acked.update(item for item in value if type(item) is str)
        return acked

    def write_pending_alerts(self, process_run_id: str, records: list[dict]) -> None:
        """Origin-only write of the origin's own list; already acknowledged ids are dropped."""
        acked = self.acknowledged_alerts(process_run_id)
        records = [row for row in records if row.get("event_id") not in acked]
        path = self._pending_path(process_run_id)
        if not records:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            return
        atomic_write(path, canonical(records) + "\n")

    def acknowledge_pending_alerts(self, origin: str, event_ids, replayer: str) -> None:
        """Replayer-owned, append-only acknowledgement of committed ids for a foreign origin."""
        path = self.root / "pending-alerts" / f"{origin}.acked.{replayer}.json"
        try:
            existing = json.loads(path.read_text("utf-8"))
            if not isinstance(existing, list):
                existing = []
        except (FileNotFoundError, ValueError, OSError):
            existing = []
        merged = sorted(set(item for item in existing if type(item) is str) | set(event_ids))
        atomic_write(path, canonical(merged) + "\n")

    def read_pending_alerts(self) -> dict[str, list[dict]]:
        """Every origin's still-unacknowledged pending alerts."""
        directory = self.root / "pending-alerts"
        found = {}
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            if ".acked." in path.name:
                continue
            try:
                value = json.loads(path.read_text("utf-8"))
            except (ValueError, OSError):
                continue
            if isinstance(value, list) and all(isinstance(row, dict) for row in value):
                acked = self.acknowledged_alerts(path.stem)
                rows = [row for row in value if row.get("event_id") not in acked]
                if rows:
                    found[path.stem] = rows
        return found

    # ---- termination evidence -------------------------------------------------------------------
    def record_termination(self, record_id: str, record: dict) -> Path:
        """Create-only and atomic: a temporary file is replaced onto the name, never a partial write."""
        require(RECORD_ID.fullmatch(record_id) is not None, "Invalid termination record id")
        path = self.root / "terminations" / (record_id + ".json")
        if path.exists():
            raise FileExistsError(str(path))
        atomic_write(path, canonical(record) + "\n")
        return path

    def pending_terminations(self, task_id: str | None = None) -> list[dict]:
        """Pending records; an unreadable file is reported (and blocks) rather than ignored."""
        directory = self.root / "terminations"
        rows = []
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            try:
                value = json.loads(path.read_text("utf-8"))
                require(isinstance(value, dict) and type(value.get("record_id")) is str, "Invalid termination record")
            except (ValueError, OSError, ContractError):
                value = {"record_id": path.stem, "unreadable": True, "task_id": None,
                         "status": "pending_reconciliation"}
            if task_id is None or value.get("task_id") == task_id or value.get("unreadable"):
                rows.append(value)
        return rows

    def resolve_termination(self, record_id: str, resolution: dict) -> dict:
        """Local finalize after the sink committed: write the resolved copy, then remove the pending file."""
        require(RECORD_ID.fullmatch(record_id) is not None, "Invalid termination record id")
        path = self.root / "terminations" / (record_id + ".json")
        target = self.root / "terminations" / "resolved" / (record_id + ".json")
        if not path.is_file():
            if target.is_file():
                return json.loads(target.read_text("utf-8"))
            raise ContractError("Unknown termination record")
        try:
            record = json.loads(path.read_text("utf-8"))
        except (ValueError, OSError):
            record = {"record_id": record_id, "unreadable": True}
        resolved = {**record, "status": "resolved", "resolution": resolution}
        atomic_write(target, canonical(resolved) + "\n")
        os.unlink(path)
        return resolved
