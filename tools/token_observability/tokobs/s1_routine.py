"""S1 routine source: dispatch records, per-attempt event streams, lifecycle, identity and settlement.

Purpose: read `routine-runs/<task>/{record.jsonl, events-<k>.jsonl, receipt-<k>.json}` (written by
`A/tools/routine/dispatch.py`) into the ledger. Layer: tooling.
Owns: DESIGN §3.1 (complete-line reading, read identity, bounded chunks), §3.2 (S1 lifecycle row, terminal values,
horizon, torn-tail settlement), §3.3 (canonical `routine:<task>:<k>` IDs, predecessor = attempt k-1, read aliases),
§3.6 (publish at result commit; one finalization), §3.7 (version gate), K1b (receipt facts only), task close.
Does-not-own: S2/S3 sources, rate-window observations (W1b), partition arithmetic (partition.py), write
primitives (publication.py), exposition (render.py).
Implements: ACCEPTANCE A01-A19 (S1 parts), A24, A31, A34-A40, A42, A44, A45, A47 (routine), A48, A58 (routine).

Reading rules in one place: only complete lines are parsed; a torn tail waits while the attempt is open and is
settled once from the complete prefix when terminal evidence or the horizon exists. mtime is never read.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

from .backfill import attempt_is_history
from .config import TaskClassRegistry
from .ledger import Ledger
from .partition import MODEL_USAGE_FIELDS, USAGE_FIELDS, Baseline, ResultFacts, plan_partition
from .publication import (
    finalize_invocation,
    publish_contribution,
    record_correction,
    unbound_published,
)
from .vocab import (
    ADVISOR_STATES,
    EXECUTOR_ROLE,
    RESUME_CUMULATIVE_SINCE,
    TOKEN_TYPES,
    is_model_mismatch,
    normalize_model,
    parse_version,
)
from .windows import observe as observe_rate
from .windows import parse_ts

SOURCE = "routine"
PROVIDER = "anthropic"
START_EVENTS = ("dispatched", "resumed")
TERMINAL_EVENTS = ("finished", "failed", "escalate", "blocked", "timed_out", "interrupted")
KILL_GRACE_SECONDS = 30  # dispatch.py KILL_GRACE_SECONDS
HORIZON_SLACK_SECONDS = 600  # DESIGN §3.2: dispatched.at + timeout + 30 s kill grace + 600 s
FALLBACK_TIMEOUT_SECONDS = 14_400  # a start row without a usable timeout_seconds: the design's LANE_HORIZON bound
MAX_READ_BYTES = 8 * 1024 * 1024  # one bounded chunk per stream per scan (§3.1)
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
EVENTS_NAME = re.compile(r"^events-[A-Za-z0-9._-]+\.jsonl$")
_AT = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
_SAFE = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,64}$")


def open_regular(path: Path):
    """Open `path` read-only as a binary file object. A symlink or a non-regular file is refused (OSError), so a
    planted link inside the allowlisted tree can never make the collector read something else (DESIGN §7, A57)."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def read_json(path: Path) -> dict | None:
    try:
        with open_regular(path) as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
        data = json.loads(raw) if len(raw) <= MAX_JSON_BYTES else None
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def parse_at(value: object) -> int | None:
    if not isinstance(value, str) or not _AT.match(value):
        return None
    try:
        return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None


def safe_token(value: object) -> str | None:
    """Ids and enums only reach the ledger through this gate: bounded charset, never free text."""
    return value if isinstance(value, str) and _SAFE.match(value) else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def invocation_id(task_id: str, attempt: int) -> str:
    return f"routine:{task_id}:{attempt}"


# --------------------------------------------------------------------- record.jsonl


@dataclass
class Attempt:
    number: int
    start: dict
    terminal: dict | None = None
    slot: str = "unknown"  # the `credential_selected` row's selection (§3.8, source-owned link)


@dataclass
class TaskView:
    attempts: dict[int, Attempt] = field(default_factory=dict)
    completed: dict | None = None


def read_record(path: Path) -> list[dict]:
    """Complete lines of record.jsonl that are JSON objects with a string `event`."""
    try:
        with open_regular(path) as handle:
            data = handle.read()
    except OSError:
        return []
    rows = []
    for raw in data.split(b"\n")[:-1]:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("event"), str):
            rows.append(row)
    return rows


