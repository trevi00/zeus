"""Terminal-operation finalization and late-message parking (INV-OPERATION-FINALIZATION-001).

Every executor, bus, budget and observer here is a labeled fixture: no Claude, Codex, ledger or
production stream is touched. The PostgreSQL/Redis cases use real services under a test-owned
schema and namespace and are skipped explicitly without HARNESS_INTEGRATION=1.
"""
import json
import os
import threading
from contextlib import contextmanager
from copy import deepcopy

import pytest
from test_operation import (
    BOUND_GOAL,
    CANARY,
    IDENTITY,
    Bus,
    Collector,
    FakeBudget,
    FakeExecutor,
    manifest,
)

from codex_harness.adapters.observation_spool import MemorySpool
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.execution_notices import record as execution_notice
from codex_harness.application.local_cycle import MESSAGE_DRAIN, LocalCycle
from codex_harness.application.observations import MemoryDirectory, Observer
from codex_harness.application.operation import TERMINAL, Operation
from codex_harness.application.operation_finalization import (
    MESSAGE_DISPOSITIONS,
    ParkedMessageConflict,
    owner,
    park,
    retire,
)
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, digest, envelope, utcnow
from codex_harness.domain.observation import new_process_run_id
from codex_harness.domain.operation import LEAD, WORKER, assignment_message_id, validate_manifest

OP1, OP2 = "operation:op-001", "operation:op-002"
TERMINATIONS = "observation_terminations"


class _Probe:
    """Transaction proxy (fixture): reports whether a put matched `trigger`; optionally fails that put."""

    def __init__(self, tx, trigger, fail):
        self.tx, self.trigger, self.fail, self.hit = tx, trigger, fail, False

    def put(self, bucket, key, body):
        if self.trigger(bucket, key, body):
            self.hit = True
            if self.fail:
                raise OSError("store write refused at the boundary (fixture)")
        return self.tx.put(bucket, key, body)

    def __getattr__(self, name):
        return getattr(self.tx, name)


class GatedStore:
    """Test-owned wrapper over a real store: the transaction whose put matches `trigger` signals
    `entered` and keeps its transaction (and the store's lock) open until `release`, then commits.
    With `fail=True` that put raises instead, so the transaction rolls back before any commit."""

    def __init__(self, store, trigger, entered=None, release=None, fail=False):
        self.store, self.trigger, self.fail = store, trigger, fail
        self.entered, self.release = entered or threading.Event(), release or threading.Event()

    @contextmanager
    def transaction(self):
        with self.store.transaction() as tx:
            probe = _Probe(tx, self.trigger, self.fail)
            yield probe
            if probe.hit:
                self.entered.set()
                assert self.release.wait(timeout=30), "the gate was never released (fixture)"


def terminal_put(bucket, key, body):
    return bucket == "operations" and body.get("status") in TERMINAL


def marker(task_id, status, bucket="tasks", attempt=7):
    """A persisted INV-OBSERVATION-001 termination marker of another attempt (synthetic fixture)."""
    return {"record_id": "term-" + task_id, "status": status, "task_id": task_id, "bucket": bucket,
            "generation": 9, "attempt": attempt, "reservation_id": "r", "boundary": "reserved",
            "invocation_outcome": "unknown", "error": CANARY, "process_run_id": "p", "recorded_at": "x"}


def valid(op="op-001"):
    return validate_manifest(manifest(id=op), packaged_policy())


class ResidueExecutor(FakeExecutor):
    """Like the real executor: a failed worker leaves a pending diagnose decision; a rejecting lead
    queues a rework assignment through the outbox (fixture)."""

    def execute_one(self, agent, expected=None):
        task = super().execute_one(agent, expected)
        if self.worker != "succeeded":
            with self.svc.store.transaction() as tx:
                tx.put("decisions_pending", "diag-" + task["id"], {
                    "id": "diag-" + task["id"], "actor": LEAD, "phase": "diagnose", "message": task["message"],
                    "input": {"error": CANARY, "source_task_id": task["id"]}, "status": "pending", "attempt": 0})
        return task

    def decide_one(self, agent, expected=None):
        row = super().decide_one(agent, expected)
        if self.verdict is False:
            rework = envelope("task.assign", LEAD, WORKER, "implement",
                              {"plan": {"objective": "rework " + CANARY}, "rework": 1}, row["message"]["correlation_id"])
            with self.svc.store.transaction() as tx:
                tx.put("outbox", rework["message_id"], {"message": rework, "sent": False})
        return row


def build(svc=None, bus=None, observer=None, executor_class=ResidueExecutor, **kwargs):
    svc = svc or Harness(MemoryStore(), organization())
    executor = executor_class(svc, **kwargs)
    operation = Operation(svc, executor, bus or Bus(), Workflow(svc.store, svc.org), FakeBudget(), Collector(),
                          observer=observer)
    return svc, operation, executor


def late(correlation=OP1, recipient=WORKER, details=None):
    return envelope("task.assign", LEAD, recipient, "implement", details or {"plan": {"objective": "late"}}, correlation)


def spool_observer(store, spool=None):
    return Observer(store, spool or MemorySpool(new_process_run_id()), component="unit", directory=MemoryDirectory())


# ----- normal accepted ----------------------------------------------------------------------
def test_accepted_operation_keeps_its_result_retires_nothing_and_makes_no_extra_calls():
    bus = Bus()
    svc, operation, executor = build(bus=bus)
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and executor.calls == ["task", "decision"]
    summary = receipt["finalization"]
    assert summary["retired"] == {"tasks": [], "decisions_pending": []} and summary["unresolved"] == []
    assert summary["already_terminal"] == 2 and summary["authority"].startswith("cleanup_summary")
    with svc.store.transaction() as tx:
        assert tx.scan("operation_dispositions") == [] and tx.scan("release_queue") == []
        assert tx.get("tasks", receipt["task_id"])["status"] == "succeeded"
    assert CANARY not in json.dumps(receipt) and bus.published[-1]["type"] == "task.result"


