"""Deferred sources and the S9 freshness read (DESIGN §3.10, §8).

Purpose: (1) read `monitoring.json` read-only for `collected_at` and `sources.*.status` (freshness only); (2) count
the rows of a configured S4/OTel-shaped file WITHOUT ingesting them. Layer: tooling. Owns: §8 now-contract and
§3.10 phase-1 contract. Does-not-own: any write under the S9 directory, any token ingestion from these rows.
Implements: ACCEPTANCE A33 (phase 1: `deferred_source_rows`, counters equal receipt-only), §5 S9 health gauges.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .ledger import Ledger
from .s1_routine import open_regular
from .windows import parse_ts

MONITORING_NAME = "monitoring.json"
MAX_MONITORING_BYTES = 8 * 1024 * 1024
MAX_S9_SOURCES = 16
SOURCE_NAME = re.compile(r"^[a-z0-9_.-]{1,48}$")


def read_s9(ledger: Ledger, s9_dir: Path | None, now: int) -> None:
    """Store the S9 snapshot's freshness. Never writes under `s9_dir` and never takes its lock. An unreadable or
    invalid snapshot clears the stored values (absent, never 0)."""
    conn = ledger.conn
    conn.execute("DELETE FROM s9_sources")
    conn.execute("DELETE FROM meta WHERE key='s9.collected_at'")
    if s9_dir is None:
        return
    try:
        with open_regular(Path(s9_dir) / MONITORING_NAME) as handle:
            raw = handle.read(MAX_MONITORING_BYTES + 1)
        data = json.loads(raw) if len(raw) <= MAX_MONITORING_BYTES else None
    except (OSError, ValueError, RecursionError):
        return
    if not isinstance(data, dict):
        return
    collected = parse_ts(data.get("collected_at"))
    if collected is not None:
        ledger.set_meta("s9.collected_at", collected)
    sources = data.get("sources")
    if isinstance(sources, dict):
        for name in sorted(sources)[:MAX_S9_SOURCES]:
            entry = sources[name]
            label = name if isinstance(name, str) and SOURCE_NAME.match(name) else "other"
            status = entry.get("status") if isinstance(entry, dict) else None
            conn.execute("INSERT INTO s9_sources(name,ok) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET "
                         "ok=MIN(ok,excluded.ok)", (label, int(status == "ok")))


def read_deferred_rows(ledger: Ledger, path: Path | None) -> None:
    """A33: count complete JSON-object lines of a configured deferred-source file; ingest nothing from them."""
    if path is None:
        ledger.conn.execute("DELETE FROM meta WHERE key='deferred_source_rows'")
        return
    rows = 0
    try:
        with open_regular(Path(path)) as handle:
            for line in handle.read(MAX_MONITORING_BYTES).split(b"\n")[:-1]:
                try:
                    rows += isinstance(json.loads(line), dict)
                except (ValueError, RecursionError):
                    continue
    except OSError:
        rows = 0
    ledger.set_meta("deferred_source_rows", rows)
