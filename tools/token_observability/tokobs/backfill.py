"""Backfill versus live classification and ingest lag (DESIGN §3.9, C-W1-7).

Purpose: decide, once at invocation creation, whether an invocation is history (`backfill=1`, excluded from
counters) or live, and compute the ingest lag. Layer: tooling. Owns: §3.9. Does-not-own: the counters themselves.
Implements: ACCEPTANCE A32.

`live_since` belongs to the persistent collector (`serve` stores it at its first start, never reset) or is passed
explicitly; a one-shot `scan` without it classifies nothing as backfill. The classification is fixed at creation
because contributions publish at result time with the invocation's flag.
"""

from __future__ import annotations

from .ledger import Ledger


def stream_is_history(live_since: int | None, last_written: float | None, *, terminal_at: float | None,
                      horizon_seconds: int) -> bool:
    """S2/S3 (F5, REVIEW-W1-r2): terminal PRESENCE is not proof of terminal AGE. A stream is history only with
    (a) a source-supported terminal timestamp (`terminal_at`, e.g. the lane metadata's own `finished_at`) before
    `live_since`, or (b) its unavailability horizon already satisfied AT `live_since` (idle measure, §3.1: the last
    write is older than the horizon). The stream's mtime is never a terminal time and a different file's old mtime
    never proves when a completion was written: with no terminal timestamp and an unexpired horizon the stream stays
    live (disclosed limit, §3.9). Anything written at or after `live_since` is live."""
    if live_since is None or last_written is None or last_written >= live_since:
        return False
    if terminal_at is not None:
        return terminal_at < live_since
    return live_since - last_written > horizon_seconds


def attempt_is_history(live_since: int | None, started_at: int, terminal_at: int | None, horizon_seconds: int) -> bool:
    """S1: terminal evidence older than `live_since`, or no terminal and the unavailability horizon already past
    at `live_since`. An attempt still in flight at the first start is live."""
    if live_since is None:
        return False
    end = terminal_at if terminal_at is not None else started_at + horizon_seconds
    return end < live_since


def ensure_live_since(ledger: Ledger, now: int, explicit: int | None) -> int | None:
    """Store `live_since` once. An explicit value wins on first store; a stored value is never reset."""
    stored = ledger.meta("live_since")
    if stored is not None:
        return int(stored)
    if explicit is None:
        return None
    ledger.set_meta("live_since", explicit)
    return explicit


def record_ingest_lag(ledger: Ledger, now: int) -> None:
    """A32: the unobserved window at the start of a scan = now - the previous successful scan."""
    previous = ledger.meta("last_scan_success")
    ledger.set_meta("ingest_lag_seconds", max(now - int(previous), 0) if previous is not None else 0)