def parse_record(rows: list[dict]) -> TaskView:
    view = TaskView()
    for row in rows:
        number = row.get("attempt")
        if row["event"] in START_EVENTS and isinstance(number, int) and not isinstance(number, bool) \
                and number >= 1 and number not in view.attempts:
            view.attempts[number] = Attempt(number, row)
    for row in rows:
        number = row.get("attempt")
        attempt = view.attempts.get(number) if isinstance(number, int) else None
        if row["event"] == "credential_selected" and attempt is not None and attempt.slot == "unknown":
            attempt.slot = row.get("selection") if row.get("selection") in ("primary", "secondary") else "unknown"
        if row["event"] in TERMINAL_EVENTS and attempt is not None and attempt.terminal is None:
            attempt.terminal = row
        elif row["event"] == "completed" and view.completed is None and row.get("outcome") in ("accepted", "abandoned"):
            view.completed = row
    return view


# --------------------------------------------------------------------- context and stream reading


@dataclass
class Scan:
    ledger: Ledger
    source_root: Path
    now: int
    registry: TaskClassRegistry
    max_read_bytes: int = MAX_READ_BYTES
    live_since: int | None = None  # §3.9 / C-W1-7: None = no backfill classification
    codex_idle_seconds: int = 0

    @property
    def conn(self) -> sqlite3.Connection:
        return self.ledger.conn


@dataclass
class StreamState:
    exists: bool
    at_eof: bool
    size: int = 0
    tail: bytes | None = None  # a torn tail, only once the stream is consumed to EOF
    prefix_end: int = 0
    alias_id: int | None = None


def _identity_changed(rs: sqlite3.Row | tuple, st: os.stat_result, head: str | None, size: int) -> bool:
    _alias, dev, ino, stored_head, offset = rs
    if dev != st.st_dev or ino != st.st_ino or size < offset:
        return True
    return stored_head is not None and head is not None and head != stored_head


def _first_line_hash(path: Path) -> str | None:
    with open_regular(path) as handle:
        line = handle.readline()
    return hashlib.sha256(line).hexdigest() if line.endswith(b"\n") else None


def _read_chunk(handle, offset: int, limit: int) -> tuple[bytes, int]:
    handle.seek(offset)
    data = handle.read(limit)
    while b"\n" not in data:
        more = handle.read(limit)
        if not more:
            break
        data += more
    return data, os.fstat(handle.fileno()).st_size


def read_stream(scan: Scan, path: Path, *, source_alias: tuple[str, str | None, str] | None,
                source: str = SOURCE):
    """Open `path` and return (alias_id, offset, complete_bytes, state). `source_alias` is
    (binding, invocation_id, provenance) for a NEW read identity. A changed identity (inode, shrink, first-line
    hash) starts a new alias row and re-reads from 0; accounting keys absorb the replay (DESIGN §3.1)."""
    conn = scan.conn
    try:
        handle = open_regular(path)
    except OSError:
        return None
    with handle:
        st = os.fstat(handle.fileno())
        rs = conn.execute("SELECT rs.alias_id, rs.dev, rs.ino, rs.head_sha256, rs.offset, a.binding, a.invocation_id "
                          "FROM read_state rs JOIN stream_aliases a USING(alias_id) WHERE rs.path=?",
                          (str(path),)).fetchone()
        fresh = rs is None
        if rs is not None:
            head = _first_line_hash(path) if rs[4] > 0 else None
            expected = (source_alias[0], source_alias[1]) if source_alias else (None, None)
            fresh = _identity_changed(rs[:5], st, head, st.st_size) or (rs[5], rs[6]) != expected
        if fresh:
            binding, inv_id, provenance = source_alias
            cursor = conn.execute(
                "INSERT INTO stream_aliases(path,dev,ino,head_sha256,source,binding,invocation_id,provenance,"
                "first_seen) VALUES(?,?,?,?,?,?,?,?,?)",
                (str(path), st.st_dev, st.st_ino, None, source, binding, inv_id, provenance, scan.now))
            alias_id, offset = cursor.lastrowid, 0
            conn.execute(
                "INSERT INTO read_state(path,alias_id,dev,ino,head_sha256,offset,closed_size) VALUES(?,?,?,?,NULL,0,NULL) "
                "ON CONFLICT(path) DO UPDATE SET alias_id=excluded.alias_id, dev=excluded.dev, ino=excluded.ino, "
                "head_sha256=NULL, offset=0, closed_size=NULL", (str(path), alias_id, st.st_dev, st.st_ino))
        else:
            alias_id, offset = rs[0], rs[4]
        data, size = _read_chunk(handle, offset, scan.max_read_bytes)
    end = data.rfind(b"\n") + 1
    complete, rest = data[:end], data[end:]
    at_eof = offset + len(data) >= size
    state = StreamState(True, at_eof, size, rest if (at_eof and rest) else None, offset + end, alias_id)
    return alias_id, offset, complete, state


