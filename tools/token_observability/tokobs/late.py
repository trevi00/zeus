"""Late facts: correction-only storage, links and the unpublished refinement (DESIGN §3.2 step 4, §3.3, §3.6; F4).

Purpose: facts that arrive after the invocation they belong to finalized are never discarded to a byte count. A
bounded, allowlisted subset (ids, enums, numbers) is stored in correction-only tables, linked to what it refines, and
shown by the report as a refined or a still-unknown allocation. Layer: tooling.
Owns: reading the bytes past a finalized stream's offset, `late_results`/`late_codex_terminal`, the
`late_predecessor` link, the refinement arithmetic (read-only). Does-not-own: contributions, outcomes, unknowns or
counters; nothing in this module updates or adds to them. A late result is NEVER a new published contribution and a
late terminal never changes a finalized outcome (settled-tail rule, §3.2 step 4).
Implements: ACCEPTANCE A44, A45, A46 (the stored, linked and reported part), A58; REVIEW-W1-r1 F4.

The refinement of a successor reuses `resumed_baseline` and `plan_partition`, the same rules as a finalization, so
"refined" is exactly what the finalization would have published had the predecessor been known; "still unknown" is
reported when those rules still refuse (an accounting reason).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .partition import plan_partition
from .publication import record_correction
from .s1_routine import (
    Scan,
    _first_line_hash,
    _identity_changed,
    _results,
    iter_lines,
    open_regular,
    parse_line,
    parse_result,
    parse_version,
    read_stream,
    resumed_baseline,
    save_progress,
    version_semantics_of,
)
from .s3_codex import TERMINAL_LINES, interval, neighbours, parse_point
from .vocab import SEMANTICS_UNCHARACTERIZED, TOKEN_TYPES, normalize_model, primary_reason

PROVENANCE = {"routine": "dispatch_record", "lane": "run_metadata", "coordinator": "credential_receipt",
              "codex_exec": "codex_run_script"}


def read_late(scan: Scan, inv: dict, path: Path) -> list[tuple[int, bytes]]:
    """Complete lines past the persisted offset of a finalized invocation's stream (one bounded chunk per scan,
    the offset persisted in the same transaction). A changed read identity (rotation, truncation) is not read: its
    bytes stay a `late_tail` growth fact only (A16)."""
    conn = scan.conn
    rs = conn.execute("SELECT alias_id,dev,ino,head_sha256,offset FROM read_state WHERE path=?",
                      (str(path),)).fetchone()
    try:
        with open_regular(path) as handle:
            st = os.fstat(handle.fileno())
        if rs is not None:
            if st.st_size <= rs[4]:
                return []  # nothing past the offset: the common case costs one open and no read
            if _identity_changed(rs, st, _first_line_hash(path) if rs[4] > 0 else None, st.st_size):
                return []
    except OSError:
        return []
    read = read_stream(scan, path, source_alias=("canonical", inv["id"], PROVENANCE[inv["source"]]),
                       source=inv["source"])
    if read is None:
        return []
    alias_id, offset, complete, state = read
    save_progress(conn, path, alias_id, state.prefix_end, complete, first_chunk=offset == 0)
    return list(iter_lines(complete, offset))


def record_late_facts(scan: Scan, inv: dict, path: Path) -> None:
    """Called for a finalized invocation on every scan, inside the caller's transaction."""
    if inv["source"] == "codex_exec":
        _late_codex_terminal(scan, inv, path)
    else:
        _late_claude_results(scan, inv, path)


def _late_claude_results(scan: Scan, inv: dict, path: Path) -> None:
    conn = scan.conn
    for _offset, raw in read_late(scan, inv, path):
        obj = parse_line(raw)
        if obj is None or obj["type"] != "result":
            continue
        parsed = parse_result(obj, raw, inv["session_or_thread"])
        if conn.execute("SELECT 1 FROM results WHERE session_id=? AND uuid=?",
                        (parsed.session_id, parsed.uuid)).fetchone():
            continue  # already published through the stream itself: nothing late about it
        usage = parsed.usage or {}
        cursor = conn.execute(
            "INSERT OR IGNORE INTO late_results(invocation_id,session_id,uuid,zeroed,usage_ok,input,output,"
            "cache_read,cache_write,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (inv["id"], parsed.session_id, parsed.uuid, int(parsed.zeroed), int(parsed.usage is not None),
             usage.get("input"), usage.get("output"), usage.get("cache_read"), usage.get("cache_write"), scan.now))
        if cursor.rowcount != 1 or parsed.zeroed:
            continue
        for model, cum in sorted((parsed.models or {}).items()):
            conn.execute("INSERT INTO late_result_models(late_id,model,input,output,cache_read,cache_write,cost_usd) "
                         "VALUES(?,?,?,?,?,?,?)",
                         (cursor.lastrowid, model, int(cum["input"]), int(cum["output"]), int(cum["cache_read"]),
                          int(cum["cache_write"]), cum["cost_usd"]))