# ----- worker retry + diagnose ------------------------------------------------------------
def test_worker_retry_and_diagnose_are_retired_atomically_and_the_next_cycle_progresses():
    svc, operation, executor = build(worker="retry")
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "execution_retry"
    with svc.store.transaction() as tx:
        task = tx.get("tasks", receipt["assignment_message_id"])
        diagnose = tx.get("decisions_pending", "diag-" + task["id"])
        fences = {f["row_id"]: f for f in tx.scan("execution_fences")}
        dispositions = tx.scan("operation_dispositions")
    assert task["status"] == "cancelled" and task["retirement"]["reason_code"] == "operation_terminal"
    assert task["error"] == "provider failed: " + CANARY, "the prior error stays in its restricted row"
    assert "attempt_outcomes" not in task, "no cancelled attempt is invented; no attempt ran"
    assert task["retirement"]["before"]["status"] == "retry" and task["generation"] == 2
    assert task["lease_owner"] is None and task["message"]["correlation_id"] == OP1
    assert diagnose["status"] == "cancelled" and diagnose["input"]["error"] == CANARY, "input evidence preserved"
    assert diagnose.get("error") is None and "attempt_outcomes" not in diagnose
    assert fences[task["id"]]["generation"] == 2 and fences[diagnose["id"]]["generation"] == 1
    assert sorted(d["row_id"] for d in dispositions) == sorted([task["id"], diagnose["id"]])
    assert receipt["finalization"]["retired"] == {"tasks": [task["id"]], "decisions_pending": [diagnose["id"]]}
    assert CANARY not in json.dumps(receipt) and CANARY not in json.dumps(dispositions)
    # The next independent operation reaches its own assignment: nothing foreign is queued.
    svc, second, executor = build(svc)
    next_receipt = second.run(valid("op-002"), IDENTITY, BOUND_GOAL)
    assert next_receipt["status"] == "accepted" and executor.calls == ["task", "decision"]
    assert Operation(svc).status("op-001")["status"] == "failed", "the first outcome is immutable"


# ----- lead rejected + rework ---------------------------------------------------------------
def test_rejected_operation_stays_rejected_and_its_rework_is_parked_before_ack():
    bus = Bus()
    svc, operation, executor = build(bus=bus, verdict=False)
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "rejected" and receipt["reason_code"] == "lead_rejected"
    rework = [m for m in bus.published if m["type"] == "task.assign" and m["what"]["details"].get("rework") == 1]
    assert len(rework) == 1 and rework[0]["correlation_id"] == OP1
    entry = next(e for e, m in bus.queued if m is rework[0] or m == rework[0])
    assert entry not in bus.acked, "the rework sits pending in the worker stream"
    svc, second, executor = build(svc, bus=bus)
    next_receipt = second.run(valid("op-002"), IDENTITY, BOUND_GOAL)
    assert next_receipt["status"] == "accepted" and executor.calls == ["task", "decision"]
    assert entry in bus.acked
    with svc.store.transaction() as tx:
        [parked] = tx.scan(MESSAGE_DISPOSITIONS)
        assert parked["message_id"] == rework[0]["message_id"] and parked["operation_id"] == "op-001"
        assert parked["message"] == rework[0] and parked["reason_code"] == "operation_terminal"
        assert tx.get("tasks", rework[0]["message_id"]) is None, "parking never queues work"
        assert tx.get("operations", "op-001")["status"] == "rejected"
    assert next_receipt["cycle"]["cycle"]["status"] == "awaiting_operator"


# ----- late / repeated messages -------------------------------------------------------------
def test_late_messages_are_parked_in_submit_and_handle_replay_is_idempotent_conflict_refused():
    svc, operation, _ = build(worker="failed")
    operation.run(valid(), IDENTITY, BOUND_GOAL)
    workflow = Workflow(svc.store, svc.org)
    message = late()
    first = workflow.submit(message)
    assert first["parked"] is True and first["authority"] == "parked_no_work" and first["operation_id"] == "op-001"
    assert workflow.submit(deepcopy(message)) == first and workflow.handle(deepcopy(message)) == first
    conflicting = {**deepcopy(message), "what": {**message["what"], "details": {"plan": {"objective": "other"}}}}
    with pytest.raises(ParkedMessageConflict):
        workflow.submit(conflicting)
    with pytest.raises(ContractError):
        workflow.claim(WORKER, "late-owner", expected={"id": message["message_id"], "correlation_id": OP1, "statuses": {"queued"}})
    with svc.store.transaction() as tx:
        assert tx.get("tasks", message["message_id"]) is None and len(tx.scan(MESSAGE_DISPOSITIONS)) == 1
    # A late report to the lead parks too; nothing becomes a pending decision.
    report = envelope("task.result", WORKER, LEAD, "implement", {"task_id": "x", "result": {"candidate": {}}}, OP1)
    assert workflow.handle(report)["parked"] is True
    notice = envelope("execution.notice", WORKER, LEAD, "observe_execution", {"reason_code": "late"}, OP1)
    assert workflow.handle(notice)["parked"] is True
    with svc.store.transaction() as tx:
        assert [d["status"] for d in tx.scan("decisions_pending") if d.get("phase") != "diagnose"] == []
        assert len(tx.scan(MESSAGE_DISPOSITIONS)) == 3
    # Conductor recipients bypass parking and keep the existing (proof-requiring) path.
    to_conductor = envelope("review.result", LEAD, "conductor", "review", {"decision_id": "d", "result": {}}, OP1)
    with pytest.raises(ContractError, match="Unproven"):
        workflow.handle(to_conductor)


