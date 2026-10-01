"""SQLite ledger (WAL), schema migrations and the single-collector lock.

Purpose: persistence for the collector. Layer: tooling. Owns: the DESIGN §4 tables (W1a subset: S1 and the
core), `schema_meta` migrations, the explicit-transaction helper with the pre-COMMIT fault hook (A15), the 0600
file creation and the `ledger.lock` flock (A18). Does-not-own: any reading of source files, any metric text.
Implements: DESIGN §3.1, §3.6 (append-only triggers), §4; ACCEPTANCE A15, A18, A24 (ids/enums/numbers only,
never prompt or result text).
W1b adds (as migration 2): `codex_points`, `rate_observations`, `backfill` bookkeeping for S2/S3.
"""

from __future__ import annotations

import fcntl
import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

EXIT_BUSY = 75  # EX_TEMPFAIL: a second collector instance while the lock is held (A18)
LEDGER_NAME = "ledger.sqlite3"
LOCK_NAME = "ledger.lock"


class LedgerError(RuntimeError):
    pass


class CollectorBusy(LedgerError):
    pass


_APPEND_ONLY = ("contributions", "cost_contributions", "corrections", "unknown_shares", "advisor_consultations",
                "task_token_snapshots")

_MIGRATION_1 = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE stream_aliases(
  alias_id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, dev INTEGER, ino INTEGER, head_sha256 TEXT,
  source TEXT NOT NULL,
  binding TEXT NOT NULL CHECK (binding IN ('canonical','alias_pending','bound','unbound')),
  invocation_id TEXT,
  provenance TEXT NOT NULL CHECK (provenance IN
    ('dispatch_record','run_metadata','credential_receipt','codex_run_script','none')),
  first_seen INTEGER NOT NULL, bound_at INTEGER);
CREATE INDEX stream_aliases_path ON stream_aliases(path);
-- read_state: where each path was read up to. A read identity change (inode, shrink, first-line hash) starts a
-- new alias row and re-reads from 0; accounting keys absorb the replay (DESIGN §3.1).
CREATE TABLE read_state(
  path TEXT PRIMARY KEY, alias_id INTEGER NOT NULL REFERENCES stream_aliases(alias_id),
  dev INTEGER, ino INTEGER, head_sha256 TEXT, offset INTEGER NOT NULL, closed_size INTEGER);
CREATE TABLE stream_settlements(
  alias_id INTEGER PRIMARY KEY REFERENCES stream_aliases(alias_id),
  prefix_end_offset INTEGER NOT NULL, tail_bytes INTEGER NOT NULL, tail_sha256 TEXT NOT NULL,
  settled_at INTEGER NOT NULL);
CREATE TABLE alias_facts(
  alias_id INTEGER NOT NULL REFERENCES stream_aliases(alias_id), session_id TEXT NOT NULL, uuid TEXT NOT NULL,
  PRIMARY KEY (alias_id, session_id, uuid));
-- A complete line that is not valid JSON or has the wrong shape; the key keeps replays from counting twice.
CREATE TABLE malformed_lines(
  path TEXT NOT NULL, line_offset INTEGER NOT NULL, line_sha256 TEXT NOT NULL, source TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('line','tail')), invocation_id TEXT,
  PRIMARY KEY (path, line_offset, line_sha256));
CREATE TABLE invocations(
  id TEXT PRIMARY KEY, source TEXT NOT NULL, provider TEXT NOT NULL, session_or_thread TEXT,
  task_id TEXT, attempt INTEGER, mode TEXT CHECK (mode IN ('fresh','resumed')),
  predecessor_id TEXT, predecessor_state TEXT NOT NULL DEFAULT 'none'
    CHECK (predecessor_state IN ('none','proven','missing','unproven')),
  requested_model_raw TEXT, executor_model_raw TEXT, executor_model TEXT, advisor_model TEXT, cli_version TEXT,
  lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN
    ('open','awaiting_predecessor','terminal_observed','terminal_unavailable','finalized')),
  outcome TEXT, unknown_reason TEXT, terminal_evidence TEXT CHECK (terminal_evidence IN
    ('record_row','horizon') OR terminal_evidence IS NULL),
  started_at INTEGER NOT NULL, timeout_seconds INTEGER, finalized_at INTEGER, backfill INTEGER NOT NULL DEFAULT 0,
  task_class TEXT NOT NULL, receipt_ok INTEGER, worker_status TEXT, advisor_state TEXT);
