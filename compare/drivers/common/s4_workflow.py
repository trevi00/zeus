"""Shared S4 scenario steps (`coordination.workflow_lease`): the workflow owner operations RunTask and
ReviewDecisions write through (lead decision Option A): claim, _owned, heartbeat, remaining_seconds, complete,
fail (retry and contained), the stale holder after a re-claim, and the guards.

Layer: harness (never shipped)

`api` supplies MemoryStore, `workflow(store)` (the side's Workflow bound to the packaged organization and, on
the target, the injected clock/ids/ticket binding), `envelope(...)` (the side's six-W constructor),
`ExecutionFailure`, `advance(seconds)` and `org`. Task rows are inserted in the exact shape M7 `submit` writes
(submit itself parks terminal operations and moves with S5). Values/refusals and the final store records (by
body digest) are compared; the adoption check is not reached (no plan/implement task).
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
    if isinstance(value, dict):
        return {"value": {k: value.get(k) for k in ("id", "status", "attempt", "generation", "lease_owner",
                                                     "lease_until", "error", "retry_budget", "attempt_outcomes",
                                                     "execution_clock", "failure_receipt")}}
    return {"value": value}


def queued(api, store, tid, agent="worker:implementation", action="rebase", created="2026-01-01T00:00:00+00:00"):
    message = api.envelope("task.assign", "lead:improvement", agent, action, {"n": tid}, "corr-" + tid)
    message["message_id"] = tid
    task = {"id": tid, "message": message, "input_hash": canonical_digest(message), "agent": agent,
            "status": "queued", "attempt": 0, "generation": 0, "lease_until": None, "lease_owner": None,
            "result": None, "error": None, "created_at": created}
    with store.transaction() as tx:
        tx.put("tasks", tid, task)
    return task


def run(api) -> dict:
    out = {}
    store = api.MemoryStore()
    wf = api.workflow(store)
    queued(api, store, "t1")
    queued(api, store, "t2", agent="worker:github")
    api.advance(1)
    claimed = wf.claim("worker:implementation", "owner-a")
    out["claim"] = call(lambda: claimed)
    out["claim_busy_agent"] = call(wf.claim, "worker:implementation", "owner-b")
    out["claim_bad_owner"] = call(wf.claim, "worker:github", " ")
    out["claim_guard_missing"] = call(wf.claim, "worker:github", "owner-c",
                                      expected={"id": "nope", "correlation_id": "x", "statuses": ["queued"]})
    api.advance(5)
    out["heartbeat"] = call(wf.heartbeat, claimed)
    out["remaining"] = call(wf.remaining_seconds, claimed, 600)
    with store.transaction() as tx:
        out["owned"] = call(wf._owned, tx, claimed)
    api.advance(5)
    out["complete"] = call(wf.complete, claimed, {"summary": "done"}, [])
    out["complete_again_stale"] = call(wf.complete, claimed, {"summary": "again"}, [])
    second = wf.claim("worker:github", "owner-c")
    out["claim_second"] = call(lambda: second)
    api.advance(2)
    out["fail_retry"] = call(wf.fail, second, "boom", True)
    out["fail_replay"] = call(wf.fail, second, "boom", True)
    api.advance(2)
    third = wf.claim("worker:github", "owner-d")
    out["reclaim"] = call(lambda: third)
    with store.transaction() as tx:
        out["stale_holder_owned"] = call(wf._owned, tx, second)
    out["stale_holder_heartbeat"] = call(wf.heartbeat, second)
    contained = api.ExecutionFailure("codex-provider-usage-limit-exceeded", {"cause": "codex-provider-usage-limit-exceeded"})
    out["fail_contained"] = call(wf.fail_execution, third, contained)
    out["fail_bad_evidence"] = call(wf.fail, third, "x", True, {"v": float("nan")})
    queued(api, store, "t3", created="bad")
    out["claim_invalid_order"] = call(wf.claim, "worker:implementation", "owner-e")
    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out
