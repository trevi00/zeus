"""S3 Codex exec: run-script-named streams, thread-cumulative points and intervals, unattributed intervals.

Purpose: read `<stem>-codex-run.sh` (argv facts only) and `<stem>-codex-events.jsonl` (`thread.started`,
`turn.completed`, `turn.failed`, `error`) into the ledger. Layer: tooling.
Owns: DESIGN §3.2 (S3 lifecycle: the turn line is the terminal evidence; idle horizon 2 x decision_seconds),
§3.3 (canonical `codex:<stem>`; points keyed by `(thread_id, cumulative tuple)`; predecessor proof), §3.5
(anchor, delta from 0 for a fresh exec, `unattributed_interval`), K4 (normalization), C-W1-3 (missing
`cache_write_input_tokens` = unknown), C-W1-4 (optional `<stem>-codex-prestart.json` sidecar).
Does-not-own: reading primitives (s1_routine), alias binding and unbound publication (aliases.py), exposition.
Implements: ACCEPTANCE A20, A21, A46, A47 (Codex), A49, A59.

Ordering: points of one thread are ordered by the cumulative tuple itself, never by mtime. Runs that become
final in the same scan are finalized in that order, so the file order cannot change an interval.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from .backfill import stream_is_history
from .publication import close_invocation, publish_contribution, record_correction
from .s1_routine import (
    Scan,
    StreamState,
    _flag,
    _inv,
    iter_lines,
    late_tail_check,
    note_malformed,
    open_regular,
    parse_line,
    read_json,
    read_stream,
    safe_token,
    save_progress,
    settle_tail,
)
from .vocab import IDENTITY_UNAVAILABLE, normalize_model, primary_reason

SOURCE = "codex_exec"
PROVIDER = "openai"
ROLE = "reviewer"
MAX_SCRIPT_BYTES = 64 * 1024
STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REDIRECT = re.compile(r"(?<![0-9&])>\s*[\"']?[^\s\"'>]*?([A-Za-z0-9][A-Za-z0-9._-]*)-codex-events\.jsonl[\"']?")
TERMINAL_LINES = ("turn.completed", "turn.failed", "error")
RAW_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
NO_CACHE_WRITE = -1  # the point lacks `cache_write_input_tokens`: unknown, never 0 (C-W1-3)


@dataclass(frozen=True)
class Point:
    thread: str
    inp: int
    cached: int
    cw: int
    out: int
    reasoning: int

    @property
    def key(self) -> tuple[int, int, int, int, int]:
        return (self.inp, self.out, self.cached, self.reasoning, self.cw)

    @property
    def text(self) -> str:
        return f"{self.inp}.{self.cached}.{self.cw}.{self.out}.{self.reasoning}"


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def parse_point(thread: str | None, usage: object) -> Point | None:
    """A cumulative point from a `usage` object; None when a required field is missing or malformed."""
    if thread is None or not isinstance(usage, dict):
        return None
    values = [_count(usage.get(name)) for name in RAW_FIELDS]
    if any(v is None for v in values):
        return None
    inp, cached, out, reasoning = values  # type: ignore[misc]
    if cached > inp:
        return None  # input includes cached input (R5); anything else is not a usable shape
    raw_cw = usage.get("cache_write_input_tokens")
    cw = NO_CACHE_WRITE if "cache_write_input_tokens" not in usage else _count(raw_cw)
    if cw is None:
        return None
    return Point(thread, inp, cached, cw, out, reasoning)


def leq(a: Point, b: Point) -> bool:
    """Every field of `a` <= the same field of `b` (the monotonic order of §3.3)."""
    ok = a.inp <= b.inp and a.cached <= b.cached and a.out <= b.out and a.reasoning <= b.reasoning
    if a.cw != NO_CACHE_WRITE and b.cw != NO_CACHE_WRITE:
        ok = ok and a.cw <= b.cw
    return ok


ZERO = "zero"


def interval(prev: Point | None, point: Point) -> tuple[dict[str, int], int, bool] | None:
    """(token deltas by normalized type, reasoning delta, cache_write_unknown) or None when not monotonic.
    K4: input = input_tokens - cached_input_tokens; cache_read = cached_input_tokens. `prev` None = baseline 0."""
    base = prev or Point(point.thread, 0, 0, 0, 0, 0)
    if not leq(base, point):
        return None
    d_input = (point.inp - point.cached) - (base.inp - base.cached)
    if d_input < 0:
        return None
    deltas = {"input": d_input, "cache_read": point.cached - base.cached, "output": point.out - base.out}
    unknown = point.cw == NO_CACHE_WRITE or base.cw == NO_CACHE_WRITE
    if not unknown:
        deltas["cache_write"] = point.cw - base.cw
    return deltas, point.reasoning - base.reasoning, unknown


# --------------------------------------------------------------------- run scripts and sidecars


@dataclass(frozen=True)
class ScriptFacts:
    stem: str
    model: str | None
    mode: str  # fresh | resume | unknown


def parse_script(path: Path) -> ScriptFacts | None:
    """Argv facts only: the stdout redirect target (names the stream), `-m`, and `resume` after `exec`."""
    try:
        with open_regular(path) as handle:
            raw = handle.read(MAX_SCRIPT_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_SCRIPT_BYTES:
        return None
    text = raw.decode("utf-8", "replace")
    stem, model, mode = None, None, "unknown"
    for line in text.splitlines():
        if "codex" not in line or "exec" not in line:
            continue
        match = REDIRECT.search(line)
        if match is None:
            continue
        stem = match.group(1)
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError:
            tokens = line.split()
        if "exec" in tokens:
            mode = "resume" if "resume" in tokens[tokens.index("exec") + 1:] else "fresh"
        for flag in ("-m", "--model"):
            if flag in tokens and tokens.index(flag) + 1 < len(tokens):
                model = safe_token(tokens[tokens.index(flag) + 1])
        break
    return ScriptFacts(stem, model, mode) if stem and STEM.match(stem) else None


def read_prestart(root: Path, stem: str) -> Point | None:
    """C-W1-4: the OPTIONAL launcher record `<stem>-codex-prestart.json` {thread_id, usage{raw fields}}."""
    data = read_json(root / f"{stem}-codex-prestart.json")
    if data is None:
        return None
    return parse_point(safe_token(data.get("thread_id")), data.get("usage"))


# --------------------------------------------------------------------- points in the ledger


def _row_point(row) -> Point:
    return Point(row[1], row[2], row[3], row[4], row[5], row[6])


_POINT_COLUMNS = "point_id,thread_id,input_tokens,cached,cache_write,output,reasoning,invocation_id,published"


def find_point(conn, point: Point):
    return conn.execute(
        f"SELECT {_POINT_COLUMNS} FROM codex_points WHERE thread_id=? AND input_tokens=? AND cached=? AND "
        "cache_write=? AND output=? AND reasoning=?",
        (point.thread, point.inp, point.cached, point.cw, point.out, point.reasoning)).fetchone()


def neighbours(conn, point: Point):
    """(previous, next) known points of the thread in tuple order; non-monotonic outliers (published=-1) are
    never neighbours."""
    rows = conn.execute(f"SELECT {_POINT_COLUMNS} FROM codex_points WHERE thread_id=? AND published>=0",
                        (point.thread,)).fetchall()
    ordered = sorted(rows, key=lambda r: _row_point(r).key)
    prev = max((r for r in ordered if _row_point(r).key < point.key), key=lambda r: _row_point(r).key, default=None)
    nxt = min((r for r in ordered if _row_point(r).key > point.key), key=lambda r: _row_point(r).key, default=None)
    return prev, nxt


def insert_point(conn, point: Point, *, invocation_id: str | None, alias_id: int | None, published: int,
                 prev_id: int | None = None) -> int:
    cursor = conn.execute(
        "INSERT INTO codex_points(thread_id,input_tokens,cached,cache_write,output,reasoning,invocation_id,"
        "alias_id,published,prev_point_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (point.thread, point.inp, point.cached, point.cw, point.out, point.reasoning, invocation_id, alias_id,
         published, prev_id))
    return cursor.lastrowid


@dataclass
class Placement:
    """Where a new point sits among the thread's known points, decided before anything is published."""
    kind: str  # duplicate | non_monotonic | late | anchor | interval
    prev: object = None  # the previous point row (or None)
    existing: object = None


