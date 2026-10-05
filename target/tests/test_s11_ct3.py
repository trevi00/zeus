"""S11 unit CT-3: behavioural characterization of INV-CYCLE-HANDOFF-001, INV-IDEMPOTENCY-001, INV-LOCAL-CYCLE-001 and
INV-SESSION-001 (DESIGN-s11 §5 G2; the accepted D3/D4/DOC-2 pattern).

Each test names its contract ID and quotes the rule it asserts (docs/contracts.md) in its own docstring. Expected results
come from that contract text, never from the implementation's output. Everything runs on MemoryStore with the existing
shims and stand-in executors of `tests/ported`: no provider, network, PostgreSQL or Redis.
"""

import hashlib
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "ported"))

from m7_coordination import Harness, LocalCycle, Workflow, organization  # noqa: E402
from m7_executor import Executor  # noqa: E402
from m7_executor import Service as ExecutorService  # noqa: E402

from codex_harness.coordination.application.local_cycle import LocalCycle as CycleOwner  # noqa: E402
from codex_harness.coordination.application.messages import MessageHandler  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.review.application.decisions import ReviewDecisions  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

CORR = "improvement:ct3"
BUCKETS = ("local_cycles", "tasks", "decisions_pending", "outbox", "events", "releases", "workflow_inbox")


def service():
    return Harness(MemoryStore(), organization())


def queue_task(svc, task_id, correlation=CORR, status="queued"):
    message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement", {"plan": {}}, correlation)
    with svc.store.transaction() as tx:
        tx.put("tasks", task_id, {"id": task_id, "agent": "worker:implementation", "status": status, "attempt": 0,
                                  "message": message, "created_at": "2026-09-16T00:00:00+00:00"})


class StandInExecutor:
    """Marks the first queued task of the agent `succeeded` (or `outcome`); records what the cycle row said at entry."""

    def __init__(self, svc, outcome="succeeded"):
        self.svc, self.outcome, self.calls, self.cycle_rows = svc, outcome, [], []

    def execute_one(self, agent, expected=None):
        with self.svc.store.transaction() as tx:
            self.cycle_rows.append(deepcopy(tx.scan("local_cycles")))
            row = next(r for r in tx.scan("tasks") if r["agent"] == agent and r["status"] == "queued")
            self.calls.append(row["id"])
            row["status"] = self.outcome
            tx.put("tasks", row["id"], row)
            return row


def snapshot(svc):
    with svc.store.transaction() as tx:
        return {bucket: deepcopy(tx.scan(bucket)) for bucket in BUCKETS}


def test_s11_ct3_local_cycle_policy_is_durable_and_one_executor_start_per_step():
    """INV-LOCAL-CYCLE-001 (docs/contracts.md:918-923): "Start is idempotent for the same policy and refuses a different
    correlation or limit; restarts and repeated steps never reset or enlarge the count. A step ... makes at most one
    executor start ... The slot is taken and an in-flight marker recorded in one transaction before the executor starts".

    Two tasks are queued but one step starts the executor once; the slot and marker are already durable when the executor
    is entered; a restart (`start` again) and a conflicting `start` change nothing; once the limit is spent the next
    step stops with `budget_exhausted` and never enters the executor."""
    svc = service()
    first = LocalCycle(svc).start("c1", CORR, 2)
    assert (first["executions"], first["status"], first["max_executions"]) == (0, "active", 2)
    queue_task(svc, "t1")
    queue_task(svc, "t2")
    executor = StandInExecutor(svc)
    step = LocalCycle(svc, executor).step("c1")
    assert executor.calls == ["t1"]  # at most one start for this step, although t2 is also queued
    seen = executor.cycle_rows[0][0]
    assert seen["executions"] == 1 and seen["in_flight"]["id"] == "t1"  # slot + marker taken before the start
    assert step["cycle"]["executions"] == 1 and step["cycle"]["in_flight"] is None
    assert LocalCycle(svc).start("c1", CORR, 2)["executions"] == 1  # same policy: idempotent, count not reset
    for correlation, limit in ((CORR, 5), ("improvement:other", 2)):
        with pytest.raises(ContractError, match="Conflicting cycle policy"):
            LocalCycle(svc).start("c1", correlation, limit)
    assert LocalCycle(svc).status("c1")["max_executions"] == 2
    assert LocalCycle(svc, StandInExecutor(svc)).step("c1")["cycle"]["executions"] == 2
    queue_task(svc, "t3")
    spent = StandInExecutor(svc)
    final = LocalCycle(svc, spent).step("c1")
    assert final["reason"] == "budget_exhausted" and final["cycle"]["status"] == "stopped"
    assert spent.calls == [] and final["cycle"]["executions"] == 2