def save_progress(conn: sqlite3.Connection, path: Path, alias_id: int, offset: int, complete: bytes,
                  first_chunk: bool) -> None:
    head = None
    if first_chunk and b"\n" in complete:
        head = hashlib.sha256(complete[:complete.index(b"\n") + 1]).hexdigest()
    conn.execute("UPDATE read_state SET offset=?, head_sha256=COALESCE(head_sha256, ?) WHERE path=?",
                 (offset, head, str(path)))
    if head is not None:
        conn.execute("UPDATE stream_aliases SET head_sha256=? WHERE alias_id=? AND head_sha256 IS NULL",
                     (head, alias_id))


def iter_lines(complete: bytes, base: int):
    """Yield (absolute line offset, raw line) for each complete, non-blank line."""
    position = 0
    for raw in complete.split(b"\n")[:-1]:
        if raw.strip():
            yield base + position, raw
        position += len(raw) + 1


def parse_line(raw: bytes) -> dict | None:
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return obj if isinstance(obj, dict) and isinstance(obj.get("type"), str) else None


def note_malformed(conn: sqlite3.Connection, path: Path, offset: int, raw: bytes, kind: str,
                   invocation_id: str | None, source: str = SOURCE) -> None:
    conn.execute("INSERT OR IGNORE INTO malformed_lines(path,line_offset,line_sha256,source,kind,invocation_id) "
                 "VALUES(?,?,?,?,?,?)",
                 (str(path), offset, hashlib.sha256(raw).hexdigest(), source, kind, invocation_id))


# --------------------------------------------------------------------- result and event facts


def _usage_map(usage: object) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    values = {tau: _int(usage.get(key)) for tau, key in USAGE_FIELDS.items()}
    return None if any(v is None for v in values.values()) else values  # type: ignore[return-value]


def _models_map(model_usage: object) -> tuple[dict[str, dict[str, float]] | None, set[str]]:
    """Per-model cumulative from modelUsage, grouped by normalized label. Returns (models|None if invalid,
    unrecognized raw names)."""
    if not isinstance(model_usage, dict):
        return None, set()
    models: dict[str, dict[str, float]] = {}
    unrecognized: set[str] = set()
    for raw_name, entry in model_usage.items():
        if not isinstance(entry, dict):
            return None, set()
        values = {tau: _int(entry.get(key)) for tau, key in MODEL_USAGE_FIELDS.items()}
        if any(v is None for v in values.values()):
            return None, set()
        cost = entry.get("costUSD", 0.0)
        cost = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0 \
            and cost == cost and cost != float("inf") else 0.0
        label = normalize_model(raw_name)
        if label.recognized is False and (name := safe_token(raw_name)):
            unrecognized.add(name)
        slot = models.setdefault(label.label, {**dict.fromkeys(TOKEN_TYPES, 0), "cost_usd": 0.0})
        for tau in TOKEN_TYPES:
            slot[tau] += values[tau]
        slot["cost_usd"] += cost
    return models, unrecognized


@dataclass
class ParsedResult:
    session_id: str
    uuid: str
    result_index: int | None
    is_error: bool
    subtype: str | None
    zeroed: bool
    usage: dict[str, int] | None
    models: dict[str, dict[str, float]] | None
    nested: bool
    unrecognized: set[str]


def parse_result(obj: dict, raw: bytes, init_session: str | None) -> ParsedResult:
    subtype = safe_token(obj.get("subtype"))
    is_error = obj.get("is_error") is True or (isinstance(obj.get("subtype"), str)
                                               and obj["subtype"].startswith("error"))
    usage = _usage_map(obj.get("usage"))
    raw_usage, raw_models = obj.get("usage"), obj.get("modelUsage")
    models, unrecognized = _models_map(raw_models)
    usage_zero = raw_usage is None or (usage is not None and not any(usage.values()))
    models_zero = raw_models is None or (models is not None and not any(
        any(m[tau] for tau in TOKEN_TYPES) for m in models.values()))
    stats = obj.get("subagent_stats")
    nested = isinstance(stats, dict) and any(
        isinstance(stats.get(key), int) and not isinstance(stats.get(key), bool) and stats[key] > 0
        for key in ("spawned", "spawned_by_subagents"))
    session = safe_token(obj.get("session_id")) or init_session or ""
    uuid = safe_token(obj.get("uuid")) or "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    index = _int(obj.get("result_index"))
    return ParsedResult(session, uuid, index, is_error, subtype, bool(is_error and usage_zero and models_zero),
                        usage, models, nested, unrecognized)