def test_previously_handled_report_replayed_on_the_bus_is_parked_and_the_next_cycle_progresses():
    bus = Bus()
    svc, operation, _ = build(bus=bus)
    assert operation.run(valid(), IDENTITY, BOUND_GOAL)["status"] == "accepted"
    [report] = [m for m in bus.published if m["type"] == "task.result"]
    with svc.store.transaction() as tx:
        inbox_before = deepcopy(tx.get("workflow_inbox", report["message_id"]))
    assert inbox_before["result"]["handled"] is True
    entry = bus.publish(deepcopy(report))  # the same handled report, redelivered
    svc, second, executor = build(svc, bus=bus)
    receipt = second.run(valid("op-002"), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and executor.calls == ["task", "decision"]
    assert entry in bus.acked
    with svc.store.transaction() as tx:
        assert tx.get("workflow_inbox", report["message_id"]) == inbox_before, "the original inbox evidence is untouched"
        [parked] = tx.scan(MESSAGE_DISPOSITIONS)
        assert parked["message_id"] == report["message_id"] and parked["operation_id"] == "op-001"
        assert [d["status"] for d in tx.scan("decisions_pending")] == ["succeeded", "succeeded"], "no new decision"


def test_the_original_assignment_of_a_terminal_operation_replays_as_parked_and_leaves_its_task_row():
    bus = Bus()
    svc, operation, _ = build(bus=bus)
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    [assignment] = [m for m in bus.published if m["message_id"] == receipt["assignment_message_id"]]
    with svc.store.transaction() as tx:
        task_before = deepcopy(tx.get("tasks", assignment["message_id"]))
    parked = Workflow(svc.store, svc.org).submit(deepcopy(assignment))
    assert parked["parked"] is True and parked["message_id"] == assignment["message_id"]
    with svc.store.transaction() as tx:
        assert tx.get("tasks", assignment["message_id"]) == task_before, "a succeeded task row is never rewritten"


def test_conflicting_bodies_under_the_same_id_are_refused_and_the_matching_replay_still_parks():
    svc, operation, _ = build(worker="retry")
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    workflow = Workflow(svc.store, svc.org)
    with svc.store.transaction() as tx:
        task = tx.get("tasks", receipt["assignment_message_id"])
    assert task["status"] == "cancelled"
    original = deepcopy(task["message"])
    changed = deepcopy(original)
    changed["what"]["details"]["plan"]["objective"] = "changed under the same id"
    with pytest.raises(ContractError, match="Conflicting task identity"):
        workflow.submit(changed)
    with svc.store.transaction() as tx:
        assert tx.scan(MESSAGE_DISPOSITIONS) == [], "a conflicting body is never parked"
        assert tx.get("tasks", task["id"]) == task
    replay = workflow.submit(deepcopy(original))
    assert replay["parked"] is True and replay["message_id"] == original["message_id"]
    assert workflow.handle(deepcopy(original)) == replay
    with pytest.raises(ContractError, match="Conflicting task identity"):
        workflow.submit(changed)  # the older input binding still wins over the parked digest
    with svc.store.transaction() as tx:
        assert tx.get("tasks", task["id"]) == task and len(tx.scan(MESSAGE_DISPOSITIONS)) == 1


def test_handled_report_and_notice_conflicts_are_refused_before_parking_and_originals_park():
    svc = Harness(MemoryStore(), organization())
    workflow = Workflow(svc.store, svc.org)
    with svc.store.transaction() as tx:  # a genuine notice for a worker row of op-001, handled while op-001 did not exist yet
        row = {"id": "t-early", "agent": WORKER, "status": "expired", "attempt": 1, "generation": 1, "message": late()}
        notice = execution_notice(tx, svc.org, row, "tasks", "deadline_exceeded", utcnow())["message"]
        tx.put("outbox", notice["message_id"], {"message": notice, "sent": True})  # keep it off the bus (fixture)
    assert workflow.handle(deepcopy(notice))["handled"] is True
    bus = Bus()
    svc, operation, _ = build(svc, bus=bus)
    assert operation.run(valid(), IDENTITY, BOUND_GOAL)["status"] == "accepted"
    [report] = [m for m in bus.published if m["type"] == "task.result"]  # handled by the lead during the run
    with svc.store.transaction() as tx:
        inbox = {k: deepcopy(tx.get("workflow_inbox", k)) for k in (notice["message_id"], report["message_id"])}
    assert all(row is not None for row in inbox.values())
    changed_notice = deepcopy(notice)
    changed_notice["what"]["details"]["reason_code"] = "other"
    changed_report = deepcopy(report)
    changed_report["what"]["details"]["result"] = {"candidate": {"revision": "x" * 40}}
    for original, changed, error in ((notice, changed_notice, "Conflicting execution notice delivery"),
                                     (report, changed_report, "Conflicting report identity")):
        with pytest.raises(ContractError, match=error):
            workflow.handle(changed)
        parked = workflow.handle(deepcopy(original))
        assert parked["parked"] is True and workflow.handle(deepcopy(original)) == parked
        with pytest.raises(ContractError, match=error):
            workflow.handle(changed)  # the inbox binding still wins over the parked digest
    # A never-handled late report is parked; its twin under the same id is refused by the parked
    # digest and the original still replays identically.
    late_report = envelope("task.result", WORKER, LEAD, "implement", {"task_id": "x", "result": {"candidate": {}}}, OP1)
    first = workflow.handle(deepcopy(late_report))
    assert first["parked"] is True
    twin = {**deepcopy(late_report), "what": {**late_report["what"], "details": {"task_id": "y", "result": {}}}}
    with pytest.raises(ParkedMessageConflict):
        workflow.handle(twin)
    assert workflow.handle(deepcopy(late_report)) == first
    with svc.store.transaction() as tx:
        assert {k: tx.get("workflow_inbox", k) for k in inbox} == inbox, "handled evidence untouched"
        assert len(tx.scan(MESSAGE_DISPOSITIONS)) == 3
        assert [d["status"] for d in tx.scan("decisions_pending")] == ["succeeded"], "no new decision from any replay"


def test_a_differently_typed_message_reusing_the_task_id_is_refused_and_the_assignment_still_parks():
    bus = Bus()
    svc, operation, _ = build(bus=bus)
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted"
    [assignment] = [m for m in bus.published if m["message_id"] == receipt["assignment_message_id"]]
    [report] = [m for m in bus.published if m["type"] == "task.result"]  # the genuine handled report
    with svc.store.transaction() as tx:
        task_before = deepcopy(tx.get("tasks", assignment["message_id"]))
    workflow = Workflow(svc.store, svc.org)
    poisoned = deepcopy(report)
    poisoned["message_id"] = assignment["message_id"]  # a task.result under the assignment's task id
    with pytest.raises(ContractError, match="Conflicting task identity"):
        workflow.handle(poisoned)
    with svc.store.transaction() as tx:
        assert tx.scan(MESSAGE_DISPOSITIONS) == [], "no parked digest under the task id"
        assert tx.get("tasks", assignment["message_id"]) == task_before
    parked = workflow.submit(deepcopy(assignment))
    assert parked["parked"] is True and parked["message_id"] == assignment["message_id"]
    with pytest.raises(ContractError, match="Conflicting task identity"):
        workflow.handle(deepcopy(poisoned))  # the task binding still wins over the parked digest
    with svc.store.transaction() as tx:
        assert len(tx.scan(MESSAGE_DISPOSITIONS)) == 1 and tx.get("tasks", assignment["message_id"]) == task_before


def test_a_conflicting_foreign_body_on_the_bus_is_refused_without_ack():
    svc, operation, _ = build(worker="retry")
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    with svc.store.transaction() as tx:
        original = tx.get("tasks", receipt["assignment_message_id"])["message"]
    changed = deepcopy(original)
    changed["what"]["details"]["plan"]["objective"] = "changed"
    LocalCycle(svc).start("c1", "improvement:mine", 2)
    bus = Bus()
    entry = bus.publish(changed)
    observer = spool_observer(svc.store)
    executor = FakeExecutor(svc)
    result = LocalCycle(svc, executor, bus, Workflow(svc.store, svc.org), observer=observer).step("c1")
    assert result["reason"] == "foreign_correlation" and bus.acked == [] and executor.calls == []
    assert result["messages"][0] == {"entry_id": entry, "message_id": original["message_id"], "refused": "ContractError"}
    [rejected] = [r for r in observer.spool.records() if r["event_type"] == "general.message_rejected"]
    assert rejected["attributes"]["error_type"] == "ContractError" and rejected["attributes"]["dead_letter"] is False
    with svc.store.transaction() as tx:
        assert tx.scan(MESSAGE_DISPOSITIONS) == [] and tx.get("tasks", original["message_id"])["status"] == "cancelled"


def test_active_absent_or_mismatched_operations_are_never_owners():
    svc, operation, _ = build()
    operation.claim(valid(), IDENTITY, BOUND_GOAL)  # running, not terminal
    workflow = Workflow(svc.store, svc.org)
    assert workflow.submit(late())["status"] == "queued", "an active operation keeps the existing path"
    with svc.store.transaction() as tx:
        assert owner(tx, "operation:absent") is None and owner(tx, "op-001") is None and owner(tx, None) is None
        row = tx.get("operations", "op-001")
        row.update(correlation_id="improvement:other")
        tx.put("operations", "op-001", row)
        assert owner(tx, OP1) is None, "a free-text or mismatched correlation never proves ownership"
        assert park(tx, late("operation:absent")) is None


# ----- wrong owner / active foreign ---------------------------------------------------------
@pytest.mark.parametrize("state", ["absent", "running", "mismatched"])
def test_unproven_foreign_messages_keep_the_refusal_without_ack(state):
    svc = Harness(MemoryStore(), organization())
    if state != "absent":
        Operation(svc).claim(valid(), IDENTITY, BOUND_GOAL)
    if state == "mismatched":
        with svc.store.transaction() as tx:
            row = tx.get("operations", "op-001")
            row.update(status="failed", cycle_id="other")
            tx.put("operations", "op-001", row)
    LocalCycle(svc).start("c1", "improvement:mine", 2)
    bus = Bus()
    foreign = late()
    bus.publish(foreign)
    executor = FakeExecutor(svc)
    result = LocalCycle(svc, executor, bus, Workflow(svc.store, svc.org)).step("c1")
    assert result["reason"] == "foreign_correlation" and bus.acked == [] and executor.calls == []
    with svc.store.transaction() as tx:
        assert tx.scan(MESSAGE_DISPOSITIONS) == [] and tx.get("tasks", foreign["message_id"]) is None


def test_conductor_messages_are_not_consumed_by_the_cycle_policy():
    svc, operation, _ = build(worker="failed")
    operation.run(valid(), IDENTITY, BOUND_GOAL)
    LocalCycle(svc).start("c1", "improvement:mine", 2)
    bus = Bus()
    bus.publish(envelope("review.result", LEAD, "conductor", "review", {"decision_id": "d", "result": {}}, OP1))
    result = LocalCycle(svc, FakeExecutor(svc), bus, Workflow(svc.store, svc.org)).step("c1")
    assert result["reason"] == "idle" and bus.acked == [], "a conductor stream is never read by the two roles"


# ----- running / unconfirmed ----------------------------------------------------------------
def test_running_blocked_and_leased_rows_stay_protected_and_are_reported_unresolved():
    svc, operation, executor = build()
    base = Operation._assignment(valid())
    with svc.store.transaction() as tx:
        for key, fields in (("t-running", {"status": "running", "lease_owner": "live", "generation": 3}),
                            ("t-blocked", {"status": "blocked", "error": "reconciliation_required"}),
                            ("t-leased", {"status": "retry", "lease_until": "2999-01-01T00:00:00+00:00"})):
            tx.put("tasks", key, {"id": key, "agent": WORKER, "attempt": 1, "generation": 0, "lease_until": None,
                                  "lease_owner": None, "message": base, "created_at": "2026-01-01T00:00:00+00:00", **fields})
        tx.put("execution_fences", "tasks:t-running", {"id": "tasks:t-running", "bucket": "tasks", "row_id": "t-running",
                                                       "generation": 3, "owner": "live", "at": "x"})
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "unknown" and receipt["reason_code"] == "in_flight_residue" and executor.calls == []
    with svc.store.transaction() as tx:
        rows = {k: tx.get("tasks", k) for k in ("t-running", "t-blocked", "t-leased")}
        fence = tx.get("execution_fences", "tasks:t-running")
    assert [r["status"] for r in rows.values()] == ["running", "blocked", "retry"], "protected rows untouched"
    assert rows["t-running"]["lease_owner"] == "live" and fence["generation"] == 3 and fence["owner"] == "live"
    summary = Operation(svc).status("op-001")["finalization"]
    assert {(u["id"], u["reason_code"]) for u in summary["unresolved"]} == {
        ("t-running", "running"), ("t-blocked", "blocked"), ("t-leased", "live_lease")}
    assert Operation(svc).status("op-001")["status"] == receipt["status"] != "running"


def test_retire_refuses_a_non_terminal_operation_and_a_fence_ahead_is_unresolved():
    svc = Harness(MemoryStore(), organization())
    with svc.store.transaction() as tx:
        with pytest.raises(ContractError, match="terminal"):
            retire(tx, {"id": "op", "status": "running", "correlation_id": OP1})
        tx.put("tasks", "t", {"id": "t", "agent": WORKER, "status": "queued", "attempt": 0, "generation": 0,
                              "message": late(), "created_at": "x"})
        tx.put("execution_fences", "tasks:t", {"id": "tasks:t", "bucket": "tasks", "row_id": "t", "generation": 5, "owner": None, "at": "x"})
        summary = retire(tx, {"id": "op-001", "status": "failed", "correlation_id": OP1})
        assert summary["unresolved"] == [{"bucket": "tasks", "id": "t", "reason_code": "fence_ahead"}]
        assert tx.get("tasks", "t")["status"] == "queued" and summary["retired"]["tasks"] == []


@pytest.mark.parametrize("status", ["unconfirmed", "pending_reconciliation"])
def test_termination_markers_of_any_attempt_protect_eligible_rows_and_fences_in_the_real_finish(status):
    svc, operation, executor = build(worker="retry")
    task_id = assignment_message_id(valid())
    with svc.store.transaction() as tx:  # persisted marker states beside the rows that would otherwise retire
        tx.put(TERMINATIONS, "term-task", marker(task_id, status))
        tx.put(TERMINATIONS, "term-diag", marker("diag-" + task_id, status, bucket="decisions_pending"))
        tx.put(TERMINATIONS, "term-closed", {**marker(task_id, "closed"), "record_id": "term-closed"})
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and executor.calls == ["task"]
    with svc.store.transaction() as tx:
        task, diagnose = tx.get("tasks", task_id), tx.get("decisions_pending", "diag-" + task_id)
        fences = tx.scan("execution_fences")
        assert tx.scan("operation_dispositions") == []
    assert task["status"] == "retry" and task["generation"] == 1 and "retirement" not in task
    assert task["error"] == "provider failed: " + CANARY and diagnose["status"] == "pending"
    assert [f["row_id"] for f in fences] == [], "no fence advanced"
    summary = receipt["finalization"]
    assert summary["retired"] == {"tasks": [], "decisions_pending": []}
    assert {(u["bucket"], u["id"], u["reason_code"]) for u in summary["unresolved"]} == {
        ("tasks", task_id, status), ("decisions_pending", "diag-" + task_id, status)}
    assert CANARY not in json.dumps(receipt)
    # The marker is the operator's boundary: the next independent cycle does not see the retry row
    # as its own, and the queue policy still refuses it as foreign (unchanged protection).
    svc, second, executor = build(svc)
    assert second.run(valid("op-002"), IDENTITY, BOUND_GOAL)["reason_code"] == "foreign_queue" and executor.calls == []


def test_retire_protects_marked_rows_directly_and_keeps_prior_errors():
    svc = Harness(MemoryStore(), organization())
    with svc.store.transaction() as tx:
        for key in ("t-marked", "t-free"):
            tx.put("tasks", key, {"id": key, "agent": WORKER, "status": "queued", "attempt": 0, "generation": 0,
                                  "lease_until": None, "lease_owner": None, "error": "earlier: " + CANARY,
                                  "attempt_outcomes": [{"attempt": 0, "status": "x"}], "message": late(), "created_at": "x"})
        tx.put(TERMINATIONS, "m", marker("t-marked", "unconfirmed", attempt=0))
        summary = retire(tx, {"id": "op-001", "status": "failed", "correlation_id": OP1})
        marked, free = tx.get("tasks", "t-marked"), tx.get("tasks", "t-free")
        assert tx.get("execution_fences", "tasks:t-marked") is None and tx.get("execution_fences", "tasks:t-free")["generation"] == 1
    assert summary["unresolved"] == [{"bucket": "tasks", "id": "t-marked", "reason_code": "unconfirmed"}]
    assert marked["status"] == "queued" and marked["generation"] == 0 and summary["retired"]["tasks"] == ["t-free"]
    assert free["status"] == "cancelled" and free["error"] == "earlier: " + CANARY
    assert free["attempt_outcomes"] == [{"attempt": 0, "status": "x"}] and free["retirement"]["before"]["status"] == "queued"


# ----- rollback before the terminal / disposition commit -------------------------------------
def test_rollback_of_the_terminal_transaction_leaves_no_status_disposition_or_finalized_event():
    plain = Harness(MemoryStore(), organization())
    observer = spool_observer(plain.store)
    gated = Harness(GatedStore(plain.store, terminal_put, fail=True), plain.org)
    svc, operation, executor = build(gated, observer=observer, worker="retry")
    with pytest.raises(OSError, match="fixture"):
        operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert executor.calls == ["task"]
    with plain.store.transaction() as tx:
        row = tx.get("operations", "op-001")
        task = tx.get("tasks", assignment_message_id(valid()))
        assert tx.scan("operation_dispositions") == [] and tx.get("execution_fences", "tasks:" + task["id"]) is None
    assert row["status"] == "running" and row.get("finalization") is None, "no terminal status without its dispositions"
    assert task["status"] == "retry" and "retirement" not in task
    kinds = [r["event_type"] for r in observer.spool.records()]
    assert "operations.operation_finalized" not in kinds and "general.message_acknowledged" in kinds


def test_rollback_of_the_parking_transaction_leaves_the_message_pending_and_unacknowledged():
    svc, operation, _ = build(worker="failed")
    operation.run(valid(), IDENTITY, BOUND_GOAL)
    observer = spool_observer(svc.store)
    faulty = GatedStore(svc.store, lambda bucket, key, body: bucket == MESSAGE_DISPOSITIONS, fail=True)
    LocalCycle(svc).start("c1", "improvement:mine", 2)
    bus = Bus()
    message = late()
    bus.publish(message)
    executor = FakeExecutor(svc)
    with pytest.raises(OSError, match="fixture"):
        LocalCycle(svc, executor, bus, Workflow(faulty, svc.org), observer=observer).step("c1")
    assert bus.acked == [] and executor.calls == []
    kinds = [r["event_type"] for r in observer.spool.records()]
    assert kinds == ["general.message_received"], "received only: nothing parked, accepted or acknowledged"
    with svc.store.transaction() as tx:
        assert tx.scan(MESSAGE_DISPOSITIONS) == [] and tx.get("tasks", message["message_id"]) is None
    # The same message, once the store works again, parks and is acknowledged after the parked event.
    result = LocalCycle(svc, executor, bus, Workflow(svc.store, svc.org), observer=observer).step("c1")
    assert "parked" in result["messages"][0] and len(bus.acked) == 1 and executor.calls == []
    kinds = [r["event_type"] for r in observer.spool.records()]
    assert kinds.index("operations.operation_message_parked") < kinds.index("general.message_acknowledged")


# ----- observation wiring / privacy ---------------------------------------------------------
def test_general_events_distinguish_received_handled_published_and_ack_without_secrets():
    svc = Harness(MemoryStore(), organization())
    observer = spool_observer(svc.store)
    bus = Bus()
    svc, operation, executor = build(svc, bus=bus, observer=observer, verdict=False)
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "rejected"
    records = observer.spool.records()
    kinds = [r["event_type"] for r in records]
    for name in ("general.message_received", "general.message_accepted", "general.message_acknowledged",
                 "operations.operation_finalized"):
        assert name in kinds, name
    assert kinds.index("general.message_received") < kinds.index("general.message_accepted") < kinds.index("general.message_acknowledged")
    assert kinds.index("operations.operation_finalized") > kinds.index("general.message_acknowledged")
    finalized = next(r for r in records if r["event_type"] == "operations.operation_finalized")
    assert finalized["attributes"] == {"operation_id": "op-001", "operation_status": "rejected", "retired_tasks": 0,
                                       "retired_decisions": 0, "unresolved": 0, "already_terminal": 2}
    with svc.store.transaction() as tx:
        audits = [a for a in tx.scan("observation_audit") if a["event_type"] == "general.message_published"]
    assert sorted(a["attributes"]["message_type"] for a in audits) == ["task.assign", "task.assign", "task.result"]
    # The second operation parks the rework: an explicit parked event, then the ACK, no acceptance.
    svc, second, _ = build(svc, bus=bus, observer=observer)
    assert second.run(valid("op-002"), IDENTITY, BOUND_GOAL)["status"] == "accepted"
    parked = [r for r in observer.spool.records() if r["event_type"] == "operations.operation_message_parked"]
    assert len(parked) == 1 and parked[0]["outcome"] == "blocked" and parked[0]["attributes"]["operation_id"] == "op-001"
    assert CANARY not in json.dumps(observer.spool.records()) and CANARY not in json.dumps(observer.health())
    assert observer.counters["refused"] == 0


def test_foreign_refusal_is_logged_blocked_not_dead_lettered_and_observer_absent_is_unchanged():
    svc = Harness(MemoryStore(), organization())
    observer = spool_observer(svc.store)
    LocalCycle(svc).start("c1", "improvement:mine", 2)
    bus = Bus()
    bus.publish(late("improvement:other"))
    LocalCycle(svc, FakeExecutor(svc), bus, Workflow(svc.store, svc.org), observer=observer).step("c1")
    [rejected] = [r for r in observer.spool.records() if r["event_type"] == "general.message_rejected"]
    assert rejected["attributes"] == {"stream_entry_id": "1-0", "error_type": "foreign_correlation", "dead_letter": False}
    assert bus.acked == []
    plain = LocalCycle(svc, FakeExecutor(svc), bus, Workflow(svc.store, svc.org))
    assert plain.observer is None and plain.step("c1")["reason"] == "stopped"


def test_logging_failure_never_fakes_success_or_ack_and_health_reports_it():
    class BrokenSpool(MemorySpool):
        def append(self, kind, event):
            raise OSError("spool unavailable " + CANARY)

    svc = Harness(MemoryStore(), organization())
    observer = spool_observer(svc.store, BrokenSpool(new_process_run_id()))
    bus = Bus()
    svc, operation, _ = build(svc, bus=bus, observer=observer)
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and len(bus.acked) == 2, "the durable path is unchanged"
    assert observer.counters["spool_failures"] > 0 and observer.health()["counters"]["spool_failures"] > 0
    assert CANARY not in json.dumps(observer.health())


# ----- bounds -------------------------------------------------------------------------------
def test_message_drain_bound_is_retained_for_parked_residue():
    svc, operation, _ = build(worker="failed")
    operation.run(valid(), IDENTITY, BOUND_GOAL)
    LocalCycle(svc).start("c1", "improvement:mine", 2)
    bus = Bus()
    for index in range(MESSAGE_DRAIN + 2):
        bus.publish(late(details={"plan": {"objective": "late"}, "index": index}))
    result = LocalCycle(svc, FakeExecutor(svc), bus, Workflow(svc.store, svc.org)).step("c1")
    assert len(bus.acked) == MESSAGE_DRAIN and len(result["messages"]) == MESSAGE_DRAIN
    assert all("parked" in r for r in result["messages"]) and result["cycle"]["status"] == "active"
    assert len([e for e, _ in bus.queued if e not in bus.acked]) == 2, "residue is left pending, not reported drained"


# ----- real PostgreSQL / Redis --------------------------------------------------------------
class PausingExecutor(ResidueExecutor):
    """Fixture: after the worker row is durably `retry` (with a bound retry budget, as a real first
    claim would leave it), signal `executed` and wait for `proceed` before the operation goes on."""

    def __init__(self, svc, executed, proceed, **kwargs):
        super().__init__(svc, **kwargs)
        self.executed, self.proceed = executed, proceed

    def execute_one(self, agent, expected=None):
        task = super().execute_one(agent, expected)
        with self.svc.store.transaction() as tx:
            row = tx.get("tasks", task["id"])
            row["retry_budget"] = {"max_attempts": 3, "bound_at": utcnow(), "version": 1, "origin": "first_claim"}
            tx.put("tasks", row["id"], row)
        self.executed.set()
        assert self.proceed.wait(timeout=30), "the operation was never resumed (fixture)"
        return task


def _race(pgstore, first, competitor_trigger, compete):
    """Two real PostgreSQL transactions overlap on the store's advisory lock; `first` names which one
    holds it while the other has already started and blocks. Returns (receipt, competitor outcome)."""
    executed, proceed, entered, release = (threading.Event() for _ in range(4))
    finishing = GatedStore(pgstore, terminal_put, entered, release) if first == "finish" else pgstore
    svc = Harness(finishing, organization())
    executor = PausingExecutor(svc, executed, proceed, worker="retry")
    operation = Operation(svc, executor, Bus(), Workflow(svc.store, svc.org), FakeBudget(), Collector())
    receipts, outcomes = [], []
    runner = threading.Thread(target=lambda: receipts.append(operation.run(valid(), IDENTITY, BOUND_GOAL)))
    runner.start()
    try:
        assert executed.wait(timeout=30), "worker row never reached retry"
        competitor_store = pgstore if first == "finish" else GatedStore(pgstore, competitor_trigger, entered, release)
        competitor = threading.Thread(target=lambda: outcomes.append(compete(Harness(competitor_store, organization()))))
        if first == "finish":
            proceed.set()
            assert entered.wait(timeout=30), "the terminal transaction never opened"
            competitor.start()  # its transaction blocks on the advisory lock held by the open finish
            competitor.join(timeout=1.0)
            assert competitor.is_alive() and outcomes == [], "the competitor must wait for the finish commit"
        else:
            competitor.start()
            assert entered.wait(timeout=30), "the competitor's transaction never opened"
            proceed.set()  # the operation now runs into the lock the open competitor holds
            runner.join(timeout=1.0)
            assert runner.is_alive() and receipts == [], "the finish must wait for the competitor commit"
        release.set()
        competitor.join(timeout=30)
        runner.join(timeout=30)
    finally:
        proceed.set()
        release.set()
    assert not runner.is_alive() and not competitor.is_alive()
    [receipt], [outcome] = receipts, outcomes
    return receipt, outcome


@pytest.mark.parametrize("first", ["finish", "claim"])
def test_pg_claim_versus_finish_has_one_ordered_outcome(isolated_pgstore, first):
    task_id = assignment_message_id(valid())
    receipt, claimed = _race(isolated_pgstore, first,
                             lambda bucket, key, body: bucket == "tasks" and key == task_id and body.get("status") == "running",
                             lambda svc: Workflow(svc.store, svc.org).claim(WORKER, "late-claimer"))
    assert receipt["status"] == "failed" and receipt["reason_code"] == "execution_retry"
    with isolated_pgstore.transaction() as tx:
        task, diagnose = tx.get("tasks", task_id), tx.get("decisions_pending", "diag-" + task_id)
        fence = tx.get("execution_fences", "tasks:" + task_id)
        dispositions = sorted(d["row_id"] for d in tx.scan("operation_dispositions"))
    summary = receipt["finalization"]
    if first == "finish":
        assert claimed is None, "a retired row is never claimable after the finish committed"
        assert task["status"] == "cancelled" and task["retirement"]["before"]["status"] == "retry"
        assert fence["generation"] == 2 and fence["owner"] is None and summary["unresolved"] == []
        assert dispositions == sorted([task_id, "diag-" + task_id])
    else:
        assert claimed is not None and claimed["status"] == "running" and claimed["lease_owner"] == "late-claimer"
        assert task["status"] == "running" and task["lease_owner"] == "late-claimer" and "retirement" not in task
        assert fence["generation"] == 2 and fence["owner"] == "late-claimer", "the live claim keeps its fence"
        assert summary["unresolved"] == [{"bucket": "tasks", "id": task_id, "reason_code": "running"}]
        assert dispositions == ["diag-" + task_id], "only the never-started diagnose is retired"
    assert diagnose["status"] == "cancelled" and diagnose["input"]["error"] == CANARY
    assert Operation(Harness(isolated_pgstore, organization())).status("op-001")["status"] == "failed"


@pytest.mark.parametrize("first", ["finish", "submit"])
def test_pg_submit_versus_finish_has_one_ordered_outcome_and_survives_restart(isolated_pgstore, first):
    message = late()  # one message object: every replay below is a deepcopy of this exact identity
    receipt, submitted = _race(isolated_pgstore, first,
                               lambda bucket, key, body: bucket == "tasks" and key == message["message_id"],
                               lambda svc: Workflow(svc.store, svc.org).submit(deepcopy(message)))
    assert receipt["status"] == "failed"
    with isolated_pgstore.transaction() as tx:
        task = tx.get("tasks", message["message_id"])
        parked_rows = tx.scan(MESSAGE_DISPOSITIONS)
    if first == "finish":
        assert submitted["parked"] is True and task is None and len(parked_rows) == 1
        assert message["message_id"] not in receipt["finalization"]["retired"]["tasks"]
    else:
        assert submitted["status"] == "queued" and task["status"] == "cancelled", "queued before the finish, then retired by it"
        assert task["input_hash"] == digest(message) and task["retirement"]["before"]["status"] == "queued"
        assert message["message_id"] in receipt["finalization"]["retired"]["tasks"] and parked_rows == []
    again = Harness(isolated_pgstore, organization())  # restart: the same message keeps parking
    workflow = Workflow(again.store, again.org)
    parked = workflow.submit(deepcopy(message))
    assert parked["parked"] is True and workflow.submit(deepcopy(message)) == parked
    changed = deepcopy(message)
    changed["what"]["details"]["plan"]["objective"] = "changed under the same id"
    with pytest.raises(ContractError, match="Conflicting"):
        workflow.submit(changed)
    assert Workflow(Harness(isolated_pgstore, organization()).store, again.org).submit(deepcopy(message)) == parked
    with again.store.transaction() as tx:
        assert len(tx.scan(MESSAGE_DISPOSITIONS)) == 1 and tx.get("tasks", message["message_id"]) == task


def test_pg_rollback_before_the_terminal_commit_leaves_no_status_disposition_or_finalized_event(isolated_pgstore):
    observer = spool_observer(isolated_pgstore)
    svc = Harness(GatedStore(isolated_pgstore, terminal_put, fail=True), organization())
    svc, operation, executor = build(svc, observer=observer, worker="retry")
    with pytest.raises(OSError, match="fixture"):
        operation.run(valid(), IDENTITY, BOUND_GOAL)
    task_id = assignment_message_id(valid())
    with isolated_pgstore.transaction() as tx:
        row, task = tx.get("operations", "op-001"), tx.get("tasks", task_id)
        assert tx.scan("operation_dispositions") == [] and tx.get("execution_fences", "tasks:" + task_id) is None
    assert row["status"] == "running" and row.get("finalization") is None and task["status"] == "retry"
    kinds = [r["event_type"] for r in observer.spool.records()]
    assert "operations.operation_finalized" not in kinds and "general.message_acknowledged" in kinds


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("HARNESS_INTEGRATION") != "1", reason="Set HARNESS_INTEGRATION=1 for local services")
def test_real_redis_commit_before_ack_gap_keeps_pel_and_redelivery_is_parked_without_execution(isolated_pgstore):
    from codex_harness.adapters.bus import RedisBus
    from codex_harness.bootstrap import redis_url

    svc = Harness(isolated_pgstore, organization())
    svc, operation, _ = build(svc, worker="failed")
    assert operation.run(valid(), IDENTITY, BOUND_GOAL)["status"] == "failed"
    observer = spool_observer(isolated_pgstore)
    bus = RedisBus(redis_url(), namespace="zeus-finalization-test-" + new_process_run_id())
    message = late()  # one message identity for publication, disposition and redelivery
    try:
        entry = bus.publish(message)
        LocalCycle(svc).start("c1", "improvement:mine", 2)
        workflow = Workflow(svc.store, svc.org)

        class AckFails(RedisBus):
            def ack(self, agent, entry_id):
                raise OSError("ack lost (fixture)")

        failing = AckFails(redis_url(), namespace=bus.namespace)
        with pytest.raises(OSError, match="fixture"):
            LocalCycle(svc, FakeExecutor(svc), failing, workflow, observer=observer).step("c1")
        with isolated_pgstore.transaction() as tx:
            [parked] = tx.scan(MESSAGE_DISPOSITIONS)
        assert parked["message_id"] == message["message_id"], "the disposition committed before the ACK"
        pending = bus.client.xpending_range(bus.stream(WORKER), "workers", "-", "+", 10)
        assert [p["message_id"] for p in pending] == [entry], "PEL retained"
        events = [(r["event_type"], r.get("causation_id")) for r in observer.spool.records()]
        assert ("operations.operation_message_parked", message["message_id"]) in events
        assert ("general.message_acknowledged", message["message_id"]) not in events, "no ACK observed"
        # Test-owned: make the pending entry look idle so the EXISTING reclaim policy (idle >= 60 s)
        # redelivers it now; production reclaim settings are untouched and nobody sleeps a minute.
        consumer = WORKER + ":cycle:c1"
        bus.client.xclaim(bus.stream(WORKER), "workers", consumer, 0, [entry], idle=120000)
        executor = FakeExecutor(svc)
        result = LocalCycle(svc, executor, bus, workflow, observer=observer).step("c1")
        assert executor.calls == [] and result["messages"][0]["parked"] == parked["id"]
        assert result["messages"][0]["entry_id"] == entry, "the same stream entry was redelivered and consumed"
        assert bus.client.xpending_range(bus.stream(WORKER), "workers", "-", "+", 10) == []
        with isolated_pgstore.transaction() as tx:
            [same] = tx.scan(MESSAGE_DISPOSITIONS)
            assert same == parked, "the replay returned the identical disposition"
        kinds = [r["event_type"] for r in observer.spool.records()]
        assert kinds.index("operations.operation_message_parked") < kinds.index("general.message_acknowledged")
    finally:
        bus.client.delete(bus.stream(WORKER), bus.stream(LEAD), bus.namespace + ":dead-letter")
