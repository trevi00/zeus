"""Shared S5 scenario steps (`coordination.execution_recovery`): M7 `ExecutionRecovery.prepare/apply`, the operator's
bounded recovery of one execution (M7 tests/test_execution_recovery.py sequences).

- **resume.** An exhausted task is resumed with its history preserved and without spending an attempt. The replay is
  idempotent, and the old lease and the old packet are stale after the next claim.
- **migrate.** A legacy retry budget is migrated explicitly.
- **Refusals.** Unrelated states and invalid proposals refuse read-only. An expired packet and a changed snapshot
  refuse.
- **Expired task.** It keeps its message and takes the new deadline; removing a deadline refuses.
- **Apply refusals.** A wrong role and missing evidence cannot apply.
- **repair.** Repair keeps the corrupt source in the receipt.
- **Decisions.** An unhandled decision phase refuses.

Layer: harness (never shipped)

`api` supplies MemoryStore, `workflow(store)`, `recovery(store, artifacts_root)` (the side's ExecutionRecovery over
its FileArtifacts), `envelope(...)`, `advance(seconds)` and `artifact_root()` (a fresh directory). The compared results
are the values or refusals and the final store records by body digest.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

FUTURE = "2027-01-01T00:00:00+00:00"


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def attempt(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    return {"value": canonical_digest(value), "keys": sorted(value) if isinstance(value, dict) else None}


def records(store):
    with store.transaction() as tx:
        rows = tx.records()
    return sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)


class World:
    def __init__(self, api):
        self.api = api
        self.store = api.MemoryStore()
        self.wf = api.workflow(self.store)
        self.root = api.artifact_root()
        self.recovery = api.recovery(self.store, self.root)

    def assignment(self, deadline=None):
        message = self.api.envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                                    {"objective": "fixture"}, "test")
        if deadline is not None:
            message["when"]["deadline"] = deadline
        return message

    def exhausted(self):
        task = self.wf.submit(self.assignment())
        self.api.advance(1)
        lease = self.wf.claim("worker:implementation", "owner", max_attempts=1)
        self.api.advance(1)
        self.wf.fail(lease, "Actual failure API input")
        self.api.advance(1)
        self.wf.claim("worker:implementation", "after-failure")  # finds the budget spent (M7 fixture)
        self.api.advance(1)
        return task, lease

    def prepare(self, task_id, **kwargs):
        ref = self.recovery.artifacts.put("Operator recovery rationale test fixture", "unit-test")["ref"]
        return self.recovery.prepare("tasks", task_id, **{
            "operation": "resume", "max_attempts": 2, "deadline": None, "reason": "Investigated transient failure",
            "operator": "test-operator", "evidence_refs": [ref], **kwargs})

    def set(self, task_id, **fields):
        with self.store.transaction() as tx:
            row = tx.get("tasks", task_id)
            row.update(**fields)
            tx.put("tasks", task_id, row)


def run(api) -> dict:
    out = {}

    w = World(api)
    task, lease = w.exhausted()
    w.set(task["id"], project_context={"id": "same-project"}, retrospective={"seen": 3, "target": 5})
    packet = w.prepare(task["id"])
    out["resume_packet"] = canonical_digest(packet)
    out["resume"] = attempt(w.recovery.apply, packet)
    before = records(w.store)
    out["resume_replay"] = attempt(w.recovery.apply, copy.deepcopy(packet))
    out["resume_replay_unchanged"] = records(w.store) == before
    out["old_lease_stale"] = attempt(w.wf.fail, lease, "Actual failure API input")
    out["next_claim"] = attempt(w.wf.claim, "worker:implementation", "recovered-process")
    out["packet_stale"] = attempt(w.recovery.apply, packet)
    out["resume_records"] = records(w.store)

    w = World(api)
    task = w.wf.submit(w.assignment())
    w.set(task["id"], attempt=2, generation=2, status="retry")
    out["legacy_claim"] = attempt(w.wf.claim, "worker:implementation", "upgrade")
    migrate = w.prepare(task["id"], operation="migrate", max_attempts=3)
    out["migrate"] = attempt(w.recovery.apply, migrate)
    out["migrate_records"] = records(w.store)

    for state in ("running", "succeeded", "cancelled", "queued", "blocked"):
        w = World(api)
        task, _ = w.exhausted()
        w.set(task["id"], status=state)
        out["unrelated_" + state] = attempt(w.prepare, task["id"])

    for name, changes in (("attempts_bool", {"max_attempts": True}), ("attempts_one", {"max_attempts": 1}),
                          ("no_reason", {"reason": ""}), ("no_operator", {"operator": ""}),
                          ("naive_deadline", {"deadline": "2026-01-01T00:00:00"}),
                          ("past_deadline", {"deadline": "2000-01-01T00:00:00+00:00"})):
        w = World(api)
        task, _ = w.exhausted()
        before = records(w.store)
        out["invalid_" + name] = attempt(w.prepare, task["id"], **changes)
        out["invalid_" + name + "_read_only"] = records(w.store) == before

    w = World(api)
    task, _ = w.exhausted()
    packet = w.prepare(task["id"])
    expired = copy.deepcopy(packet)
    expired.update(issued_at="2000-01-01T00:00:00+00:00", expires_at="2000-01-01T00:01:00+00:00")
    out["expired_packet"] = attempt(w.recovery.apply, expired)
    w.wf.cancel(task["id"], "conductor", "Operator cancelled while reviewing")
    out["changed_snapshot"] = attempt(w.recovery.apply, packet)

    w = World(api)
    task, _ = w.exhausted()
    w.set(task["id"], status="expired", error="deadline exceeded", execution_deadline="2000-01-01T00:00:00+00:00")
    out["expired_without_deadline"] = attempt(w.prepare, task["id"])
    packet = w.prepare(task["id"], deadline=FUTURE)
    out["expired_resume"] = attempt(w.recovery.apply, packet)
    out["expired_claim"] = attempt(w.wf.claim, "worker:implementation", "new-deadline")

    w = World(api)
    task, _ = w.exhausted()
    packet = w.prepare(task["id"])
    out["wrong_role"] = attempt(w.recovery.apply, packet, actor="worker:implementation")
    key = packet["evidence_refs"][0].split(":")[1]
    for path in Path(w.root).rglob(key + "*"):
        path.unlink()
    out["missing_evidence"] = attempt(w.recovery.apply, packet)

    w = World(api)
    task, _ = w.exhausted()
    w.set(task["id"], status="blocked", error="InvalidRetryBudget", retry_budget={"version": "invalid"})
    out["repair"] = attempt(w.recovery.apply, w.prepare(task["id"], operation="repair"))
    out["repair_records"] = records(w.store)

    w = World(api)
    with w.store.transaction() as tx:
        tx.put("decisions_pending", "decision", {"id": "decision", "phase": "unknown_phase", "actor": "conductor",
                                                 "input": {}, "attempt": 1, "generation": 1, "status": "failed",
                                                 "error": "attempt budget exhausted",
                                                 "retry_budget": {"version": 1, "max_attempts": 1}})
    ref = w.recovery.artifacts.put("Evidence fixture", "test")["ref"]
    out["unhandled_phase"] = attempt(w.recovery.prepare, "decisions_pending", "decision", operation="resume",
                                     max_attempts=2, deadline=None, reason="Explicit recovery", evidence_refs=[ref],
                                     operator="test")
    return out