# --------------------------------------------------------------------- one attempt


def _inv(conn: sqlite3.Connection, inv_id: str) -> dict | None:
    cursor = conn.execute("SELECT * FROM invocations WHERE id=?", (inv_id,))
    row = cursor.fetchone()
    return dict(zip([c[0] for c in cursor.description], row)) if row else None


def _ensure_invocation(scan: Scan, task_id: str, task_class: str, attempt: Attempt) -> dict:
    inv_id = invocation_id(task_id, attempt.number)
    existing = _inv(scan.conn, inv_id)
    if existing:
        return existing
    start = attempt.start
    resumed = start["event"] == "resumed"
    advisor = normalize_model(start.get("advisor")).label if isinstance(start.get("advisor"), str) else None
    timeout = _int(start.get("timeout_seconds"))
    started = parse_at(start.get("at")) or scan.now
    terminal_at = parse_at(attempt.terminal.get("at")) if attempt.terminal else None
    history = attempt_is_history(scan.live_since, started, terminal_at,
                                 (timeout or FALLBACK_TIMEOUT_SECONDS) + KILL_GRACE_SECONDS + HORIZON_SLACK_SECONDS)
    scan.conn.execute(
        "INSERT INTO invocations(id,source,provider,session_or_thread,task_id,attempt,mode,predecessor_id,"
        "requested_model_raw,advisor_model,lifecycle_state,started_at,timeout_seconds,task_class,backfill) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,'open',?,?,?,?)",
        (inv_id, SOURCE, PROVIDER, safe_token(start.get("worker_session")), task_id, attempt.number,
         "resumed" if resumed else "fresh", invocation_id(task_id, attempt.number - 1) if resumed else None,
         safe_token(start.get("model")), advisor, started,
         timeout if timeout else FALLBACK_TIMEOUT_SECONDS, task_class, int(history)))
    return _inv(scan.conn, inv_id)  # type: ignore[return-value]


def horizon_passed(inv: dict, now: int) -> bool:
    return now - inv["started_at"] > inv["timeout_seconds"] + KILL_GRACE_SECONDS + HORIZON_SLACK_SECONDS


def _apply_init(scan: Scan, inv: dict, obj: dict) -> None:
    if inv["executor_model_raw"] is not None:
        return
    raw = safe_token(obj.get("model"))
    if raw is None:
        return
    version = obj.get("claude_code_version")
    version = version if parse_version(version) else None
    label = normalize_model(raw)
    session = safe_token(obj.get("session_id"))
    scan.conn.execute("UPDATE invocations SET executor_model_raw=?, executor_model=?, cli_version=?, "
                      "session_or_thread=COALESCE(session_or_thread, ?) WHERE id=?",
                      (raw, label.label, version, session, inv["id"]))
    inv.update(executor_model_raw=raw, executor_model=label.label, cli_version=version)
    if label.recognized is False:
        _flag(scan.conn, inv["id"], "unrecognized", raw)
    if inv["requested_model_raw"] and is_model_mismatch(inv["requested_model_raw"], raw):
        _flag(scan.conn, inv["id"], "mismatch", raw)


def _flag(conn: sqlite3.Connection, inv_id: str, kind: str, model_raw: str) -> None:
    conn.execute("INSERT OR IGNORE INTO model_flags(invocation_id,kind,model_raw) VALUES(?,?,?)",
                 (inv_id, kind, model_raw))


def _apply_assistant(scan: Scan, inv: dict, obj: dict, raw: bytes) -> None:
    message = obj.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return
    session = safe_token(obj.get("session_id")) or inv["session_or_thread"] or ""
    message_id = safe_token(message.get("id")) or safe_token(obj.get("uuid")) or hashlib.sha256(raw).hexdigest()
    for index, block in enumerate(content):
        if isinstance(block, dict) and block.get("type") == "server_tool_use" and block.get("name") == "advisor":
            scan.conn.execute("INSERT OR IGNORE INTO advisor_consultations(session_id,message_id,block_index,"
                              "invocation_id) VALUES(?,?,?,?)", (session, message_id, index, inv["id"]))


