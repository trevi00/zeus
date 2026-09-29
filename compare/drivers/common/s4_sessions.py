"""Shared S4 scenario steps (`coordination.session_checkpoints`): M7 `Harness.checkpoint`, the only M7 writer of
`sessions` (lead decision Option A: RunTask's turn loop checkpoints through it). An unknown agent and incomplete state
are refused before any read; the first and second checkpoints advance the generation; a stale writer is refused; a
checkpoint bound to a claimed execution commits only while that execution still holds its lease.

Layer: harness (never shipped)

`api` supplies MemoryStore, `workflow(store)` (the side's Workflow, as in s4_submit), `checkpoints(store)` (the side's
checkpoint owner), `envelope(...)` and `advance(seconds)`. Values/refusals and the final store records (by body
digest) are compared.
"""

from __future__ import annotations

import hashlib
import json


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    return {"value": value}


def run(api) -> dict:
    out = {}
    store = api.MemoryStore()
    wf = api.workflow(store)
    cp = api.checkpoints(store)
    st = {"next_action": "a", "source_revision": "r", "graph_snapshot": "g"}
    out["unknown_agent"] = call(cp.checkpoint, "nobody", 0, st)
    out["incomplete"] = call(cp.checkpoint, "lead:improvement", 0, {"next_action": "a"})
    out["first"] = call(cp.checkpoint, "lead:improvement", 0, st)
    out["stale"] = call(cp.checkpoint, "lead:improvement", 0, st)
    out["second"] = call(cp.checkpoint, "lead:improvement", 1, st)
    plan = api.envelope("task.assign", "conductor", "lead:improvement", "plan", {"plan": {"objective": "x"}}, "corr-1")
    wf.submit(plan)
    api.advance(1)
    claimed = wf.claim("lead:improvement", "owner-a")
    out["with_execution"] = call(cp.checkpoint, "lead:improvement", 2, st, execution=claimed)
    with store.transaction() as tx:  # a re-claim advances the row's generation, as drivers/common/s4_workflow.py does
        row = tx.get("tasks", claimed["id"])
        tx.put("tasks", claimed["id"], {**row, "generation": row["generation"] + 1})
    out["stale_execution"] = call(cp.checkpoint, "lead:improvement", 3, st, execution=claimed)
    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out