CREATE INDEX invocations_task ON invocations(task_id);
CREATE TABLE results(
  session_id TEXT NOT NULL, uuid TEXT NOT NULL, invocation_id TEXT NOT NULL REFERENCES invocations(id),
  seq INTEGER NOT NULL, result_index INTEGER, is_error INTEGER NOT NULL, subtype TEXT,
  zeroed INTEGER NOT NULL, usage_ok INTEGER NOT NULL, models_ok INTEGER NOT NULL,
  nested INTEGER NOT NULL, -- 0 explicit zero/zero counters, 1 nested agents reported, 2 unknown (F2)
  input INTEGER, output INTEGER, cache_read INTEGER, cache_write INTEGER,
  PRIMARY KEY (session_id, uuid));
CREATE INDEX results_invocation ON results(invocation_id, seq);
CREATE TABLE result_models(
  session_id TEXT NOT NULL, uuid TEXT NOT NULL, model TEXT NOT NULL,
  input INTEGER NOT NULL, output INTEGER NOT NULL, cache_read INTEGER NOT NULL, cache_write INTEGER NOT NULL,
  cost_usd REAL NOT NULL, PRIMARY KEY (session_id, uuid, model));
CREATE TABLE cumulative(
  invocation_id TEXT NOT NULL REFERENCES invocations(id), model TEXT NOT NULL,
  input INTEGER NOT NULL, output INTEGER NOT NULL, cache_read INTEGER NOT NULL, cache_write INTEGER NOT NULL,
  cost_usd REAL NOT NULL, PRIMARY KEY (invocation_id, model));
CREATE TABLE contributions(
  id TEXT PRIMARY KEY, invocation_id TEXT NOT NULL REFERENCES invocations(id),
  kind TEXT NOT NULL CHECK (kind IN ('main_result','tree_remainder','codex_delta','codex_interval')),
  provider TEXT NOT NULL, model TEXT NOT NULL, role TEXT NOT NULL, source TEXT NOT NULL,
  task_class TEXT NOT NULL, token_type TEXT NOT NULL, value INTEGER NOT NULL CHECK (value > 0),
  published_at INTEGER NOT NULL, backfill INTEGER NOT NULL DEFAULT 0);
CREATE INDEX contributions_invocation ON contributions(invocation_id);
CREATE TABLE cost_contributions(
  id TEXT PRIMARY KEY, invocation_id TEXT NOT NULL REFERENCES invocations(id), provider TEXT NOT NULL,
  model TEXT NOT NULL, source TEXT NOT NULL, task_class TEXT NOT NULL, usd REAL NOT NULL CHECK (usd > 0),
  published_at INTEGER NOT NULL, backfill INTEGER NOT NULL DEFAULT 0);
CREATE TABLE unknown_shares(
  invocation_id TEXT NOT NULL REFERENCES invocations(id), model TEXT NOT NULL, provider TEXT NOT NULL,
  reason TEXT NOT NULL, PRIMARY KEY (invocation_id, model));
CREATE TABLE advisor_consultations(
  session_id TEXT NOT NULL, message_id TEXT NOT NULL, block_index INTEGER NOT NULL,
  invocation_id TEXT NOT NULL REFERENCES invocations(id), PRIMARY KEY (session_id, message_id, block_index));
CREATE TABLE model_flags(
  invocation_id TEXT NOT NULL REFERENCES invocations(id), kind TEXT NOT NULL CHECK (kind IN
    ('unrecognized','mismatch')), model_raw TEXT NOT NULL, PRIMARY KEY (invocation_id, kind, model_raw));
CREATE TABLE corrections(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, dedupe_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('late_point','late_predecessor','late_terminal','late_tail',
                                      'duplicate_after_publish')),
  invocation_id TEXT, detail_enum TEXT NOT NULL, recorded_at INTEGER NOT NULL);
CREATE TABLE tasks(
  task_id TEXT PRIMARY KEY, task_class TEXT NOT NULL, outcome TEXT CHECK (outcome IN ('accepted','abandoned')
    OR outcome IS NULL), attempts INTEGER NOT NULL DEFAULT 0, review_rounds INTEGER,
  first_dispatch_at INTEGER, closed_at INTEGER, first_pass INTEGER, unknown_invocations INTEGER);