def _apply_result(scan: Scan, inv: dict, obj: dict, raw: bytes, path: Path, offset: int, task_class: str) -> None:
    conn = scan.conn
    result = parse_result(obj, raw, inv["session_or_thread"])
    seen = conn.execute("SELECT invocation_id FROM results WHERE session_id=? AND uuid=?",
                        (result.session_id, result.uuid)).fetchone()
    if seen:  # redelivery / copy: nothing is published twice (A14, A16)
        record_correction(conn, kind="duplicate_after_publish", invocation_id=inv["id"], detail="redelivered_result",
                          dedupe_key=f"dup:{path}:{offset}:{result.session_id}:{result.uuid}", now=scan.now)
        return
    seq = conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM results WHERE invocation_id=?", (inv["id"],)).fetchone()[0]
    usage = result.usage or {}
    conn.execute(
        "INSERT INTO results(session_id,uuid,invocation_id,seq,result_index,is_error,subtype,zeroed,usage_ok,"
        "models_ok,nested,input,output,cache_read,cache_write) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (result.session_id, result.uuid, inv["id"], seq, result.result_index, int(result.is_error), result.subtype,
         int(result.zeroed), int(result.usage is not None), int(result.models is not None), int(result.nested),
         usage.get("input"), usage.get("output"), usage.get("cache_read"), usage.get("cache_write")))
    for model, cum in sorted((result.models or {}).items()):
        conn.execute("INSERT INTO result_models(session_id,uuid,model,input,output,cache_read,cache_write,cost_usd) "
                     "VALUES(?,?,?,?,?,?,?,?)",
                     (result.session_id, result.uuid, model, int(cum["input"]), int(cum["output"]),
                      int(cum["cache_read"]), int(cum["cache_write"]), cum["cost_usd"]))
    for name in sorted(result.unrecognized):
        _flag(conn, inv["id"], "unrecognized", name)
    if result.usage is not None and not result.zeroed:  # §3.6: a main_result publishes when its line commits
        executor = inv["executor_model"] or normalize_model(inv["requested_model_raw"]).label
        key = f"{result.session_id}:{result.uuid}"
        if unbound_published(conn, key):
            # C-W1-2: an unbound alias already published these facts as identity_unavailable; a later canonical
            # arrival keeps the result row (for M) but publishes nothing a second time.
            record_correction(conn, kind="duplicate_after_publish", invocation_id=inv["id"],
                              detail="published_as_identity_unavailable", dedupe_key=f"unb:{key}", now=scan.now)
            return
        for tau in TOKEN_TYPES:
            publish_contribution(conn, key=key, kind="main_result", invocation_id=inv["id"],
                                 provider=inv["provider"], model=executor, role=EXECUTOR_ROLE[inv["source"]],
                                 source=inv["source"], task_class=task_class, token_type=tau,
                                 value=result.usage[tau], now=scan.now, backfill=inv["backfill"])


def ingest_claude_events(scan: Scan, inv: dict, path: Path, task_class: str, *, provenance: str,
                         slot: str = "unknown") -> StreamState:
    """Read and apply the new complete lines of a canonical Claude stream (S1 attempt, S2 lane or coordinator),
    inside the caller's transaction. `rate_limit_event` lines become window markers (§3.8) with the nearest
    preceding line timestamp as observation time."""
    source = inv["source"]
    read = read_stream(scan, path, source_alias=("canonical", inv["id"], provenance), source=source)
    if read is None:
        return StreamState(False, True)
    alias_id, offset, complete, state = read
    clock = scan.conn.execute("SELECT last_ts FROM stream_clock WHERE alias_id=?", (alias_id,)).fetchone()
    last_ts = clock[0] if clock else None
    slot = slot if slot in ("primary", "secondary") else "unknown"
    for line_offset, raw in iter_lines(complete, offset):
        obj = parse_line(raw)
        if obj is None:
            note_malformed(scan.conn, path, line_offset, raw, "line", inv["id"], source)
            continue
        stamp = parse_ts(obj.get("timestamp"))
        if obj["type"] == "system" and obj.get("subtype") == "init":
            _apply_init(scan, inv, obj)
        elif obj["type"] == "assistant":
            _apply_assistant(scan, inv, obj, raw)
        elif obj["type"] == "result":
            _apply_result(scan, inv, obj, raw, path, line_offset, task_class)
        elif obj["type"] == "rate_limit_event":
            observe_rate(scan.conn, slot=slot, stream=str(path), line_index=line_offset, obj=obj, raw=raw,
                         observed_at=last_ts)
        if stamp is not None:
            last_ts = stamp
    scan.conn.execute("INSERT INTO stream_clock(alias_id,last_ts) VALUES(?,?) ON CONFLICT(alias_id) DO UPDATE "
                      "SET last_ts=excluded.last_ts", (alias_id, last_ts))
    save_progress(scan.conn, path, alias_id, state.prefix_end, complete, first_chunk=offset == 0)
    return state


