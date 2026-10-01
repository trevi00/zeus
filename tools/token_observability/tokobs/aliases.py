"""Read aliases: streams no launcher names (DESIGN §3.3, C-W1-2).

Purpose: parse an unnamed stream (a copy, a renamed file) for fact keys only, bind it to a canonical invocation
when a fact equals one of that invocation's facts, and after the source's idle horizon publish the facts no
canonical stream knows as `identity_unavailable`. Layer: tooling.
Owns: the alias lifecycle (`alias_pending` -> `bound` | `unbound`), unbound publication.
Does-not-own: canonical invocations; an alias never creates an invocation, outcome, attempt or unknown.
Implements: ACCEPTANCE A47 (routine, Codex), A59(b), C-W1-2.
"""

from __future__ import annotations

from pathlib import Path

from .backfill import stream_is_history
from .s1_routine import (
    Scan,
    iter_lines,
    note_malformed,
    parse_line,
    parse_result,
    read_stream,
    safe_token,
    save_progress,
)
from .s3_codex import SOURCE as CODEX_SOURCE
from .s3_codex import parse_point, publish_unbound_point
from .vocab import (
    EXECUTOR_ROLE,
    IDENTITY_UNAVAILABLE,
    LANE_HORIZON_SECONDS,
    TOKEN_TYPES,
    normalize_model,
)

PROVIDER = "anthropic"


def _load_state(conn, alias_id: int) -> tuple[str | None, str | None, str | None]:
    """F1: (session, model, thread) parsed from earlier batches of this read alias."""
    row = conn.execute("SELECT session_id,model,thread_id FROM alias_state WHERE alias_id=?", (alias_id,)).fetchone()
    return row if row else (None, None, None)


def _save_state(conn, alias_id: int, *, session: str | None = None, model: str | None = None,
                thread: str | None = None) -> None:
    """Persisted in the batch's transaction, next to the offset (`save_progress`), so a restart between two scans
    resumes with the same init/thread context. Only values known so far overwrite; none is ever cleared."""
    conn.execute("INSERT INTO alias_state(alias_id,session_id,model,thread_id) VALUES(?,?,?,?) "
                 "ON CONFLICT(alias_id) DO UPDATE SET session_id=COALESCE(excluded.session_id, session_id), "
                 "model=COALESCE(excluded.model, model), thread_id=COALESCE(excluded.thread_id, thread_id)",
                 (alias_id, session, model, thread))


def scan_claude_alias(scan: Scan, path: Path, source: str) -> None:
    """Parse result keys and usage only; publish nothing here."""
    conn = scan.conn
    with scan.ledger.transaction():
        row = conn.execute("SELECT a.binding FROM read_state rs JOIN stream_aliases a USING(alias_id) "
                           "WHERE rs.path=?", (str(path),)).fetchone()
        if row and row[0] == "bound":
            return
        read = read_stream(scan, path, source_alias=("alias_pending", None, "none"), source=source)
        if read is None:
            return
        alias_id, offset, complete, state = read
        session, model, _thread = _load_state(conn, alias_id)
        model = model or "other"
        for line_offset, raw in iter_lines(complete, offset):
            obj = parse_line(raw)
            if obj is None:
                note_malformed(conn, path, line_offset, raw, "line", None, source)
            elif obj["type"] == "system" and obj.get("subtype") == "init" and safe_token(obj.get("model")):
                model = normalize_model(obj["model"]).label
                session = safe_token(obj.get("session_id")) or session
            elif obj["type"] == "result":
                parsed = parse_result(obj, raw, session)
                conn.execute("INSERT OR IGNORE INTO alias_facts(alias_id,session_id,uuid) VALUES(?,?,?)",
                             (alias_id, parsed.session_id, parsed.uuid))
                if parsed.usage is not None and not parsed.zeroed:
                    conn.execute("INSERT OR IGNORE INTO alias_usage(alias_id,session_id,uuid,model,input,output,"
                                 "cache_read,cache_write) VALUES(?,?,?,?,?,?,?,?)",
                                 (alias_id, parsed.session_id, parsed.uuid, model, parsed.usage["input"],
                                  parsed.usage["output"], parsed.usage["cache_read"], parsed.usage["cache_write"]))
        _save_state(conn, alias_id, session=session, model=model)
        save_progress(conn, path, alias_id, state.prefix_end, complete, first_chunk=offset == 0)


def scan_codex_alias(scan: Scan, path: Path) -> None:
    conn = scan.conn
    with scan.ledger.transaction():
        row = conn.execute("SELECT a.binding FROM read_state rs JOIN stream_aliases a USING(alias_id) "
                           "WHERE rs.path=?", (str(path),)).fetchone()
        if row and row[0] == "bound":
            return
        read = read_stream(scan, path, source_alias=("alias_pending", None, "none"), source=CODEX_SOURCE)
        if read is None:
            return
        alias_id, offset, complete, state = read
        thread = _load_state(conn, alias_id)[2]
        for line_offset, raw in iter_lines(complete, offset):
            obj = parse_line(raw)
            if obj is None:
                note_malformed(conn, path, line_offset, raw, "line", None, CODEX_SOURCE)
            elif obj["type"] == "thread.started" and thread is None:
                thread = safe_token(obj.get("thread_id"))
            elif obj["type"] == "turn.completed":
                point = parse_point(thread, obj.get("usage"))
                if point is not None:
                    conn.execute("INSERT OR IGNORE INTO alias_codex_points(alias_id,thread_id,input_tokens,cached,"
                                 "cache_write,output,reasoning) VALUES(?,?,?,?,?,?,?)",
                                 (alias_id, point.thread, point.inp, point.cached, point.cw, point.out,
                                  point.reasoning))
        _save_state(conn, alias_id, thread=thread)
        save_progress(conn, path, alias_id, state.prefix_end, complete, first_chunk=offset == 0)


