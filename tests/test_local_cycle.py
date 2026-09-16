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

    def execute_one(self, agent, expected=None):
        return self._finish("tasks", agent, "task")

    def decide_one(self, agent, expected=None):
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


# ----- real Workflow / Executor paths; the provider is a labeled fixture, never Claude or Codex -----
def real_executor(tmp_path, monkeypatch, store=None, verdict=None):
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.executor import Executor
    from codex_harness.application.workflow import Workflow

    svc = Harness(store or MemoryStore(), organization())
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    git = SimpleNamespace(repository=tmp_path, inspect=lambda *a: {}, review_workspace=lambda *a: str(tmp_path),
                          _git=lambda *a, **k: "" if a[0] == "status" else "candidate",
                          prepare=lambda *a: {"path": str(workspace), "branch": "harness/t", "base": "base", "task_id": "t"},
                          capture=lambda ws: {"revision": "candidate", "base": "base", "tree": "tree"})
    executor = Executor(svc, git, FileArtifacts(str(tmp_path / "artifacts")))
    runs = []

    def fixture_run(agent, key, objective, *a, **k):
        runs.append((agent, key))
        if agent == "lead:improvement":
            return {"accepted": verdict, "reason": "fixture review verdict", "execution_ref": "fixture:review"}
        return {"summary": "fixture implementation", "tests": [], "execution_ref": "fixture:implement"}
    monkeypatch.setattr(executor, "_run", fixture_run)
    monkeypatch.setattr(executor, "_inspect_evidence", lambda *a, **k: {"verdict": "not_inspected_in_unit", "claims": 0})
    return svc, executor, Workflow(svc.store, svc.org), runs


def implement(correlation=CORR):
    return envelope("task.assign", "lead:improvement", "worker:implementation", "implement", {"plan": {}}, correlation)


def test_real_workflow_success_reaches_review_lead_and_rejection_reworks(tmp_path, monkeypatch):
    svc, executor, workflow, runs = real_executor(tmp_path, monkeypatch, verdict=False)
    bus = Bus([])
    cycle = LocalCycle(svc, executor, bus, workflow)
    cycle.start("c1", CORR, 4)
    workflow.submit(implement())
    first = cycle.step("c1")
    assert first["execution"]["status"] == "succeeded" and first["execution"]["kind"] == "task"
    assert bus.published[-1]["type"] == "task.result"  # relayed through the existing outbox
    bus.queued.append(("1-0", bus.published[-1]))
    second = cycle.step("c1")  # task.result -> review_lead decision -> fixture rejection -> rework implement
    assert second["messages"][0]["type"] == "task.result" and second["execution"]["kind"] == "decision"
    assert second["execution"]["status"] == "succeeded" and second["cycle"]["status"] == "active"
    rework = bus.published[-1]
    assert rework["type"] == "task.assign" and rework["who"]["recipient"] == "worker:implementation"
    assert rework["what"]["details"]["rework"] == 1 and rework["correlation_id"] == CORR
    bus.queued.append(("2-0", rework))
    third = cycle.step("c1")
    assert third["execution"]["kind"] == "task" and third["execution"]["status"] == "succeeded"
    assert third["cycle"]["executions"] == 3
    assert [r[0] for r in runs] == ["worker:implementation", "lead:improvement", "worker:implementation"]


def test_real_workflow_acceptance_stops_before_the_conductor(tmp_path, monkeypatch):
    svc, executor, workflow, runs = real_executor(tmp_path, monkeypatch, verdict=True)
    bus = Bus([])
    cycle = LocalCycle(svc, executor, bus, workflow)
    cycle.start("c1", CORR, 4)
    workflow.submit(implement())
    cycle.step("c1")
    bus.queued.append(("1-0", bus.published[-1]))
    result = cycle.step("c1")
    assert result["cycle"]["status"] == "awaiting_operator" and bus.published[-1]["who"]["recipient"] == "conductor"
    with svc.store.transaction() as tx:
        assert tx.scan("release_queue") == []
    assert LocalCycle(svc, executor, bus, workflow).step("c1")["reason"] == "awaiting_operator" and len(runs) == 2


def older_foreign_task(svc, task_id="t-foreign"):
    task(svc, task_id, correlation="improvement:other")
    with svc.store.transaction() as tx:
        row = tx.get("tasks", task_id)
        row.update(created_at="2020-01-01T00:00:00+00:00", generation=0, lease_until=None, lease_owner=None,
                   result=None, error=None, input_hash="x")
        tx.put("tasks", task_id, row)