# --------------------------------------------------------------------- finalization


def _receipt_facts(path: Path, configured: bool) -> tuple[int | None, str | None, str]:
    default = "unknown" if configured else "not_configured"
    try:
        with open_regular(path) as handle:
            raw = handle.read(MAX_RECEIPT_BYTES + 1)
        if len(raw) > MAX_RECEIPT_BYTES:
            return None, None, default
        data = json.loads(raw)
    except (OSError, ValueError):
        return None, None, default
    if not isinstance(data, dict):
        return None, None, default
    ok = data.get("receipt_ok")
    status = data.get("worker_status")
    state = data.get("advisor_enabled")
    return (int(ok) if isinstance(ok, bool) else None, status if status in ("done", "escalate", "blocked", "missing")
            else None, state if state in ADVISOR_STATES else default)


def _predecessor(scan: Scan, inv: dict) -> tuple[str, dict[str, dict[str, float]]] | None:
    """(state, cumulative) of attempt k-1, or None while it is not finalized (awaiting_predecessor)."""
    pred = _inv(scan.conn, inv["predecessor_id"])
    if pred is None:
        return "missing", {}
    if pred["lifecycle_state"] != "finalized":
        return None
    zeroed = scan.conn.execute("SELECT 1 FROM results WHERE invocation_id=? AND zeroed=1", (pred["id"],)).fetchone()
    rows = scan.conn.execute("SELECT model,input,output,cache_read,cache_write,cost_usd FROM cumulative "
                             "WHERE invocation_id=?", (pred["id"],)).fetchall()
    if zeroed:
        return "unproven", {}  # a zeroed crash result may hide spend: continuity is not proven
    if not rows:
        return "missing", {}
    return "proven", {r[0]: {"input": r[1], "output": r[2], "cache_read": r[3], "cache_write": r[4],
                              "cost_usd": r[5]} for r in rows}


def _results(conn: sqlite3.Connection, inv_id: str) -> list[ResultFacts]:
    facts = []
    for sid, uuid, is_error, zeroed, usage_ok, models_ok, nested, *usage in conn.execute(
            "SELECT session_id,uuid,is_error,zeroed,usage_ok,models_ok,nested,input,output,cache_read,cache_write "
            "FROM results WHERE invocation_id=? ORDER BY seq", (inv_id,)).fetchall():
        models = None
        if models_ok:
            models = {m[0]: {"input": m[1], "output": m[2], "cache_read": m[3], "cache_write": m[4],
                             "cost_usd": m[5]} for m in conn.execute(
                "SELECT model,input,output,cache_read,cache_write,cost_usd FROM result_models "
                "WHERE session_id=? AND uuid=?", (sid, uuid)).fetchall()}
        facts.append(ResultFacts(dict(zip(TOKEN_TYPES, usage)) if usage_ok else None, models, bool(is_error),
                                 bool(zeroed), bool(nested)))
    return facts