def test_s11_ct3_local_cycle_non_success_outcome_stops_with_a_recorded_reason():
    """INV-LOCAL-CYCLE-001 (docs/contracts.md:927-928): "Any outcome other than success (retry, failed, blocked, expired,
    exception, no claim) ... stops the cycle with a recorded reason."

    A failed execution leaves the cycle `stopped` with the reason recorded, no marker held, and no further start."""
    svc = service()
    LocalCycle(svc).start("c1", CORR, 3)
    queue_task(svc, "t1")
    queue_task(svc, "t2")
    stopped = LocalCycle(svc, StandInExecutor(svc, outcome="failed")).step("c1")
    assert stopped["cycle"]["status"] == "stopped" and stopped["cycle"]["stopped_reason"]
    assert stopped["cycle"]["in_flight"] is None and stopped["cycle"]["executions"] == 1
    again = StandInExecutor(svc)
    assert LocalCycle(svc, again).step("c1")["action"] == "none" and again.calls == []


def test_s11_ct3_cycle_handoff_is_a_read_only_projection_with_a_digested_reason():
    """INV-CYCLE-HANDOFF-001 (docs/contracts.md:942-948): "`LocalCycle.handoff` ... a read-only projection ...: authority
    `observation_only`, `automatic_resume` false, schema `urn:zeus:cycle-handoff:1`. ... nothing is put, updated, deleted
    ... The stored `stopped_reason` is never printed as such: ... the text before the first colon when that text is one of
    the finite recognized codes ..., otherwise `unknown`; any colon detail is discarded. `cycle.stopped_reason_sha256` is
    the lowercase SHA-256 hex of the complete original UTF-8 string".

    The expected digest is computed here from the stored string; the stored row and every bucket are unchanged."""
    assert CycleOwner.handoff is LocalCycle.handoff
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    stored = "exception:OSError secret-detail"
    with svc.store.transaction() as tx:
        row = tx.get("local_cycles", "c1")
        row.update(status="stopped", stopped_reason=stored,
                   last_execution={"agent": "worker:implementation", "kind": "task", "id": "t9", "status": "exception",
                                   "error": "OSError"})
        tx.put("local_cycles", "c1", row)
    before = snapshot(svc)
    view = LocalCycle(svc).handoff("c1")
    assert snapshot(svc) == before
    assert (view["schema"], view["authority"], view["automatic_resume"]) == (
        "urn:zeus:cycle-handoff:1", "observation_only", False)
    assert view["cycle"]["stopped_reason"] == "exception"  # the detail after the colon is discarded
    assert view["cycle"]["stopped_reason_sha256"] == hashlib.sha256(stored.encode("utf-8")).hexdigest()
    assert "secret-detail" not in repr(view) and "error" not in view["cycle"]["last_execution"]
    assert view["remaining_executions"] == 2 - view["cycle"]["executions"]
    assert LocalCycle(svc).status("c1")["stopped_reason"] == stored  # the stored row keeps the original text
    for text, code in (("free text: x", "unknown"), ("budget_exhausted", "budget_exhausted")):
        with svc.store.transaction() as tx:
            row = tx.get("local_cycles", "c1")
            row["stopped_reason"] = text
            tx.put("local_cycles", "c1", row)
        shown = LocalCycle(svc).handoff("c1")["cycle"]
        assert shown["stopped_reason"] == code
        assert shown["stopped_reason_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    with svc.store.transaction() as tx:
        row = tx.get("local_cycles", "c1")
        row["stopped_reason"] = None
        tx.put("local_cycles", "c1", row)
    assert LocalCycle(svc).handoff("c1")["cycle"]["stopped_reason"] is None
    with pytest.raises(ContractError, match="Unknown cycle"):
        LocalCycle(svc).handoff("absent")


def test_s11_ct3_idempotency_redelivery_returns_the_recorded_result_or_is_rejected_on_changed_content():
    """INV-IDEMPOTENCY-001 (docs/contracts.md:196-198): "Receipts are keyed by durable identity (message, ...) and a
    redelivery returns the recorded result or is rejected when its content differs."

    A task.result report is handled once: its redelivery returns the recorded outcome and adds no decision or outbox row;
    the same message id with different content is refused and changes nothing."""
    svc = Workflow(MemoryStore(), organization())
    assert isinstance(svc.messages, MessageHandler)  # `handle` below is the row-listed MessageHandler.handle
    result = {"summary": "done", "candidate": {"revision": "r1", "base": "b", "tree": "t", "author": "worker:implementation"}}
    assign = envelope("task.assign", "lead:improvement", "worker:implementation", "implement", {"plan": {}}, CORR)
    with svc.store.transaction() as tx:
        tx.put("tasks", "t1", {"id": "t1", "agent": "worker:implementation", "status": "succeeded", "attempt": 0,
                               "message": assign, "result": result, "created_at": "2026-09-16T00:00:00+00:00"})
    report = envelope("task.result", "worker:implementation", "lead:improvement", "implement",
                      {"task_id": "t1", "result": result}, CORR, assign["message_id"])
    recorded = svc.handle(report)
    assert recorded["handled"] is True

    def rows():
        with svc.store.transaction() as tx:
            return {bucket: deepcopy(tx.scan(bucket)) for bucket in ("decisions_pending", "outbox", "workflow_inbox")}

    after_first = rows()
    assert len(after_first["decisions_pending"]) == 1 and len(after_first["workflow_inbox"]) == 1
    assert svc.handle(deepcopy(report)) == recorded  # a redelivery returns the recorded result
    assert rows() == after_first  # ... and effects nothing
    changed = deepcopy(report)
    changed["what"]["details"]["result"] = {**result, "summary": "changed"}
    with pytest.raises(ContractError, match="Conflicting report identity"):
        svc.handle(changed)
    assert rows() == after_first


@pytest.mark.parametrize("lease", ["current", "replaced"])
def test_s11_ct3_session_a_stale_generation_cannot_commit_decision_effects(tmp_path, monkeypatch, lease):
    """INV-SESSION-001 (docs/contracts.md:11): "Checkpoint generation and execution lease fence stale writers."

    A review_lead decision runs through `ReviewDecisions` (via the executor shim). While the reviewer runs, the lease is
    either left alone (current) or taken over by a replacement with a higher generation (replaced). The current writer
    commits its verdict, release and outbox message together; the stale writer commits none of them, publishes nothing
    and leaves the replacement's ownership untouched."""
    store = MemoryStore()
    carrier = ExecutorService(store, organization())
    git = SimpleNamespace(repository=tmp_path, inspect=lambda *a: {}, review_workspace=lambda *a: str(tmp_path),
                          _git=lambda *a, **k: "" if a[0] == "status" else "revision")
    executor = Executor(carrier, git, FileArtifacts(tmp_path / "artifacts"))
    assert isinstance(executor.decisions, ReviewDecisions)
    candidate = {"revision": "revision", "base": "base", "tree": "tree", "author": "worker:implementation"}
    data = {"candidate": candidate, "source_actor": "worker:implementation", "occurrence_id": "occurrence",
            "source_task_id": "task", "evidence_ref": "fixture:error"}
    message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement", {}, "correlation")
    with store.transaction() as tx:
        tx.put("decisions_pending", "decision", {"id": "decision", "actor": "lead:improvement", "phase": "review_lead",
                                                 "input": data, "message": message, "status": "pending", "attempt": 0})

    def reviewer(*args, **kwargs):
        if lease == "replaced":
            with store.transaction() as tx:
                row = tx.get("decisions_pending", "decision")
                started = row["generation"]
                row.update(owner="replacement", lease_owner="replacement", generation=started + 1)
                tx.put("decisions_pending", "decision", row)
        return {"accepted": True, "confirmed": True, "root_cause": "cause", "scope": "scope",
                "execution_ref": "fixture:review", "reason": "fixture"}

    monkeypatch.setattr(executor, "_run", reviewer)
    executor.decide_one("lead:improvement")
    with store.transaction() as tx:
        row = tx.get("decisions_pending", "decision")
        releases, outbox = tx.scan("releases"), tx.scan("outbox")
    if lease == "current":
        assert row["status"] == "succeeded"
        assert len(releases) == 1 and len(outbox) == 1
        return
    assert row["status"] == "running" and row["lease_owner"] == "replacement" and row["generation"] == 2
    assert releases == [] and outbox == []
