"""LocalCycle: bounded persistent loop. Fixture executors here are stand-ins, not Claude or Codex."""
from types import SimpleNamespace

import pytest

from codex_harness import cli
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.local_cycle import LocalCycle
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, envelope

CORR = "improvement:cycle-test"


def service():
    return Harness(MemoryStore(), organization())


def task(svc, task_id, status="queued", correlation=CORR, agent="worker:implementation"):
    message = envelope("task.assign", "lead:improvement", agent, "implement", {"plan": {}}, correlation)
    with svc.store.transaction() as tx:
        tx.put("tasks", task_id, {"id": task_id, "agent": agent, "status": status, "attempt": 0,
                                  "message": message, "created_at": "2026-09-16T00:00:00+00:00"})


def decision(svc, decision_id, phase="review_lead", status="pending", correlation=CORR, actor="lead:improvement"):
    message = envelope("task.result", "worker:implementation", actor, "implement", {}, correlation)
    with svc.store.transaction() as tx:
        tx.put("decisions_pending", decision_id, {"id": decision_id, "actor": actor, "phase": phase,
                                                  "status": status, "attempt": 0, "message": message})


class FakeExecutor:
    def __init__(self, svc, outcome="succeeded", accepted=None, raise_error=None):
        self.svc, self.outcome, self.accepted, self.raise_error, self.calls = svc, outcome, accepted, raise_error, []

    def _finish(self, bucket, agent, kind):
        self.calls.append((kind, agent))
        if self.raise_error:
            raise self.raise_error
        with self.svc.store.transaction() as tx:
            rows = [r for r in tx.scan(bucket) if r.get("agent", r.get("actor")) == agent
                    and r["status"] in {"queued", "pending"}]
            if not rows:
                return None
            row = rows[0]
            row["status"] = self.outcome
            if self.accepted is not None:
                row["result"] = {"accepted": self.accepted}
            tx.put(bucket, row["id"], row)
            return row

    def execute_one(self, agent):
        return self._finish("tasks", agent, "task")

    def decide_one(self, agent):
        return self._finish("decisions_pending", agent, "decision")


def test_start_is_idempotent_and_refuses_a_different_policy():
    svc = service()
    first = LocalCycle(svc).start("c1", CORR, 2)
    assert LocalCycle(svc).start("c1", CORR, 2) == first
    with pytest.raises(ContractError, match="Conflicting cycle policy"):
        LocalCycle(svc).start("c1", CORR, 3)
    with pytest.raises(ContractError, match="Conflicting cycle policy"):
        LocalCycle(svc).start("c1", "other", 2)
    assert LocalCycle(svc).status("c1")["executions"] == 0


def test_counts_persist_across_restart_and_budget_is_never_reset():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    task(svc, "t1")
    executor = FakeExecutor(svc)
    assert LocalCycle(svc, executor).step("c1")["execution"]["status"] == "succeeded"
    task(svc, "t2")
    LocalCycle(svc).start("c1", CORR, 2)  # a restart re-issues start; nothing resets
    second = LocalCycle(svc, FakeExecutor(svc)).step("c1")
    assert second["cycle"]["executions"] == 2
    task(svc, "t3")
    third = LocalCycle(svc, FakeExecutor(svc)).step("c1")
    assert third["reason"] == "budget_exhausted" and third["cycle"]["status"] == "stopped"
    assert third["cycle"]["executions"] == 2


def test_in_flight_marker_refuses_reentry_and_is_not_released():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 3)
    task(svc, "t1")
    with svc.store.transaction() as tx:
        row = tx.get("local_cycles", "c1")
        row.update(in_flight={"agent": "worker:implementation", "kind": "task", "id": "t1", "at": "x"}, executions=1)
        tx.put("local_cycles", "c1", row)
    executor = FakeExecutor(svc)
    result = LocalCycle(svc, executor).step("c1")
    assert result["reason"] == "in_flight_residue" and executor.calls == []
    assert LocalCycle(svc).status("c1")["in_flight"]["id"] == "t1"


def test_running_residue_in_ledger_stops_without_execution():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 3)
    task(svc, "t1", status="running")
    executor = FakeExecutor(svc)
    assert LocalCycle(svc, executor).step("c1")["reason"] == "in_flight_residue"
    assert executor.calls == [] and LocalCycle(svc).status("c1")["executions"] == 0


@pytest.mark.parametrize("outcome", ["retry", "failed", "blocked"])
def test_non_success_outcome_stops_the_cycle(outcome):
    svc = service()
    LocalCycle(svc).start("c1", CORR, 3)
    task(svc, "t1")
    result = LocalCycle(svc, FakeExecutor(svc, outcome=outcome)).step("c1")
    assert result["cycle"]["status"] == "stopped" and result["reason"] == "execution_" + outcome
    assert result["cycle"]["in_flight"] is None
    executor = FakeExecutor(svc)
    assert LocalCycle(svc, executor).step("c1")["action"] == "none" and executor.calls == []