def finalize_claude(scan: Scan, inv: dict, path: Path, state: StreamState, task_class: str, *, evidence: str,
                    outcome: str, receipt: tuple[int | None, str | None, str | None] = (None, None, None),
                    terminal_kind: str = "record_row") -> bool:
    """Finalize one Claude process (S1 attempt, S2 lane or coordinator stream). False (and `awaiting_predecessor`)
    while a named predecessor is not finalized. `mode` None (no launcher metadata, §3.3) = continuity UNPROVEN, so
    a resumed session's cumulative baseline is unknown and the remainder is withheld (`no_baseline`, C-W1-6)."""
    conn = scan.conn
    external: set[str] = set()
    baseline = Baseline("zero")
    pred_state = "none"
    if inv["mode"] == "resumed" and inv["predecessor_id"]:
        pred = _predecessor(scan, inv)
        if pred is None:
            conn.execute("UPDATE invocations SET lifecycle_state='awaiting_predecessor' WHERE id=?", (inv["id"],))
            return False
        pred_state, pred_cum = pred
        version = parse_version(inv["cli_version"])
        if version is None:
            external.add("unknown_version_semantics")  # §3.7: the main-loop M is still published
        if version is not None and version < RESUME_CUMULATIVE_SINCE:
            baseline = Baseline("zero")  # D2: totals restart at zero for such resumed processes
        elif pred_state == "proven":
            baseline = Baseline("cumulative", pred_cum)
        else:
            baseline = Baseline(pred_state)
    elif inv["mode"] in ("resumed", None):
        pred_state, baseline = "unproven", Baseline("unproven")
    results = _results(conn, inv["id"])
    if not results:
        external.add("no_result")
    if evidence == "horizon":
        external.add("terminal_unproven")
    if conn.execute("SELECT 1 FROM malformed_lines WHERE invocation_id=? AND kind='line' LIMIT 1",
                    (inv["id"],)).fetchone():
        external.add("malformed")
    closed_size = state.size if state.exists else 0
    if state.tail:  # §3.2 step 2: settle the torn tail once, in this transaction
        settle_tail(conn, state, path, inv, scan.now)
        external.add("incomplete_tail")
    executor = inv["executor_model"] or normalize_model(inv["requested_model_raw"]).label
    consultations = conn.execute("SELECT COUNT(*) FROM advisor_consultations WHERE invocation_id=?",
                                 (inv["id"],)).fetchone()[0]
    plan = plan_partition(results, executor, inv["advisor_model"], consultations, baseline, external)
    conn.execute("UPDATE invocations SET predecessor_state=?, terminal_kind=? WHERE id=?",
                 (pred_state, terminal_kind, inv["id"]))
    finalize_invocation(conn, invocation_id=inv["id"], outcome=outcome, reasons=set(), plan=plan, source=inv["source"],
                        task_class=task_class, terminal_evidence=evidence, advisor_state=receipt[2],
                        receipt_ok=receipt[0], worker_status=receipt[1], now=scan.now)
    conn.execute("UPDATE read_state SET closed_size=? WHERE path=?", (closed_size, str(path)))
    return True


def settle_tail(conn: sqlite3.Connection, state: StreamState, path: Path, inv: dict, now: int) -> None:
    """DESIGN §3.2 step 2: persist the settlement boundary (length and hash only) and count the tail once."""
    assert state.tail is not None
    conn.execute("INSERT OR IGNORE INTO stream_settlements(alias_id,prefix_end_offset,tail_bytes,tail_sha256,"
                 "settled_at) VALUES(?,?,?,?,?)",
                 (state.alias_id, state.prefix_end, len(state.tail), hashlib.sha256(state.tail).hexdigest(), now))
    note_malformed(conn, path, state.prefix_end, state.tail, "tail", inv["id"], inv["source"])


def _finalize(scan: Scan, inv: dict, attempt: Attempt, task_dir: Path, state: StreamState, task_class: str,
              evidence: str) -> bool:
    receipt_ok, status, advisor_state = _receipt_facts(task_dir / f"receipt-{attempt.number}.json",
                                                       inv["advisor_model"] is not None)
    outcome = attempt.terminal["event"] if attempt.terminal else "terminal_unproven"
    return finalize_claude(scan, inv, task_dir / f"events-{attempt.number}.jsonl", state, task_class,
                           evidence=evidence, outcome=outcome, receipt=(receipt_ok, status, advisor_state))


def late_tail_check(scan: Scan, inv: dict, path: Path) -> None:
    """Bytes past the settlement boundary are a `late_tail` correction, never parsed or published (§3.2 step 4)."""
    conn = scan.conn
    try:
        info = path.lstat()
    except OSError:
        return
    if not stat.S_ISREG(info.st_mode):
        return
    size = info.st_size
    rs = conn.execute("SELECT closed_size FROM read_state WHERE path=?", (str(path),)).fetchone()
    closed = (rs[0] if rs and rs[0] is not None else 0)
    if size > closed:
        record_correction(conn, kind="late_tail", invocation_id=inv["id"],
                          detail="stream_grew_after_finalization" if rs else "stream_appeared_after_finalization",
                          dedupe_key=f"late_tail:{inv['id']}:{size}", now=scan.now)
        if rs:
            conn.execute("UPDATE read_state SET closed_size=? WHERE path=?", (size, str(path)))


def _after_finalization(scan: Scan, inv: dict, attempt: Attempt, path: Path) -> None:
    """Facts arriving after finalization are corrections only (§3.2, §3.6): never a second finalization, a new
    contribution or a changed outcome."""
    if inv["terminal_evidence"] == "horizon" and attempt.terminal is not None:
        record_correction(scan.conn, kind="late_terminal", invocation_id=inv["id"], detail=attempt.terminal["event"],
                          dedupe_key=f"late_terminal:{inv['id']}", now=scan.now)
    late_tail_check(scan, inv, path)