def place(conn, point: Point) -> Placement:
    existing = find_point(conn, point)
    if existing is not None:
        return Placement("duplicate", existing=existing)
    prev, nxt = neighbours(conn, point)
    if prev is not None and not leq(_row_point(prev), point):
        return Placement("non_monotonic")
    if nxt is not None and not leq(point, _row_point(nxt)):
        return Placement("non_monotonic")
    if nxt is not None and nxt[8] == 1:
        return Placement("late", prev=prev)  # a later neighbour was already published: stored, never re-published (§3.3)
    return Placement("interval" if prev is not None else "anchor", prev=prev)


# --------------------------------------------------------------------- one run


@dataclass
class RunSpec:
    inv_id: str
    stem: str
    path: Path
    facts: ScriptFacts


def _model_label(facts: ScriptFacts) -> str:
    return normalize_model(facts.model).label


TAIL_PEEK_BYTES = 64 * 1024  # a terminal line is the last line of a run: only the stream's last bytes are inspected


def has_terminal_line(path: Path) -> bool:
    """F5: does the stream already carry its terminal evidence (a complete `turn.completed`/`turn.failed`/`error`
    line)? Reads at most `TAIL_PEEK_BYTES` from the end; a read-only peek that never changes the read offset."""
    try:
        with open_regular(path) as handle:
            size = handle.seek(0, 2)
            start = max(size - TAIL_PEEK_BYTES, 0)
            handle.seek(start)
            data = handle.read(TAIL_PEEK_BYTES)
    except OSError:
        return False
    lines = data.split(b"\n")[:-1]  # complete lines only
    if start > 0:
        lines = lines[1:]  # the first line of a mid-file window may be cut
    for raw in lines:
        obj = parse_line(raw)
        if obj is not None and obj["type"] in TERMINAL_LINES:
            return True
    return False


