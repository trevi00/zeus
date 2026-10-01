"""Append-only publication, unknown accounting, corrections and finalization bookkeeping.

Purpose: the write primitives every source uses. Layer: tooling. Owns: DESIGN §3.6 (append-only contributions,
at most one unknown per finalized invocation in the same transaction as the outcome, corrections that never edit
contributions), the finalization step itself. Does-not-own: reading streams or deciding outcomes (the source module)
and exposition text (render).
Implements: ACCEPTANCE A02, A03, A06, A07, A14, A39, A42, A44; the "counters never decrease" guarantee comes from
`contributions` having UPDATE/DELETE triggers (ledger.py) and every counter being a Σ over those rows.
"""

from __future__ import annotations

import sqlite3

from .partition import Plan
from .vocab import primary_reason


def contribution_id(key: str, kind: str, model: str, token_type: str) -> str:
    return f"{key}|{kind}|{model}|{token_type}"


def publish_contribution(conn: sqlite3.Connection, *, key: str, kind: str, invocation_id: str, provider: str,
                         model: str, role: str, source: str, task_class: str, token_type: str, value: int,
                         now: int, backfill: int = 0) -> bool:
    """Insert one immutable contribution. A repeated accounting key adds nothing (idempotent replay)."""
    if value <= 0:
        return False
    cursor = conn.execute(
        "INSERT OR IGNORE INTO contributions(id,invocation_id,kind,provider,model,role,source,task_class,"
        "token_type,value,published_at,backfill) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (contribution_id(key, kind, model, token_type), invocation_id, kind, provider, model, role, source,
         task_class, token_type, int(value), now, backfill))
    return cursor.rowcount == 1


def record_correction(conn: sqlite3.Connection, *, kind: str, invocation_id: str | None, detail: str,
                      dedupe_key: str, now: int) -> bool:
    """Ledger correction (§3.6): counted separately, never edits a contribution. Idempotent by `dedupe_key`."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO corrections(dedupe_key,kind,invocation_id,detail_enum,recorded_at) VALUES(?,?,?,?,?)",
        (dedupe_key, kind, invocation_id, detail, now))
    return cursor.rowcount == 1


def finalize_invocation(conn: sqlite3.Connection, *, invocation_id: str, outcome: str, reasons: set[str],
                        plan: Plan, source: str, task_class: str, terminal_evidence: str, advisor_state: str,
                        receipt_ok: int | None, worker_status: str | None, now: int) -> str | None:
    """Finalize exactly once: outcome, the one primary unknown reason, tree-remainder contributions, cost and
    share detail all commit in the caller's single transaction. Returns the primary reason (or None).

    The remainder is published only when no reason applies (§3.4 step 6); otherwise only `main_result`
    contributions exist and the remainder is the process's one unknown."""
    row = conn.execute("SELECT lifecycle_state, provider, backfill FROM invocations WHERE id=?",
                       (invocation_id,)).fetchone()
    if row is None or row[0] == "finalized":
        return None
    provider, backfill = row[1], row[2]
    reason = primary_reason(plan.reasons | reasons)
    if reason is None:
        for model, role, tau, value in plan.remainder:
            publish_contribution(conn, key=invocation_id, kind="tree_remainder", invocation_id=invocation_id,
                                 provider=provider, model=model,
                                 role=role, source=source, task_class=task_class, token_type=tau, value=value,
                                 now=now, backfill=backfill)
        for model, usd in sorted(plan.costs.items()):
            conn.execute(
                "INSERT OR IGNORE INTO cost_contributions(id,invocation_id,provider,model,source,task_class,usd,"
                "published_at,backfill) VALUES(?,?,?,?,?,?,?,?,?)",
                (f"{invocation_id}|cost|{model}", invocation_id, provider, model, source, task_class, usd, now,
                 backfill))
    else:
        for model in plan.share_models:
            conn.execute("INSERT OR IGNORE INTO unknown_shares(invocation_id,model,provider,reason) VALUES(?,?,?,?)",
                         (invocation_id, model, provider, reason))
    if plan.cumulative:
        for model, cum in sorted(plan.cumulative.items()):
            conn.execute(
                "INSERT OR REPLACE INTO cumulative(invocation_id,model,input,output,cache_read,cache_write,"
                "cost_usd) VALUES(?,?,?,?,?,?,?)",
                (invocation_id, model, int(cum["input"]), int(cum["output"]), int(cum["cache_read"]),
                 int(cum["cache_write"]), float(cum.get("cost_usd", 0.0))))
    conn.execute(
        "UPDATE invocations SET lifecycle_state='finalized', outcome=?, unknown_reason=?, terminal_evidence=?, "
        "finalized_at=?, advisor_state=?, receipt_ok=?, worker_status=? WHERE id=?",
        (outcome, reason, terminal_evidence, now, advisor_state, receipt_ok, worker_status, invocation_id))
    return reason