def bind_aliases(scan: Scan) -> None:
    """A pending alias whose fact equals a canonical stream's fact binds to that canonical invocation (before or
    after its finalization); the facts deduplicate and add nothing."""
    conn = scan.conn
    with scan.ledger.transaction():
        for (alias_id,) in conn.execute("SELECT alias_id FROM stream_aliases WHERE binding IN "
                                        "('alias_pending','unbound') ORDER BY alias_id").fetchall():
            match = conn.execute("SELECT MIN(r.invocation_id) FROM alias_facts f JOIN results r "
                                 "ON r.session_id=f.session_id AND r.uuid=f.uuid WHERE f.alias_id=?",
                                 (alias_id,)).fetchone()
            invocation = match[0] if match else None
            if invocation is None:
                match = conn.execute(
                    "SELECT MIN(p.invocation_id) FROM alias_codex_points a JOIN codex_points p ON "
                    "p.thread_id=a.thread_id AND p.input_tokens=a.input_tokens AND p.cached=a.cached AND "
                    "p.cache_write=a.cache_write AND p.output=a.output AND p.reasoning=a.reasoning "
                    "WHERE a.alias_id=? AND p.invocation_id IS NOT NULL", (alias_id,)).fetchone()
                invocation = match[0] if match else None
            if invocation is not None:
                conn.execute("UPDATE stream_aliases SET binding='bound', invocation_id=?, bound_at=? WHERE alias_id=?",
                             (invocation, scan.now, alias_id))


def publish_unbound(scan: Scan) -> None:
    """After the source's idle horizon (mtime, delay-only, §3.1), publish the not-yet-known facts of a still
    unbound alias as `identity_unavailable` (no invocation, outcome, attempt or unknown)."""
    conn = scan.conn
    with scan.ledger.transaction():
        aliases = conn.execute("SELECT a.alias_id,a.path,a.source FROM stream_aliases a JOIN read_state rs USING(alias_id) "
                               "WHERE a.binding IN ('alias_pending','unbound') ORDER BY a.alias_id").fetchall()
        for alias_id, path, source in aliases:
            try:
                modified = Path(path).lstat().st_mtime
            except OSError:
                continue
            horizon = scan.codex_idle_seconds if source == CODEX_SOURCE else LANE_HORIZON_SECONDS
            if scan.now - modified <= horizon:
                continue
            history = stream_is_history(scan.live_since, modified, terminal_at=None, horizon_seconds=horizon)
            if source == CODEX_SOURCE:
                points = conn.execute("SELECT thread_id,input_tokens,cached,cache_write,output,reasoning FROM "
                                      "alias_codex_points WHERE alias_id=?", (alias_id,)).fetchall()
                from .s3_codex import Point
                for p in sorted((Point(*row) for row in points), key=lambda x: x.key):
                    publish_unbound_point(scan, alias_id, p, history)
            else:
                for session, uuid, model, *usage in conn.execute(
                        "SELECT u.session_id,u.uuid,u.model,u.input,u.output,u.cache_read,u.cache_write FROM "
                        "alias_usage u WHERE u.alias_id=? AND NOT EXISTS (SELECT 1 FROM results r WHERE "
                        "r.session_id=u.session_id AND r.uuid=u.uuid)", (alias_id,)).fetchall():
                    for tau, value in zip(TOKEN_TYPES, usage):
                        if value > 0:
                            # F1: the id is the stable token fact (session, uuid, type), never the model label,
                            # which is provisional until an `init` line has been seen: a copy that parsed another
                            # label (or none) cannot publish the same fact a second time.
                            conn.execute(
                                "INSERT OR IGNORE INTO unbound_contributions(id,provider,model,role,source,"
                                "task_class,token_type,value,published_at,backfill) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (f"{session}:{uuid}|unbound|{tau}", PROVIDER, model, EXECUTOR_ROLE[source], source,
                                 IDENTITY_UNAVAILABLE, tau, value, scan.now, int(history)))
            conn.execute("UPDATE stream_aliases SET binding='unbound' WHERE alias_id=? AND binding='alias_pending'",
                         (alias_id,))


def scan_aliases(scan: Scan, claude: list[tuple[Path, str]], codex: list[tuple[Path, str]]) -> None:
    for path, source in claude:
        scan_claude_alias(scan, path, source)
    for path, _source in codex:
        scan_codex_alias(scan, path)
    bind_aliases(scan)
    publish_unbound(scan)