def _ensure(scan: Scan, spec: RunSpec) -> dict:
    existing = _inv(scan.conn, spec.inv_id)
    if existing:
        return existing
    try:
        modified = spec.path.lstat().st_mtime
    except OSError:
        modified = None
    history = stream_is_history(scan.live_since, modified, terminal=has_terminal_line(spec.path),
                                horizon_seconds=scan.codex_idle_seconds)
    label = normalize_model(spec.facts.model)
    scan.conn.execute(
        "INSERT INTO invocations(id,source,provider,requested_model_raw,executor_model_raw,executor_model,"
        "lifecycle_state,started_at,task_class,backfill) VALUES(?,?,?,?,?,?,'open',?,?,?)",
        (spec.inv_id, SOURCE, PROVIDER, spec.facts.model, spec.facts.model, label.label, scan.now,
         scan.registry.classify(spec.stem), int(history)))
    scan.conn.execute("INSERT INTO codex_runs(invocation_id,argv_mode) VALUES(?,?)", (spec.inv_id, spec.facts.mode))
    if label.recognized is False and spec.facts.model:
        _flag(scan.conn, spec.inv_id, "unrecognized", spec.facts.model)
    return _inv(scan.conn, spec.inv_id)  # type: ignore[return-value]


def ingest_run(scan: Scan, spec: RunSpec) -> StreamState:
    """Apply the new complete lines: `thread.started`, `turn.completed` (the point), `turn.failed`, `error`."""
    conn = scan.conn
    read = read_stream(scan, spec.path, source_alias=("canonical", spec.inv_id, "codex_run_script"), source=SOURCE)
    if read is None:
        return StreamState(False, True)
    alias_id, offset, complete, state = read
    run = conn.execute("SELECT thread_id,turn FROM codex_runs WHERE invocation_id=?", (spec.inv_id,)).fetchone()
    thread, turn = run
    for line_offset, raw in iter_lines(complete, offset):
        obj = parse_line(raw)
        if obj is None:
            note_malformed(conn, spec.path, line_offset, raw, "line", spec.inv_id, SOURCE)
            continue
        kind = obj["type"]
        if kind == "thread.started" and thread is None:
            thread = safe_token(obj.get("thread_id"))
            conn.execute("UPDATE codex_runs SET thread_id=? WHERE invocation_id=?", (thread, spec.inv_id))
        elif kind == "turn.completed" and turn is None:
            point = parse_point(thread, obj.get("usage"))
            turn = "completed"
            if point is None:
                conn.execute("UPDATE codex_runs SET turn='completed', usage_state='bad' WHERE invocation_id=?",
                             (spec.inv_id,))
            else:
                conn.execute(
                    "UPDATE codex_runs SET turn='completed', usage_state='ok', input_tokens=?, cached=?, "
                    "cache_write=?, output=?, reasoning=? WHERE invocation_id=?",
                    (point.inp, point.cached, point.cw, point.out, point.reasoning, spec.inv_id))
        elif kind in ("turn.failed", "error") and turn is None:
            turn = "failed"
            conn.execute("UPDATE codex_runs SET turn='failed' WHERE invocation_id=?", (spec.inv_id,))
    conn.execute("UPDATE codex_runs SET eof=? WHERE invocation_id=?", (int(state.at_eof), spec.inv_id))
    save_progress(conn, spec.path, alias_id, state.prefix_end, complete, first_chunk=offset == 0)
    return state


