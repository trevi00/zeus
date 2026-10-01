"""One bounded collector scan under the single-instance lock.

Purpose: tie the lock, the ledger and the S1 reader together. Layer: tooling. Owns: DESIGN §3.1 single collector,
scan metadata (`last_scan_success`, duration, `live_since`). Does-not-own: reading details (s1_routine), exposition
(render), serving (W1b `serve`).
Implements: ACCEPTANCE A15 (fault hook), A18 (lock before the ledger is opened).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from .config import TaskClassRegistry
from .ledger import collector_lock, open_ledger
from .s1_routine import MAX_READ_BYTES, Scan, scan_routine


def scan_once(data_dir: Path, source_root: Path, *, now: int, registry: TaskClassRegistry | None = None,
              monotonic: Callable[[], float] = time.monotonic, before_commit: Callable[[], None] | None = None,
              max_read_bytes: int = MAX_READ_BYTES) -> None:
    """One bounded scan. Raises CollectorBusy (CLI exit 75) when another instance holds `ledger.lock`."""
    with collector_lock(data_dir):
        ledger = open_ledger(data_dir)
        try:
            ledger.before_commit = before_commit
            started = monotonic()
            with ledger.transaction():
                if ledger.meta("live_since") is None:
                    ledger.set_meta("live_since", now)  # DESIGN §3.9 (backfill itself is W1b)
            scan_routine(Scan(ledger, Path(source_root), now, registry or TaskClassRegistry(), max_read_bytes))
            ledger.before_commit = None
            with ledger.transaction():
                ledger.set_meta("last_scan_success", now)
                ledger.set_meta("scan_duration_seconds", round(monotonic() - started, 6))
        finally:
            ledger.close()