def _late_codex_terminal(scan: Scan, inv: dict, path: Path) -> None:
    """A Codex run finalized by its idle horizon whose terminal line arrives later: recognized once, idempotently,
    as `late_terminal` (distinct from the `late_tail` growth fact); the outcome and counters stay as finalized."""
    conn = scan.conn
    run = conn.execute("SELECT thread_id,turn FROM codex_runs WHERE invocation_id=?", (inv["id"],)).fetchone()
    if run is None or run[1] is not None or inv["terminal_evidence"] != "horizon":
        return
    for _offset, raw in read_late(scan, inv, path):
        obj = parse_line(raw)
        if obj is None or obj["type"] not in TERMINAL_LINES:
            continue
        turn = "completed" if obj["type"] == "turn.completed" else "failed"
        point = parse_point(run[0], obj.get("usage")) if turn == "completed" else None
        state = "none" if turn == "failed" else ("ok" if point is not None else "bad")
        values = (point.inp, point.cached, point.cw, point.out, point.reasoning) if point else (None,) * 5
        if conn.execute("INSERT OR IGNORE INTO late_codex_terminal(invocation_id,turn,thread_id,usage_state,"
                        "input_tokens,cached,cache_write,output,reasoning,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (inv["id"], turn, run[0], state, *values, scan.now)).rowcount == 1:
            record_correction(conn, kind="late_terminal", invocation_id=inv["id"],
                              detail="codex_completed" if turn == "completed" else "codex_failed",
                              dedupe_key=f"late_terminal:{inv['id']}", now=scan.now)
        return


def link_late_predecessors(scan: Scan) -> None:
    """A finalized successor whose predecessor was MISSING at its finalization (`no_baseline`) gets a
    `late_predecessor` correction, linked to the predecessor, once that predecessor offers numbers: late result
    lines of a finalized stream, or a predecessor invocation that was only discovered and finalized afterwards."""
    conn = scan.conn
    rows = conn.execute(
        "SELECT s.id, p.id FROM invocations s JOIN invocations p ON p.id = s.predecessor_id "
        "WHERE s.lifecycle_state='finalized' AND s.predecessor_state='missing' AND p.lifecycle_state='finalized' "
        "AND (EXISTS (SELECT 1 FROM late_results lr JOIN late_result_models m USING(late_id) "
        "            WHERE lr.invocation_id=p.id) "
        "     OR (p.finalized_at > s.finalized_at AND EXISTS (SELECT 1 FROM cumulative c WHERE c.invocation_id=p.id))) "
        "ORDER BY s.id").fetchall()
    for successor, predecessor in rows:
        record_correction(conn, kind="late_predecessor", invocation_id=successor, detail="predecessor_arrived",
                          dedupe_key=f"late_predecessor:{successor}:{predecessor}", now=scan.now,
                          linked_ref=predecessor)


# --------------------------------------------------------------------- refinement (read-only, report side)


def _baseline_models(conn: sqlite3.Connection, predecessor: str) -> tuple[str, str, dict[str, dict[str, float]]]:
    """(source, proof state, models) of the predecessor: the newest non-zeroed late result's modelUsage, else its own
    finalized cumulative. The proof state applies the ordinary zeroed-crash continuity refusal (`_predecessor`,
    s1_routine) to the ordinary AND the late results of the predecessor: a zeroed one may hide spend, so an earlier
    nonzero model row never proves the baseline."""
    zeroed = conn.execute("SELECT 1 FROM results WHERE invocation_id=?1 AND zeroed=1 UNION ALL "
                          "SELECT 1 FROM late_results WHERE invocation_id=?1 AND zeroed=1", (predecessor,)).fetchone()
    proof = "unproven" if zeroed else "proven"
    late = conn.execute("SELECT lr.late_id FROM late_results lr WHERE lr.invocation_id=? AND lr.zeroed=0 AND EXISTS "
                        "(SELECT 1 FROM late_result_models m WHERE m.late_id=lr.late_id) ORDER BY lr.late_id DESC "
                        "LIMIT 1", (predecessor,)).fetchone()
    if late is not None:
        rows = conn.execute("SELECT model,input,output,cache_read,cache_write,cost_usd FROM late_result_models "
                            "WHERE late_id=?", (late[0],)).fetchall()
        return "late_result", proof, {r[0]: dict(zip((*TOKEN_TYPES, "cost_usd"), r[1:], strict=True)) for r in rows}
    rows = conn.execute("SELECT model,input,output,cache_read,cache_write,cost_usd FROM cumulative "
                        "WHERE invocation_id=?", (predecessor,)).fetchall()
    return "predecessor_cumulative", proof, {r[0]: dict(zip((*TOKEN_TYPES, "cost_usd"), r[1:], strict=True)) for r in rows}


def refine_successor(conn: sqlite3.Connection, inv: dict) -> dict | None:
    """What the finalization would have published had the late predecessor been known. Nothing is written."""
    links = conn.execute("SELECT linked_ref FROM corrections WHERE kind='late_predecessor' AND invocation_id=? "
                         "ORDER BY seq", (inv["id"],)).fetchall()
    if not links:
        return None
    predecessor = links[-1][0]
    source, proof, baseline_models = _baseline_models(conn, predecessor)
    answer: dict = {"predecessor": predecessor, "baseline_source": source, "published": False}
    if not baseline_models:
        return {**answer, "state": "still_unknown", "reason": "no_baseline", "remainder": []}
    external = set()
    if version_semantics_of(inv) == SEMANTICS_UNCHARACTERIZED or parse_version(inv["cli_version"]) is None:
        external.add("unknown_version_semantics")
    executor = inv["executor_model"] or normalize_model(inv["requested_model_raw"]).label
    consultations = conn.execute("SELECT COUNT(*) FROM advisor_consultations WHERE invocation_id=?",
                                 (inv["id"],)).fetchone()[0]
    plan = plan_partition(_results(conn, inv["id"]), executor, inv["advisor_model"], consultations,
                          resumed_baseline(inv, proof, baseline_models), external)
    if plan.share_models or not plan.cumulative:
        return {**answer, "state": "still_unknown", "reason": primary_reason(plan.reasons) or "no_result",
                "remainder": []}
    return {**answer, "state": "refined", "reason": None,
            "remainder": [{"model": m, "role": r, "token_type": t, "value": v} for m, r, t, v in plan.remainder]}


def _point_facts(row) -> dict:
    return {"point_id": row[0], "input_tokens": row[2], "cached": row[3], "cache_write": row[4], "output": row[5],
            "reasoning": row[6], "invocation_id": row[7], "published": row[8]}


def refine_late_points(conn: sqlite3.Connection, inv: dict) -> list[dict]:
    """For each `late_point` correction of a Codex run: the stored point, its neighbours in tuple order, and the two
    intervals that split the already published interval (never published again, §3.3)."""
    from .s3_codex import _row_point

    out = []
    for (point_id,) in conn.execute("SELECT linked_ref FROM corrections WHERE kind='late_point' AND "
                                    "invocation_id=? ORDER BY seq", (inv["id"],)).fetchall():
        row = conn.execute("SELECT point_id,thread_id,input_tokens,cached,cache_write,output,reasoning,"
                           "invocation_id,published FROM codex_points WHERE point_id=?", (point_id,)).fetchone()
        if row is None:
            continue
        point = _row_point(row)
        prev, nxt = neighbours(conn, point)
        item: dict = {"point": _point_facts(row), "published": False}
        before = interval(_row_point(prev), point) if prev is not None else None
        after = interval(point, _row_point(nxt)) if nxt is not None else None
        item["previous_point_id"] = prev[0] if prev is not None else None
        item["next_point_id"] = nxt[0] if nxt is not None else None
        if before is None or after is None:
            item.update(state="still_unknown", reason="no_previous_point" if prev is None else "no_next_point")
        else:
            item.update(state="refined",
                        before={"deltas": before[0], "reasoning": before[1], "cache_write_unknown": before[2]},
                        after={"deltas": after[0], "reasoning": after[1], "cache_write_unknown": after[2]})
        out.append(item)
    return out


def late_terminal_facts(conn: sqlite3.Connection, inv_id: str) -> dict | None:
    row = conn.execute("SELECT turn,thread_id,usage_state,input_tokens,cached,cache_write,output,reasoning "
                       "FROM late_codex_terminal WHERE invocation_id=?", (inv_id,)).fetchone()
    if row is None:
        return None
    keys = ("turn", "thread_id", "usage_state", "input_tokens", "cached", "cache_write", "output", "reasoning")
    return dict(zip(keys, row, strict=True))


def late_results_facts(conn: sqlite3.Connection, inv_id: str) -> list[dict]:
    out = []
    for late_id, zeroed, *numbers in conn.execute(
            "SELECT late_id,zeroed,input,output,cache_read,cache_write FROM late_results WHERE invocation_id=? "
            "ORDER BY late_id", (inv_id,)).fetchall():
        models = conn.execute("SELECT model,input,output,cache_read,cache_write,cost_usd FROM late_result_models "
                              "WHERE late_id=? ORDER BY model", (late_id,)).fetchall()
        out.append({"zeroed": bool(zeroed), "usage": dict(zip(TOKEN_TYPES, numbers, strict=True)),
                    "cumulative": [dict(zip(("model", *TOKEN_TYPES, "cost_usd"), m, strict=True)) for m in models]})
    return out