def _publish(conn, inv: dict, point: Point, deltas: dict[str, int], reasoning: int, kind: str, task_class: str,
             now: int) -> None:
    for tau, value in sorted(deltas.items()):
        publish_contribution(conn, key=f"{point.thread}:{point.text}", kind=kind, invocation_id=inv["id"],
                             provider=PROVIDER, model=inv["executor_model"], role=ROLE, source=SOURCE,
                             task_class=task_class, token_type=tau, value=value, now=now, backfill=inv["backfill"])
    if reasoning > 0:
        conn.execute(
            "INSERT OR IGNORE INTO reasoning_contributions(id,invocation_id,provider,model,role,source,task_class,"
            "value,published_at,backfill) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (f"{point.thread}:{point.text}|{kind}|{inv['executor_model']}", inv["id"], PROVIDER,
             inv["executor_model"], ROLE, SOURCE, task_class, reasoning, now, inv["backfill"]))


def finalize_run(scan: Scan, spec: RunSpec, state: StreamState, evidence: str) -> None:
    conn = scan.conn
    inv = _inv(conn, spec.inv_id)
    run = conn.execute("SELECT thread_id,argv_mode,turn,usage_state,input_tokens,cached,cache_write,output,reasoning "
                       "FROM codex_runs WHERE invocation_id=?", (spec.inv_id,)).fetchone()
    thread, mode, turn, usage_state = run[0], run[1], run[2], run[3]
    reasons: set[str] = set()
    if state.tail:
        settle_tail(conn, state, spec.path, inv, scan.now)
        reasons.add("incomplete_tail")
    if conn.execute("SELECT 1 FROM malformed_lines WHERE invocation_id=? AND kind='line' LIMIT 1",
                    (spec.inv_id,)).fetchone():
        reasons.add("malformed")
    if evidence == "horizon":
        reasons.add("terminal_unproven")
    outcome = {"completed": "codex_completed", "failed": "codex_failed"}.get(turn, "terminal_unproven")
    task_class, predecessor_state, share_reason = inv["task_class"], "none", None
    point = Point(thread, *run[4:6], run[6], *run[7:9]) if usage_state == "ok" and thread else None
    if turn != "completed" or usage_state == "none":
        reasons.add("no_result")
    elif point is None:
        reasons.add("malformed")
    if point is not None:
        placed = place(conn, point)
        if placed.kind == "duplicate":
            # A59(a): a shared point is counted once; this run's delta is 0.
            if placed.existing[7] is None:
                record_correction(conn, kind="duplicate_after_publish", invocation_id=spec.inv_id,
                                  detail="point_published_by_unbound_alias", dedupe_key=f"dup_point:{spec.inv_id}",
                                  now=scan.now)
        elif placed.kind == "non_monotonic":
            reasons.add("non_monotonic")
            share_reason = "non_monotonic"
            insert_point(conn, point, invocation_id=spec.inv_id, alias_id=None, published=-1)
        elif placed.kind == "late":
            # F4: stored and LINKED (previous known point, correction -> stored point); never published (§3.3).
            point_id = insert_point(conn, point, invocation_id=spec.inv_id, alias_id=None, published=1,
                                    prev_id=placed.prev[0] if placed.prev else None)
            record_correction(conn, kind="late_point", invocation_id=spec.inv_id, detail="before_published_point",
                              dedupe_key=f"late_point:{spec.inv_id}", now=scan.now, linked_ref=str(point_id))
        elif placed.kind == "anchor" and mode != "fresh":
            insert_point(conn, point, invocation_id=spec.inv_id, alias_id=None, published=1)
            reasons.add("no_baseline")  # §3.5: the first known point of a resumed thread is an anchor only
            share_reason, predecessor_state = "no_baseline", "missing"
        else:
            prev = placed.prev
            prev_point = _row_point(prev) if prev is not None else None
            moved = interval(prev_point, point)
            if moved is None:
                reasons.add("non_monotonic")
                share_reason = "non_monotonic"
                insert_point(conn, point, invocation_id=spec.inv_id, alias_id=None, published=-1)
            else:
                deltas, reasoning, cw_unknown = moved
                proven = prev is None  # a fresh `codex exec` first point: baseline 0, argv-proven
                if prev is not None:
                    pre = read_prestart(scan.source_root, spec.stem)
                    proven = pre is not None and pre == _row_point(prev)
                predecessor_state = "proven" if proven else "unproven"
                kind = "codex_delta" if proven else "codex_interval"
                if not proven:
                    task_class = "unattributed_interval"
                _publish(conn, inv, point, deltas, reasoning, kind, task_class, scan.now)
                if cw_unknown:  # C-W1-3: a share-detail record only; the other types are unaffected
                    conn.execute("INSERT OR IGNORE INTO unknown_shares(invocation_id,model,provider,reason) "
                                 "VALUES(?,?,?,?)", (spec.inv_id, inv["executor_model"], PROVIDER,
                                                     "unknown_version_semantics"))
                insert_point(conn, point, invocation_id=spec.inv_id, alias_id=None, published=1,
                             prev_id=prev[0] if prev else None)
    if share_reason:
        conn.execute("INSERT OR IGNORE INTO unknown_shares(invocation_id,model,provider,reason) VALUES(?,?,?,?)",
                     (spec.inv_id, inv["executor_model"], PROVIDER, share_reason))
    conn.execute("UPDATE invocations SET predecessor_state=?, task_class=?, session_or_thread=? WHERE id=?",
                 (predecessor_state, task_class, thread, spec.inv_id))
    close_invocation(conn, invocation_id=spec.inv_id, outcome=outcome, reason=primary_reason(reasons),
                     terminal_evidence="record_row" if evidence == "turn_line" else "horizon",
                     terminal_kind="turn_line" if evidence == "turn_line" else "horizon", now=scan.now)
    conn.execute("UPDATE read_state SET closed_size=? WHERE path=?", (state.size if state.exists else 0,
                                                                      str(spec.path)))


