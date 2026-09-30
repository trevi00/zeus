"""Shared S5 scenario steps (`coordination.workflow_handle`): M7 `Workflow.handle`, `cancel`, `request_rebase` and
`context` (RESEARCH-S5 D1, local check (a)).

- **handle.** Reports are consumed once. A replay returns the stored result, the same id with other content refuses,
  and an unproven task/decision result refuses. Research reports record a topic once. Accepted assessments, hook
  requirements, reviews and implementation results queue their decisions or next commands in the same unit.
- **Terminal operations.** A report under a terminal operation's correlation is parked, and its replay is parked the
  same way.
- **Execution notices.** The notice a cancellation queues is received once, and a conflicting redelivery refuses.
- **cancel / request_rebase.** They cover the authorized and refused paths and the idempotent rebase request.

Layer: harness (never shipped)

`api` supplies MemoryStore, `workflow(store)` (the side's Workflow bound to the packaged organization, the side's
adoption gate, ticket binding and terminal-operation parking), `envelope(...)`, `advance(seconds)` and `org`. Every
task is created through the side's own submit/claim/complete, so the reports are the ones the side itself queued.
The compared results are values or refusals, the outbox messages the steps queue (by digest) and the final store
records (by body digest).
"""

from __future__ import annotations

import copy
import hashlib
import json

CANDIDATE = {"revision": "a" * 40, "tree": "b" * 40, "base": "c" * 40}


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    if isinstance(value, dict):
        return {"value": canonical_digest(value), "keys": sorted(value)}
    return {"value": value if value is None or isinstance(value, (bool, int)) else canonical_digest(value)}


def outbox(store) -> list:
    with store.transaction() as tx:
        return sorted(tx.scan("outbox"), key=lambda row: row["message"]["message_id"])


def report_for(store, task_id) -> dict:
    """The task.result the side's own complete() queued for this task."""
    return next(copy.deepcopy(row["message"]) for row in outbox(store)
                if row["message"]["type"] == "task.result" and row["message"]["what"]["details"]["task_id"] == task_id)


def finished(api, store, wf, sender, recipient, action, details, correlation, result):
    """Submit, claim and complete one task through the side's Workflow; returns (task, report)."""
    message = api.envelope("task.assign", sender, recipient, action, details, correlation)
    wf.submit(message)
    api.advance(1)
    task = wf.claim(recipient, "owner-" + action)
    api.advance(1)
    wf.complete(task, result)
    api.advance(1)
    return task, report_for(store, task["id"])


