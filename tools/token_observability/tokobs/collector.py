"""One bounded collector scan under the single-instance lock.

Purpose: tie the lock, the ledger and the source readers together. Layer: tooling. Owns: DESIGN §3.1 single
collector, scan metadata (`last_scan_success`, duration, `live_since`, ingest lag), the order S1 -> S2 -> S3 ->
aliases, the S9 freshness read. Does-not-own: reading details (s1_routine, s2_streams, s3_codex, aliases),
exposition (render), serving (serve).
Implements: ACCEPTANCE A15 (fault hook), A18 (lock before the ledger is opened), A32 (live_since, ingest lag),
A33 (deferred rows).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from .aliases import scan_aliases
from .backfill import ensure_live_since, record_ingest_lag
from .config import TaskClassRegistry
from .deferred import read_deferred_rows, read_s9
from .late import link_late_predecessors
from .ledger import Ledger, collector_lock, open_ledger
from .s1_routine import MAX_READ_BYTES, Scan, scan_routine
from .s2_streams import scan_s2
from .s3_codex import scan_codex
from .vocab import codex_idle_seconds


def scan_locked(ledger: Ledger, source_root: Path, *, now: int, registry: TaskClassRegistry | None = None,
                monotonic: Callable[[], float] = time.monotonic, before_commit: Callable[[], None] | None = None,
                max_read_bytes: int = MAX_READ_BYTES, live_since: int | None = None, s9_dir: Path | None = None,
                deferred_file: Path | None = None) -> None:
    """One scan on an open ledger; the caller holds `ledger.lock`."""
    ledger.before_commit = before_commit
    started = monotonic()
    with ledger.transaction():
        stored = ensure_live_since(ledger, now, live_since)
        record_ingest_lag(ledger, now)
    scan = Scan(ledger, Path(source_root), now, registry or TaskClassRegistry(), max_read_bytes, stored,
                codex_idle_seconds())
    aliases = scan_routine(scan)
    claude_aliases = aliases + scan_s2(scan)
    codex_aliases = scan_codex(scan)
    with ledger.transaction():
        link_late_predecessors(scan)
    scan_aliases(scan, claude_aliases, codex_aliases)
    ledger.before_commit = None
    with ledger.transaction():
        read_s9(ledger, s9_dir, now)
        read_deferred_rows(ledger, deferred_file)
        ledger.set_meta("last_scan_success", now)
        ledger.set_meta("scan_duration_seconds", round(monotonic() - started, 6))


def scan_once(data_dir: Path, source_root: Path, *, now: int, registry: TaskClassRegistry | None = None,
              monotonic: Callable[[], float] = time.monotonic, before_commit: Callable[[], None] | None = None,
              max_read_bytes: int = MAX_READ_BYTES, live_since: int | None = None, s9_dir: Path | None = None,
              deferred_file: Path | None = None) -> None:
    """One bounded scan. Raises CollectorBusy (CLI exit 75) when another instance holds `ledger.lock`."""
    with collector_lock(data_dir):
        ledger = open_ledger(data_dir)
        try:
            scan_locked(ledger, source_root, now=now, registry=registry, monotonic=monotonic,
                        before_commit=before_commit, max_read_bytes=max_read_bytes, live_since=live_since,
                        s9_dir=s9_dir, deferred_file=deferred_file)
        finally:
            ledger.close()
