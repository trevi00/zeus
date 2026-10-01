"""Provider rate-window observations: markers ordered before validity (DESIGN §3.8, round-2 R4).

Purpose: turn `rate_limit_event` lines into one marker per window and select, per (provider, slot, window), the
newest timestamped marker; derive the current/stale/expired/unavailable state at render time. Layer: tooling.
Owns: §3.8 validity, bracketed observation time, marker selection and state. Does-not-own: reading streams
(the stream readers call `observe`), exposition text (render) or any join with token counts.
Implements: ACCEPTANCE A50, A51, A52, A53.

Observation time is the `timestamp` of the nearest PRECEDING timestamped line of the same stream; the event has
none of its own. The file's mtime, latest append or ingest time is never used.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from datetime import datetime, timezone

PROVIDER = "anthropic"
WINDOWS = ("five_hour", "seven_day")
SLOTS = ("primary", "secondary", "unknown")
PROVENANCE = "stream_preceding_timestamp"
STALE_SECONDS = 3600  # the credential policy's FRESH_SECONDS (§3.8)
MAX_UTILIZATION = 2.0  # R7: values above 1 are real (1.1 with status `rejected`)
RESET_SPAN_SECONDS = 8 * 86400
STATES = ("current", "stale", "expired", "unavailable")


def parse_ts(value: object) -> float | None:
    """ISO-8601 with optional fraction and `Z`/offset -> epoch seconds (millisecond ordering kept)."""
    if not isinstance(value, str) or not 10 <= len(value) <= 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return round(parsed.timestamp(), 6)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _marker(window: object, observed_at: float | None) -> tuple[str, float | None, int | None]:
    if not isinstance(window, dict):
        return "missing", None, None
    utilization = _number(window.get("utilization"))
    resets = window.get("resetsAt")
    if utilization is None or not 0 <= utilization <= MAX_UTILIZATION:
        return "invalid", None, None
    if isinstance(resets, bool) or not isinstance(resets, int):
        return "invalid", None, None
    if observed_at is not None and abs(resets - observed_at) > RESET_SPAN_SECONDS:
        return "invalid", None, None
    return "value", utilization, resets


def observe(conn: sqlite3.Connection, *, slot: str, stream: str, line_index: int, obj: dict, raw: bytes,
            observed_at: float | None) -> None:
    """Persist one marker per window for one `rate_limit_event` line. Idempotent by (session, event, window)."""
    info = obj.get("rate_limit_info")
    windows = info.get("unifiedWindows") if isinstance(info, dict) else None
    session = obj.get("session_id") if isinstance(obj.get("session_id"), str) else ""
    event = obj.get("uuid") if isinstance(obj.get("uuid"), str) else "sha256:" + hashlib.sha256(raw).hexdigest()
    for name in WINDOWS:
        entry = windows.get(name) if isinstance(windows, dict) else None
        marker, utilization, resets = _marker(entry, observed_at) if entry is not None else ("missing", None, None)
        conn.execute(
            "INSERT OR IGNORE INTO rate_observations(session_id,event_key,window,provider,slot,marker,utilization,"
            "resets_at,observed_at,provenance,stream,line_index) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (session[:96], event[:96], name, PROVIDER, slot, marker, utilization, resets, observed_at, PROVENANCE,
             stream, line_index))


def selected(conn: sqlite3.Connection) -> dict[tuple[str, str], tuple | None]:
    """(slot, window) -> the newest timestamped marker row (marker, utilization, resets_at, observed_at), chosen
    BEFORE validity is considered; None when the slot has only untimed history."""
    out: dict[tuple[str, str], tuple | None] = {}
    for (slot,) in conn.execute("SELECT DISTINCT slot FROM rate_observations ORDER BY slot").fetchall():
        for window in WINDOWS:
            row = conn.execute(
                "SELECT marker,utilization,resets_at,observed_at FROM rate_observations WHERE provider=? AND slot=? "
                "AND window=? AND observed_at IS NOT NULL ORDER BY observed_at DESC, stream DESC, line_index DESC "
                "LIMIT 1", (PROVIDER, slot, window)).fetchone()
            out[(slot, window)] = row
    return out


def state_of(row: tuple | None, now: float) -> str:
    if row is None or row[0] != "value":
        return "unavailable"
    _marker_name, _util, resets, observed = row
    if resets <= now:
        return "expired"
    if now - observed > STALE_SECONDS:
        return "stale"
    return "current"