def run(api) -> dict:
    out = {}
    store = api.MemoryStore()
    wf = api.workflow(store)

    # implement result -> review_lead decision; replay; conflicting body; unproven result
    implement, report = finished(api, store, wf, "lead:improvement", "worker:implementation", "implement",
                                 {"plan": {"objective": "x"}}, "corr-impl",
                                 {"candidate": dict(CANDIDATE), "summary": "done"})
    out["implement_report"] = call(wf.handle, report)
    out["implement_replay"] = call(wf.handle, copy.deepcopy(report))
    conflicting = copy.deepcopy(report)
    conflicting["what"]["details"]["result"] = {"candidate": dict(CANDIDATE), "summary": "changed"}
    out["implement_conflict"] = call(wf.handle, conflicting)
    forged = api.envelope("task.result", "worker:implementation", "lead:improvement", "implement",
                          {"task_id": implement["id"], "result": {"summary": "forged"}}, "corr-impl", implement["id"])
    out["implement_unproven"] = call(wf.handle, forged)

    # research result -> topic, deferred decision, discovery; the same source again records nothing new
    research_result = {"source_url": "https://github.com/example/repo", "source_details": {"revision": "d" * 40}}
    _, research_report = finished(api, store, wf, "lead:research", "worker:github", "research",
                                  {"source": "github", "intent": "user_request"}, "corr-res-1",
                                  dict(research_result))
    out["research_report"] = call(wf.handle, research_report)
    _, again = finished(api, store, wf, "lead:research", "worker:github", "research",
                        {"source": "github", "intent": "user_request"}, "corr-res-2", dict(research_result))
    out["research_same_topic"] = call(wf.handle, again)

    # decision-backed review.result -> conductor review; an unproven decision refuses
    with store.transaction() as tx:
        tx.put("decisions_pending", "decision-1", {"id": "decision-1", "status": "succeeded",
                                                   "actor": "lead:improvement", "result": {"approved": True}})
    review = api.envelope("review.result", "lead:improvement", "conductor", "review",
                          {"decision_id": "decision-1", "result": {"approved": True}}, "corr-review")
    out["review_decided"] = call(wf.handle, review)
    unproven = api.envelope("review.result", "lead:improvement", "conductor", "review",
                            {"decision_id": "decision-1", "result": {"approved": False}}, "corr-review")
    out["review_unproven"] = call(wf.handle, unproven)
    assessed = api.envelope("review.result", "lead:improvement", "conductor", "assess_research",
                            {"decision_id": "decision-2", "result": {"accepted": True}}, "corr-assess")
    with store.transaction() as tx:
        tx.put("decisions_pending", "decision-2", {"id": "decision-2", "status": "succeeded",
                                                   "actor": "lead:improvement", "result": {"accepted": True}})
    out["assess_minimal_proposal"] = call(wf.handle, assessed)

    # hook.required: required -> next plan command; active -> nothing queued; unknown -> refusal
    with store.transaction() as tx:
        tx.put("hooks", "hook-required", {"id": "hook-required", "status": "required", "fingerprint": "f" * 64})
        tx.put("hooks", "hook-active", {"id": "hook-active", "status": "active", "fingerprint": "e" * 64})
    for name, hook_id in (("hook_required", "hook-required"), ("hook_active", "hook-active"),
                          ("hook_unknown", "hook-missing")):
        message = api.envelope("hook.required", "lead:improvement", "conductor", "implement_hook",
                               {"hook_id": hook_id, "evidence_refs": []}, "corr-" + name)
        out[name] = call(wf.handle, message)

    # a task.assign through handle is a submit; an unsupported type refuses
    assign = api.envelope("task.assign", "conductor", "lead:improvement", "plan", {"plan": {"objective": "h"}},
                          "corr-assign")
    out["assign_via_handle"] = call(wf.handle, assign)
    incident = api.envelope("incident.report", "worker:implementation", "lead:improvement", "report",
                            {"occurrence_id": "o1", "root_cause": "r", "scope": "s", "evidence_refs": []},
                            "corr-incident")
    out["unsupported_type"] = call(wf.handle, incident)

    # a terminal operation's report is parked, and so is its replay
    with store.transaction() as tx:
        tx.put("operations", "op-1", {"id": "op-1", "status": "failed", "correlation_id": "operation:op-1",
                                      "cycle_id": "operation:op-1", "assignment_message_id": "assignment-op-1"})
    parked = api.envelope("task.result", "worker:implementation", "lead:improvement", "implement",
                          {"task_id": "task-of-op-1", "result": {"summary": "late"}}, "operation:op-1")
    out["terminal_parked"] = call(wf.handle, parked)
    out["terminal_parked_replay"] = call(wf.handle, copy.deepcopy(parked))

    # cancel: refusals first, then the conductor; the queued notice is received once
    queued = api.envelope("task.assign", "conductor", "lead:improvement", "plan", {"plan": {"objective": "c"}},
                          "corr-cancel")
    wf.submit(queued)
    api.advance(1)
    out["cancel_no_reason"] = call(wf.cancel, queued["message_id"], "conductor", "")
    out["cancel_unauthorized"] = call(wf.cancel, queued["message_id"], "worker:implementation", "stop")
    out["cancel_unknown"] = call(wf.cancel, "missing-task", "conductor", "stop")
    out["cancel"] = call(wf.cancel, queued["message_id"], "conductor", "operator stop")
    out["cancel_again"] = call(wf.cancel, queued["message_id"], "conductor", "operator stop")
    notices = [row["message"] for row in outbox(store) if row["message"]["type"] == "execution.notice"]
    out["notices_queued"] = len(notices)
    if notices:
        notice = copy.deepcopy(notices[0])
        out["notice_handled"] = call(wf.handle, notice)
        out["notice_replay"] = call(wf.handle, copy.deepcopy(notice))
        changed = copy.deepcopy(notice)
        changed["what"]["details"] = {**changed["what"]["details"], "reason_code": "changed"}
        out["notice_conflict"] = call(wf.handle, changed)

    # request_rebase: the completed candidate task; replay; a task without a candidate
    out["rebase"] = call(wf.request_rebase, implement["id"], "f" * 40)
    out["rebase_replay"] = call(wf.request_rebase, implement["id"], "f" * 40)
    out["rebase_other_base"] = call(wf.request_rebase, implement["id"], "9" * 40)
    out["rebase_not_candidate"] = call(wf.request_rebase, queued["message_id"], "f" * 40)

    with store.transaction() as tx:
        current = tx.get("tasks", implement["id"])
    out["context"] = canonical_digest(wf.context(current))
    out["outbox"] = [[row["message"]["type"], row["message"]["what"]["action"], row["sent"],
                      canonical_digest(row["message"])] for row in outbox(store)]
    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out