def test_real_claim_guard_refuses_a_foreign_older_task_injected_after_preflight(tmp_path, monkeypatch):
    svc, executor, workflow, runs = real_executor(tmp_path, monkeypatch)
    cycle = LocalCycle(svc, executor, None, workflow)
    cycle.start("c1", CORR, 3)
    mine = workflow.submit(implement())
    original = executor.execute_one

    def racing(agent, expected=None):
        older_foreign_task(svc)  # arrives between the cycle's scan and the claim transaction
        return original(agent, expected=expected)
    monkeypatch.setattr(executor, "execute_one", racing)
    result = cycle.step("c1")
    assert result["action"] == "refused" and result["reason"] == "claim_guard_refused"
    assert result["cycle"]["executions"] == 1 and result["cycle"]["in_flight"] is None
    assert result["cycle"]["last_execution"]["id"] == mine["id"] and runs == []
    with svc.store.transaction() as tx:
        assert tx.get("tasks", "t-foreign")["status"] == "queued"  # refused unclaimed
        assert tx.get("tasks", mine["id"])["status"] == "queued"
    # The unguarded default keeps the existing policy: the older task is the one claimed.
    assert workflow.claim("worker:implementation", "plain")["id"] == "t-foreign"


def test_claim_guard_validates_identity_correlation_and_status(tmp_path, monkeypatch):
    from codex_harness.application.workflow import ClaimGuardRefused
    svc, executor, workflow, runs = real_executor(tmp_path, monkeypatch)
    mine = workflow.submit(implement())
    guard = {"id": mine["id"], "correlation_id": CORR, "statuses": {"queued"}}
    with pytest.raises(ClaimGuardRefused, match="missing"):
        workflow.claim("worker:implementation", "o", expected={**guard, "id": "absent"})
    with pytest.raises(ClaimGuardRefused, match="correlation"):
        workflow.claim("worker:implementation", "o", expected={**guard, "correlation_id": "improvement:other"})
    with pytest.raises(ClaimGuardRefused, match="status"):
        workflow.claim("worker:implementation", "o", expected={**guard, "statuses": {"retry"}})
    with pytest.raises(ContractError, match="Invalid execution guard"):
        workflow.claim("worker:implementation", "o", expected={"id": mine["id"]})
    claimed = workflow.claim("worker:implementation", "o", expected=guard)
    assert claimed["id"] == mine["id"] and claimed["status"] == "running"
    # decide_one: a foreign older pending decision is refused before any provider entry.
    decision(svc, "d-foreign", correlation="improvement:other")
    decision(svc, "d-mine")
    candidate = {"revision": "candidate", "base": "base", "tree": "tree", "author": "worker:implementation"}
    with svc.store.transaction() as tx:
        for key in ("d-foreign", "d-mine"):
            row = tx.get("decisions_pending", key)
            row["input"] = {"candidate": candidate}
            tx.put("decisions_pending", key, row)
    with pytest.raises(ClaimGuardRefused, match="instead of d-mine"):
        executor.decide_one("lead:improvement", expected={"id": "d-mine", "correlation_id": CORR, "statuses": {"pending"}})
    with svc.store.transaction() as tx:
        assert {r["status"] for r in tx.scan("decisions_pending")} == {"pending"}
    assert runs == []


def test_concurrent_step_on_the_same_cycle_executes_once():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 3)
    task(svc, "t1")
    inner = FakeExecutor(svc)
    seen = []

    class Overlapping(FakeExecutor):
        def execute_one(self, agent, expected=None):
            seen.append(LocalCycle(svc, inner).step("c1"))  # a second process steps while we hold the slot
            return super().execute_one(agent, expected)
    outer = Overlapping(svc)
    result = LocalCycle(svc, outer).step("c1")
    assert result["execution"]["status"] == "succeeded" and result["cycle"]["executions"] == 1
    assert seen[0]["reason"] == "in_flight_residue" and inner.calls == [] and len(outer.calls) == 1


def test_cycle_policy_persists_in_postgres_across_instances(isolated_pgstore):
    svc = Harness(isolated_pgstore, organization())
    LocalCycle(svc).start("c1", CORR, 2)
    task(svc, "t1")
    assert LocalCycle(svc, FakeExecutor(svc)).step("c1")["cycle"]["executions"] == 1
    again = Harness(isolated_pgstore, organization())  # a new process over the same schema
    with pytest.raises(ContractError, match="Conflicting cycle policy"):
        LocalCycle(again).start("c1", CORR, 5)
    assert LocalCycle(again).start("c1", CORR, 2)["executions"] == 1
    task(again, "t2")
    assert LocalCycle(again, FakeExecutor(again)).step("c1")["cycle"]["executions"] == 2
    task(again, "t3")
    stopped = LocalCycle(again, FakeExecutor(again)).step("c1")
    assert stopped["reason"] == "budget_exhausted" and LocalCycle(again).status("c1")["executions"] == 2
