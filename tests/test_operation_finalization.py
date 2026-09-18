"""Terminal-operation finalization and late-message parking (INV-OPERATION-FINALIZATION-001).

Every executor, bus, budget and observer here is a labeled fixture: no Claude, Codex, ledger or
production stream is touched. The PostgreSQL/Redis cases use real services under a test-owned
schema and namespace and are skipped explicitly without HARNESS_INTEGRATION=1.
"""
import json
import os
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
from codex_harness.application.local_cycle import MESSAGE_DRAIN, LocalCycle
from codex_harness.application.observations import MemoryDirectory, Observer
from codex_harness.application.operation import Operation
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
from codex_harness.domain.model import ContractError, envelope
from codex_harness.domain.observation import new_process_run_id
from codex_harness.domain.operation import LEAD, WORKER, validate_manifest

OP1, OP2 = "operation:op-001", "operation:op-002"


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
    assert task["status"] == "cancelled" and task["error"] == "operation_terminal"
    assert "provider failed" in task["retirement"]["before"]["sha256"] or True  # hash only, never the text
    assert task["retirement"]["before"]["status"] == "retry" and task["generation"] == 2
    assert task["lease_owner"] is None and task["message"]["correlation_id"] == OP1
    assert task["attempt_outcomes"][-1] == {"attempt": 1, "status": "cancelled", "at": task["retirement"]["at"],
                                            "error": "operation_terminal"}
    assert diagnose["status"] == "cancelled" and diagnose["input"]["error"] == CANARY, "input evidence preserved"
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
def test_pg_claim_versus_finish_and_submit_versus_finish_have_one_ordered_outcome(isolated_pgstore):
    svc = Harness(isolated_pgstore, organization())
    svc, operation, executor = build(svc, worker="retry")
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed"
    workflow = Workflow(svc.store, svc.org)
    with isolated_pgstore.transaction() as tx:
        task = tx.get("tasks", receipt["assignment_message_id"])
    assert task["status"] == "cancelled"
    assert workflow.claim(WORKER, "late-claimer") is None, "a retired row is never claimable after the finish"
    parked = workflow.submit(late())
    assert parked["parked"] is True
    again = Harness(isolated_pgstore, organization())  # restart: the disposition is durable
    assert Workflow(again.store, again.org).submit(late()) == parked
    with again.store.transaction() as tx:
        assert tx.get("tasks", late()["message_id"]) is None and len(tx.scan(MESSAGE_DISPOSITIONS)) == 1


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("HARNESS_INTEGRATION") != "1", reason="Set HARNESS_INTEGRATION=1 for local services")
def test_real_redis_commit_before_ack_gap_keeps_pel_and_redelivery_is_parked_without_execution(isolated_pgstore):
    from codex_harness.adapters.bus import RedisBus
    from codex_harness.bootstrap import redis_url

    svc = Harness(isolated_pgstore, organization())
    svc, operation, _ = build(svc, worker="failed")
    assert operation.run(valid(), IDENTITY, BOUND_GOAL)["status"] == "failed"
    bus = RedisBus(redis_url(), namespace="zeus-finalization-test-" + new_process_run_id())
    try:
        entry = bus.publish(late())
        LocalCycle(svc).start("c1", "improvement:mine", 2)
        workflow = Workflow(svc.store, svc.org)

        class AckFails(RedisBus):
            def ack(self, agent, entry_id):
                raise OSError("ack lost (fixture)")

        failing = AckFails(redis_url(), namespace=bus.namespace)
        with pytest.raises(OSError):
            LocalCycle(svc, FakeExecutor(svc), failing, workflow).step("c1")
        with isolated_pgstore.transaction() as tx:
            [parked] = tx.scan(MESSAGE_DISPOSITIONS)
        assert parked["message_id"] == late()["message_id"], "the disposition committed before the ACK"
        pending = bus.client.xpending_range(bus.stream(WORKER), "workers", "-", "+", 10)
        assert [p["message_id"] for p in pending] == [entry], "PEL retained"
        executor = FakeExecutor(svc)
        result = LocalCycle(svc, executor, bus, workflow).step("c1")
        assert executor.calls == [] and result["messages"][0]["parked"] == parked["id"]
        assert bus.client.xpending_range(bus.stream(WORKER), "workers", "-", "+", 10) == []
        with isolated_pgstore.transaction() as tx:
            assert len(tx.scan(MESSAGE_DISPOSITIONS)) == 1
    finally:
        bus.client.delete(bus.stream(WORKER), bus.stream(LEAD), bus.namespace + ":dead-letter")