CREATE TABLE task_token_snapshots(
  task_id TEXT NOT NULL REFERENCES tasks(task_id), role TEXT NOT NULL, token_type TEXT NOT NULL,
  value INTEGER NOT NULL, PRIMARY KEY (task_id, role, token_type));
"""

# Ordered migrations: (version, script). `schema_meta.version` records the applied level.
# W1b (migration 2). `terminal_kind` names the evidence behind `terminal_evidence='record_row'` for sources that have no
# record row (run metadata, a Codex turn line), because the migration-1 CHECK cannot be widened in place.
_MIGRATION_2 = """
ALTER TABLE invocations ADD COLUMN terminal_kind TEXT;
CREATE TABLE stream_clock(alias_id INTEGER PRIMARY KEY REFERENCES stream_aliases(alias_id), last_ts REAL);
CREATE TABLE alias_usage(
  alias_id INTEGER NOT NULL REFERENCES stream_aliases(alias_id), session_id TEXT NOT NULL, uuid TEXT NOT NULL,
  model TEXT NOT NULL, input INTEGER NOT NULL, output INTEGER NOT NULL, cache_read INTEGER NOT NULL,
  cache_write INTEGER NOT NULL, PRIMARY KEY (alias_id, session_id, uuid));
CREATE TABLE alias_codex_points(
  alias_id INTEGER NOT NULL REFERENCES stream_aliases(alias_id), thread_id TEXT NOT NULL,
  input_tokens INTEGER NOT NULL, cached INTEGER NOT NULL, cache_write INTEGER NOT NULL, output INTEGER NOT NULL,
  reasoning INTEGER NOT NULL, PRIMARY KEY (alias_id, thread_id, input_tokens, cached, cache_write, output, reasoning));
ALTER TABLE stream_aliases ADD COLUMN unbound_published INTEGER NOT NULL DEFAULT 0;
CREATE TABLE unbound_contributions(
  id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL, role TEXT NOT NULL, source TEXT NOT NULL,
  task_class TEXT NOT NULL, token_type TEXT NOT NULL, value INTEGER NOT NULL CHECK (value > 0),
  published_at INTEGER NOT NULL, backfill INTEGER NOT NULL DEFAULT 0);
CREATE TABLE reasoning_contributions(
  id TEXT PRIMARY KEY, invocation_id TEXT REFERENCES invocations(id), provider TEXT NOT NULL, model TEXT NOT NULL,
  role TEXT NOT NULL, source TEXT NOT NULL, task_class TEXT NOT NULL, value INTEGER NOT NULL CHECK (value > 0),
  published_at INTEGER NOT NULL, backfill INTEGER NOT NULL DEFAULT 0);
-- cache_write = -1 when the point lacks `cache_write_input_tokens` (C-W1-3: unknown, never 0).
CREATE TABLE codex_runs(
  invocation_id TEXT PRIMARY KEY REFERENCES invocations(id), thread_id TEXT, argv_mode TEXT NOT NULL
    CHECK (argv_mode IN ('fresh','resume','unknown')), turn TEXT CHECK (turn IN ('completed','failed') OR turn IS NULL),
  usage_state TEXT NOT NULL DEFAULT 'none' CHECK (usage_state IN ('none','ok','bad')),
  input_tokens INTEGER, cached INTEGER, cache_write INTEGER, output INTEGER, reasoning INTEGER, eof INTEGER NOT NULL DEFAULT 0);
CREATE TABLE codex_points(
  point_id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, input_tokens INTEGER NOT NULL,
  cached INTEGER NOT NULL, cache_write INTEGER NOT NULL, output INTEGER NOT NULL, reasoning INTEGER NOT NULL,
  invocation_id TEXT, alias_id INTEGER, published INTEGER NOT NULL DEFAULT 0, prev_point_id INTEGER,
  UNIQUE (thread_id, input_tokens, cached, cache_write, output, reasoning));
CREATE INDEX codex_points_thread ON codex_points(thread_id, input_tokens, output);
CREATE TABLE rate_observations(
  session_id TEXT NOT NULL, event_key TEXT NOT NULL, window TEXT NOT NULL CHECK (window IN ('five_hour','seven_day')),
  provider TEXT NOT NULL, slot TEXT NOT NULL, marker TEXT NOT NULL CHECK (marker IN ('value','missing','invalid')),
  utilization REAL, resets_at INTEGER, observed_at REAL, provenance TEXT NOT NULL, stream TEXT NOT NULL,
  line_index INTEGER NOT NULL, PRIMARY KEY (session_id, event_key, window));
