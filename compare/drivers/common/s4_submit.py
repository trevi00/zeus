"""Shared S4 scenario steps (`coordination.workflow_submit`): M7 `Workflow.submit` (lead decision Option A: every
RunTask scenario and later coordination flow submits through it). Valid plan/implement assignments, the replay
(old row), the conflicting body, non-assignments, unauthorized edges, deadline and dependency refusals, a used
execution fence, and the adoption gate refusing a proposal without a retained approval.

Layer: harness (never shipped)

`api` supplies MemoryStore, `workflow(store)` (the side's Workflow bound to the packaged organization, the side's
adoption gate and terminal-operation parking), `envelope(...)` (the side's six-W constructor), `advance(seconds)`
and `org`. This scenario creates no operations, so parking returns None for every message. Values/refusals and the
final store records (by body digest) are compared.
"""

from __future__ import annotations

import copy
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
                                                     "lease_until", "error", "agent", "input_hash", "created_at",
                                                     "result")}}
    return {"value": value}


def run(api) -> dict:
    out = {}
    store = api.MemoryStore()
    wf = api.workflow(store)
    plan = api.envelope("task.assign", "conductor", "lead:improvement", "plan", {"plan": {"objective": "x"}}, "corr-1")
    out["plan"] = call(wf.submit, plan)
    api.advance(3)
    out["replay"] = call(wf.submit, copy.deepcopy(plan))
    conflicting = copy.deepcopy(plan)
    conflicting["what"]["details"] = {"plan": {"objective": "changed"}}
    out["conflict"] = call(wf.submit, conflicting)
    implement = api.envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                             {"plan": {"objective": "y"}}, "corr-2")
    out["implement"] = call(wf.submit, implement)
    result = api.envelope("task.result", "worker:implementation", "lead:improvement", "implement",
                          {"summary": "done"}, "corr-3")
    out["not_assignment"] = call(wf.submit, result)
    unauthorized = api.envelope("task.assign", "worker:implementation", "conductor", "plan",
                                {"plan": {"objective": "z"}}, "corr-4")
    out["unauthorized"] = call(wf.submit, unauthorized)
    bad_deadline = api.envelope("task.assign", "conductor", "lead:improvement", "plan",
                                {"plan": {"objective": "d"}}, "corr-5")
    bad_deadline["when"]["deadline"] = "not-a-time"
    out["bad_deadline"] = call(wf.submit, bad_deadline)
    self_dependency = api.envelope("task.assign", "conductor", "lead:improvement", "plan",
                                   {"plan": {"objective": "s"}}, "corr-6")
    self_dependency["when"]["after"] = [self_dependency["message_id"]]
    out["self_dependency"] = call(wf.submit, self_dependency)
    missing = api.envelope("task.assign", "conductor", "lead:improvement", "plan",
                           {"plan": {"objective": "m"}}, "corr-7")
    missing["when"]["after"] = ["nope"]
    out["missing_dependency"] = call(wf.submit, missing)
    dependent = api.envelope("task.assign", "conductor", "lead:improvement", "plan",
                             {"plan": {"objective": "w"}}, "corr-8")
    dependent["when"]["after"] = [plan["message_id"]]
    out["with_dependency"] = call(wf.submit, dependent)
    fenced = api.envelope("task.assign", "conductor", "lead:improvement", "plan",
                          {"plan": {"objective": "f"}}, "corr-9")
    with store.transaction() as tx:
        tx.put("execution_fences", "tasks:" + fenced["message_id"],
               {"id": "tasks:" + fenced["message_id"], "bucket": "tasks", "row_id": fenced["message_id"],
                "generation": 1, "owner": "owner-a", "at": "2026-01-01T00:00:00+00:00"})
    out["fence_used"] = call(wf.submit, fenced)
    research = api.envelope("task.assign", "conductor", "lead:improvement", "plan", {"proposal": {}}, "corr-10")
    out["research_plan"] = call(wf.submit, research)
    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out