def process_attempt(scan: Scan, task_dir: Path, task_id: str, task_class: str, attempt: Attempt) -> None:
    """One transaction per attempt: stream batch, offsets, contributions and (when due) the finalization."""
    path = task_dir / f"events-{attempt.number}.jsonl"
    with scan.ledger.transaction() as conn:
        inv = _ensure_invocation(scan, task_id, task_class, attempt)
        if inv["lifecycle_state"] == "finalized":
            _after_finalization(scan, inv, attempt, path)
            return
        state = ingest_claude_events(scan, inv, path, task_class, provenance="dispatch_record", slot=attempt.slot)
        evidence = "record_row" if attempt.terminal else ("horizon" if horizon_passed(inv, scan.now) else None)
        if evidence is None:
            return
        if not state.at_eof:
            conn.execute("UPDATE invocations SET lifecycle_state='terminal_observed' WHERE id=?", (inv["id"],))
            return
        _finalize(scan, inv, attempt, task_dir, state, task_class, evidence)


# --------------------------------------------------------------------- tasks


def _sync_task(scan: Scan, task_id: str, task_class: str, view: TaskView) -> None:
    """Task row, and the close snapshot once `completed` exists and every attempt is finalized."""
    with scan.ledger.transaction() as conn:
        first = min((parse_at(a.start.get("at")) or scan.now) for a in view.attempts.values())
        conn.execute("INSERT OR IGNORE INTO tasks(task_id,task_class,first_dispatch_at) VALUES(?,?,?)",
                     (task_id, task_class, first))
        conn.execute("UPDATE tasks SET attempts=? WHERE task_id=? AND closed_at IS NULL",
                     (len(view.attempts), task_id))
        row = conn.execute("SELECT closed_at FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row[0] is not None or view.completed is None:
            return
        open_count = conn.execute("SELECT COUNT(*) FROM invocations WHERE task_id=? AND lifecycle_state!='finalized'",
                                  (task_id,)).fetchone()[0]
        finalized = conn.execute("SELECT COUNT(*) FROM invocations WHERE task_id=?", (task_id,)).fetchone()[0]
        if open_count or finalized != len(view.attempts):
            return
        outcome = view.completed["outcome"]
        unknown = conn.execute("SELECT COUNT(*) FROM invocations WHERE task_id=? AND unknown_reason IS NOT NULL",
                               (task_id,)).fetchone()[0]
        history = conn.execute("SELECT MIN(backfill) FROM invocations WHERE task_id=?", (task_id,)).fetchone()[0]
        conn.execute(
            "UPDATE tasks SET outcome=?, closed_at=?, first_pass=?, unknown_invocations=?, backfill=? "
            "WHERE task_id=?",
            (outcome, parse_at(view.completed.get("at")) or scan.now,
             int(outcome == "accepted" and len(view.attempts) == 1), unknown, int(history or 0), task_id))
        conn.execute(
            "INSERT INTO task_token_snapshots(task_id,role,token_type,value) "
            "SELECT ?, c.role, c.token_type, SUM(c.value) FROM contributions c JOIN invocations i "
            "ON i.id=c.invocation_id WHERE i.task_id=? AND c.backfill=0 GROUP BY c.role, c.token_type",
            (task_id, task_id))


# --------------------------------------------------------------------- entry point


def scan_routine(scan: Scan) -> list[tuple[Path, str]]:
    """One bounded pass over `routine-runs`. Attempts of a task are processed strictly in attempt order. Returns
    the (path, source) read-alias candidates (streams no record row names) for aliases.py."""
    runs = scan.source_root / "routine-runs"
    if not runs.is_dir():
        scan.ledger.set_meta("source_up.routine", 0)
        return []
    scan.ledger.set_meta("source_up.routine", 1)
    canonical: set[Path] = set()
    candidates: list[Path] = []
    for task_dir in sorted(p for p in runs.iterdir() if p.is_dir() and not p.is_symlink() and TASK_ID.match(p.name)):
        try:
            candidates += sorted(task_dir.glob("events-*.jsonl"))
        except OSError:
            continue
        view = parse_record(read_record(task_dir / "record.jsonl"))
        if not view.attempts:
            continue
        task_class = scan.registry.classify(task_dir.name)
        for number in sorted(view.attempts):
            canonical.add(task_dir / f"events-{number}.jsonl")
            process_attempt(scan, task_dir, task_dir.name, task_class, view.attempts[number])
        _sync_task(scan, task_dir.name, task_class, view)
    return [(path, SOURCE) for path in candidates
            if path not in canonical and EVENTS_NAME.match(path.name) and path.is_file() and not path.is_symlink()]