def test_executor_exception_stops_and_settles_marker():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 3)
    task(svc, "t1")
    result = LocalCycle(svc, FakeExecutor(svc, raise_error=RuntimeError("boom"))).step("c1")
    assert result["reason"] == "exception:RuntimeError" and result["cycle"]["in_flight"] is None
    assert result["cycle"]["executions"] == 1


def test_diagnose_wait_and_foreign_queue_fail_closed():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 3)
    decision(svc, "d-diag", phase="diagnose")
    executor = FakeExecutor(svc)
    assert LocalCycle(svc, executor).step("c1")["reason"] == "diagnose_pending"
    svc = service()
    LocalCycle(svc).start("c1", CORR, 3)
    task(svc, "t-mine")
    task(svc, "t-other", correlation="improvement:other")
    executor = FakeExecutor(svc)
    result = LocalCycle(svc, executor).step("c1")
    assert result["reason"].startswith("foreign_queue:") and executor.calls == []


def test_review_lead_rejection_continues_and_acceptance_awaits_operator():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 4)
    decision(svc, "d1")
    result = LocalCycle(svc, FakeExecutor(svc, accepted=False)).step("c1")
    assert result["cycle"]["status"] == "active" and result["execution"]["kind"] == "decision"
    decision(svc, "d2")
    result = LocalCycle(svc, FakeExecutor(svc, accepted=True)).step("c1")
    assert result["cycle"]["status"] == "awaiting_operator"
    executor = FakeExecutor(svc)
    assert LocalCycle(svc, executor).step("c1")["reason"] == "awaiting_operator" and executor.calls == []


def test_pending_conductor_review_reports_awaiting_operator_and_idle_is_not_success():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    assert LocalCycle(svc, FakeExecutor(svc)).step("c1")["reason"] == "idle"
    decision(svc, "d-conductor", phase="review_conductor", actor="conductor")
    result = LocalCycle(svc, FakeExecutor(svc)).step("c1")
    assert result["reason"] == "awaiting_operator" and result["cycle"]["executions"] == 0


class Bus:
    """In-memory stand-in for the Redis consumer group: receive, decode, ack, dead_letter, publish."""

    def __init__(self, queued):
        self.queued, self.acked, self.dead, self.published = list(queued), [], [], []

    def receive(self, agent, consumer):
        for entry in self.queued:
            if entry[1]["who"]["recipient"] == agent and entry[0] not in self.acked:
                return entry[0], {"body": entry[1]}
        return None

    @staticmethod
    def decode(fields):
        return fields["body"]

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)

    def dead_letter(self, agent, entry_id, fields, reason):
        self.dead.append(entry_id)
        self.acked.append(entry_id)

    @staticmethod
    def validate(message):
        return message

    def publish(self, message):
        self.published.append(message)
        return "1-0"


def test_foreign_correlation_message_is_left_pending_and_stops():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    foreign = envelope("task.assign", "conductor", "lead:improvement", "plan", {"objective": "x"}, "improvement:other")
    bus = Bus([("1-0", foreign)])
    handled = []
    workflow = SimpleNamespace(handle=lambda message: handled.append(message) or {"handled": True})
    result = LocalCycle(svc, FakeExecutor(svc), bus, workflow).step("c1")
    assert result["reason"] == "foreign_correlation" and result["cycle"]["status"] == "stopped"
    assert bus.acked == [] and bus.dead == [] and handled == []


def test_own_message_is_handled_relayed_and_acked_before_execution():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    own = envelope("task.assign", "conductor", "lead:improvement", "plan", {"objective": "x"}, CORR)
    bus = Bus([("1-0", own)])
    handled = []
    workflow = SimpleNamespace(handle=lambda message: handled.append(message) or {"handled": True})
    result = LocalCycle(svc, FakeExecutor(svc), bus, workflow).step("c1")
    assert bus.acked == ["1-0"] and len(handled) == 1
    assert result["messages"][0]["type"] == "task.assign" and result["reason"] == "idle"


def test_cli_start_and_status_use_local_cycle(monkeypatch):
    svc = service()
    outputs = []
    monkeypatch.setattr(cli, "emit", outputs.append)
    args = cli.parser().parse_args(["cycle", "start", "c1", "--correlation", CORR, "--max-executions", "2"])
    cli.cycle_command(svc, args)
    cli.cycle_command(svc, cli.parser().parse_args(["cycle", "status", "c1"]))
    assert outputs[0]["max_executions"] == 2 and outputs[1]["status"] == "active"
    assert cli.parser().parse_args(["cycle", "step", "c1"]).cycle_command == "step"