def _sort_key(scan: Scan, spec: RunSpec):
    """Thread, then the cumulative tuple, then a fresh run before a resumed one that reports the same point, so
    the file order never decides which run owns a shared point."""
    row = scan.conn.execute("SELECT thread_id,input_tokens,output,cached,reasoning,cache_write,argv_mode "
                            "FROM codex_runs WHERE invocation_id=?", (spec.inv_id,)).fetchone()
    point_key = (row[1], row[2], row[3], row[4], row[5]) if row[1] is not None else (1 << 62,) * 5
    return (row[0] or "", point_key, 0 if row[6] == "fresh" else 1, spec.stem)


def run_specs(scan: Scan) -> list[RunSpec]:
    specs: dict[str, RunSpec] = {}
    for script in sorted(scan.source_root.glob("*-codex-run.sh")):
        if script.is_symlink() or not script.is_file():
            continue
        facts = parse_script(script)
        if facts is None:
            continue
        path = scan.source_root / f"{facts.stem}-codex-events.jsonl"
        if path.is_file() and not path.is_symlink():
            specs.setdefault(f"codex:{facts.stem}", RunSpec(f"codex:{facts.stem}", facts.stem, path, facts))
    return list(specs.values())


def scan_codex(scan: Scan) -> list[tuple[Path, str]]:
    """Phase 1 reads every canonical run; phase 2 finalizes the due runs in tuple order. Returns alias candidates."""
    root = scan.source_root
    scan.ledger.set_meta("source_up.codex_exec", 1 if root.is_dir() else 0)
    specs = run_specs(scan)
    due: list[tuple[RunSpec, StreamState, str]] = []
    for spec in specs:
        with scan.ledger.transaction() as conn:
            inv = _ensure(scan, spec)
            if inv["lifecycle_state"] == "finalized":
                late_tail_check(scan, inv, spec.path)
                from .late import record_late_facts  # late.py builds on this module's readers (F4)

                record_late_facts(scan, inv, spec.path)
                continue
            state = ingest_run(scan, spec)
            turn = conn.execute("SELECT turn FROM codex_runs WHERE invocation_id=?", (spec.inv_id,)).fetchone()[0]
            try:
                idle = scan.now - spec.path.lstat().st_mtime
            except OSError:
                idle = 0
            if turn is not None:
                evidence = "turn_line"
            elif idle > scan.codex_idle_seconds:
                evidence = "horizon"
            else:
                continue
            if not state.at_eof:
                conn.execute("UPDATE invocations SET lifecycle_state='terminal_observed' WHERE id=?", (spec.inv_id,))
                continue
            due.append((spec, state, evidence))
    due.sort(key=lambda item: _sort_key(scan, item[0]))
    for spec, state, evidence in due:
        with scan.ledger.transaction():
            finalize_run(scan, spec, state, evidence)
    canonical = {spec.path for spec in specs}
    return [(path, SOURCE) for path in sorted(root.glob("*-codex-events.jsonl"))
            if path not in canonical and path.is_file() and not path.is_symlink()]


