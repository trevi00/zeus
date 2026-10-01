"""`tokobs report --task`: one task's invocations, contributions and corrections.

Purpose: operator inspection of the ledger for a single task. Layer: tooling. Owns: DESIGN §4 report shape
(ids, enums and numbers only; no text field exists in the ledger to print). Does-not-own: any write.
Implements: ACCEPTANCE A10/A11 (attempts, rework, task tokens), A24 (no text), §3.3 late-arrival visibility.
W1b adds the refined allocation of late Codex points/predecessors.
"""

from __future__ import annotations

import json
import sqlite3

from .ledger import Ledger


def task_report(ledger: Ledger, task_id: str) -> dict | None:
    conn = ledger.conn
    conn.row_factory = sqlite3.Row
    try:
        task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        invocations = conn.execute("SELECT * FROM invocations WHERE task_id=? ORDER BY attempt", (task_id,)).fetchall()
        if task is None and not invocations:
            return None
        report: dict = {
            "task_id": task_id,
            "task": dict(task) if task else None,
            "rework": max(len(invocations) - 1, 0),
            "invocations": [],
        }
        for inv in invocations:
            contributions = conn.execute(
                "SELECT kind,provider,model,role,token_type,SUM(value) AS value FROM contributions "
                "WHERE invocation_id=? GROUP BY kind,provider,model,role,token_type ORDER BY kind,model,role,token_type",
                (inv["id"],)).fetchall()
            corrections = conn.execute(
                "SELECT kind,detail_enum,recorded_at FROM corrections WHERE invocation_id=? ORDER BY seq",
                (inv["id"],)).fetchall()
            shares = conn.execute("SELECT model,reason FROM unknown_shares WHERE invocation_id=? ORDER BY model",
                                  (inv["id"],)).fetchall()
            costs = conn.execute("SELECT model,usd FROM cost_contributions WHERE invocation_id=? ORDER BY model",
                                 (inv["id"],)).fetchall()
            report["invocations"].append({
                **dict(inv),
                "consultations": conn.execute("SELECT COUNT(*) FROM advisor_consultations WHERE invocation_id=?",
                                              (inv["id"],)).fetchone()[0],
                "contributions": [dict(r) for r in contributions],
                "estimated_cost_usd": [dict(r) for r in costs],
                "unknown_shares": [dict(r) for r in shares],
                "corrections": [dict(r) for r in corrections],
            })
        report["task_token_snapshot"] = [dict(r) for r in conn.execute(
            "SELECT role,token_type,value FROM task_token_snapshots WHERE task_id=? ORDER BY role,token_type",
            (task_id,))]
        return report
    finally:
        conn.row_factory = None


def render_report(report: dict) -> str:
    return json.dumps(report, indent=1, sort_keys=True) + "\n"