CREATE INDEX rate_observations_slot ON rate_observations(provider, slot, window, observed_at);
CREATE TABLE s9_sources(name TEXT PRIMARY KEY, ok INTEGER NOT NULL);
ALTER TABLE tasks ADD COLUMN backfill INTEGER NOT NULL DEFAULT 0;
"""

# W1c (migration 3, F1): the parse state of an UNNAMED read alias that must survive between scans and restarts: the
# Claude `init` session/model and the Codex thread. One row per read alias, written in the same transaction as the
# alias's offset; a new read identity is a new alias row and therefore starts without it (DESIGN §3.1).
_MIGRATION_3 = """
CREATE TABLE alias_state(
  alias_id INTEGER PRIMARY KEY REFERENCES stream_aliases(alias_id), session_id TEXT, model TEXT, thread_id TEXT);
"""

MIGRATIONS: tuple[tuple[int, str], ...] = ((1, _MIGRATION_1), (2, _MIGRATION_2), (3, _MIGRATION_3))
_APPEND_ONLY_BY_MIGRATION = {1: _APPEND_ONLY, 2: ("unbound_contributions", "reasoning_contributions"), 3: ()}
SCHEMA_VERSION = MIGRATIONS[-1][0]


def _append_only_triggers(tables: tuple[str, ...] = _APPEND_ONLY) -> str:
    parts = []
    for table in tables:
        for verb in ("UPDATE", "DELETE"):
            parts.append(f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                         f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;")
    return "\n".join(parts)


class Ledger:
    def __init__(self, conn: sqlite3.Connection, path: Path):
        self.conn = conn
        self.path = path
        self.before_commit: Callable[[], None] | None = None  # A15: raise here to simulate a crash

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One transaction per file batch: offsets, parsed facts and contributions commit together."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
            if self.before_commit is not None:
                self.before_commit()
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()

    # -- meta -----------------------------------------------------------------
    def meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: object) -> None:
        self.conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, str(value)))


def _create_private(path: Path) -> None:
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    os.close(fd)


def open_ledger(data_dir: Path, *, create: bool = True) -> Ledger:
    """Open (and migrate) `data_dir/ledger.sqlite3`. The file is created 0600. A ledger written by a newer
    schema is refused, never downgraded."""
    data_dir = Path(data_dir)
    path = data_dir / LEDGER_NAME
    if not path.exists():
        if not create:
            raise LedgerError("no ledger at the data directory")
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _create_private(path)
    conn = sqlite3.connect(path, isolation_level=None, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    ledger = Ledger(conn, path)
    if create:
        _migrate(ledger)
    else:
        _require_current(ledger)
    return ledger


def _version(conn: sqlite3.Connection) -> int:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'").fetchone()
    if not exists:
        return 0
    row = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
    return int(row[0]) if row else 0


def _require_current(ledger: Ledger) -> None:
    version = _version(ledger.conn)
    if version != SCHEMA_VERSION:
        ledger.close()
        raise LedgerError(f"ledger schema {version} != supported {SCHEMA_VERSION}")


def _migrate(ledger: Ledger) -> None:
    conn = ledger.conn
    version = _version(conn)
    if version > SCHEMA_VERSION:
        conn.close()
        raise LedgerError(f"ledger schema {version} is newer than the supported {SCHEMA_VERSION}")
    for target, script in MIGRATIONS:
        if target <= version:
            continue
        with ledger.transaction():
            conn.execute("CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for statement in script.split(";\n"):
                if statement.strip():
                    conn.execute(statement)
            for statement in _append_only_triggers(_APPEND_ONLY_BY_MIGRATION[target]).split("\n"):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_meta(key,value) VALUES('version',?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(target),))


@contextmanager
def collector_lock(data_dir: Path) -> Iterator[None]:
    """A18: one collector per data directory. The lock is taken before the ledger is opened, so a refused second
    instance leaves the ledger untouched (CollectorBusy -> exit 75)."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(data_dir / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CollectorBusy("another collector holds ledger.lock") from None
        yield
    finally:
        os.close(fd)