def publish_unbound_point(scan: Scan, alias_id: int, point: Point, history: bool) -> None:
    """C-W1-2/A59(b): a point of an unbound alias, not known to any canonical stream, publishes as
    `identity_unavailable` against the previous known point; it creates no invocation, outcome or unknown."""
    conn = scan.conn
    placed = place(conn, point)
    if placed.kind == "duplicate":
        return
    if placed.kind == "non_monotonic":
        insert_point(conn, point, invocation_id=None, alias_id=alias_id, published=-1)
        return
    insert_point(conn, point, invocation_id=None, alias_id=alias_id, published=1)
    if placed.kind != "interval":
        return  # anchor or late: stored, nothing to publish
    moved = interval(_row_point(placed.prev), point)
    if moved is None:
        return
    deltas, reasoning, _unknown = moved
    key = f"{point.thread}:{point.text}"
    for tau, value in sorted(deltas.items()):
        if value > 0:
            conn.execute(
                "INSERT OR IGNORE INTO unbound_contributions(id,provider,model,role,source,task_class,token_type,"
                "value,published_at,backfill) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (f"{key}|other|{tau}", PROVIDER, "other", ROLE, SOURCE, IDENTITY_UNAVAILABLE, tau, value, scan.now,
                 int(history)))
    if reasoning > 0:
        conn.execute(
            "INSERT OR IGNORE INTO reasoning_contributions(id,invocation_id,provider,model,role,source,task_class,"
            "value,published_at,backfill) VALUES(?,NULL,?,?,?,?,?,?,?,?)",
            (f"{key}|alias|other", PROVIDER, "other", ROLE, SOURCE, IDENTITY_UNAVAILABLE, reasoning, scan.now,
             int(history)))
