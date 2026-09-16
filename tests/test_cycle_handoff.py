"""`zeus cycle handoff` / LocalCycle.handoff: read-only projection (INV-CYCLE-HANDOFF-001).

Fixture executors, rows and canary values here are synthetic; nothing is actual provider evidence.
"""
from copy import deepcopy

import pytest

from codex_harness import cli
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.local_cycle import LocalCycle
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, envelope

CORR = "improvement:cycle-handoff-test"
FOREIGN = "improvement:foreign"
CANARY = "CANARY-must-never-be-emitted"
CANDIDATE = {"base": "base-sha", "revision": "rev-sha", "tree": "tree-sha", "diff_hash": "diff-sha",
             "author": "worker:implementation", "path": "D:/absolute/candidate/" + CANARY}
SECRETS = {"input": {"prompt": CANARY}, "prompt": CANARY, "summary": CANARY, "stdout": CANARY,
           "error": CANARY, "messages": [CANARY], "settings": {"token": CANARY}}


def service():
    return Harness(MemoryStore(), organization())


def task(svc, task_id, status="queued", correlation=CORR, **extra):
    message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                       {"plan": {"objective": CANARY}}, correlation)
    with svc.store.transaction() as tx:
        tx.put("tasks", task_id, {"id": task_id, "agent": "worker:implementation", "status": status,
                                  "attempt": 0, "message": message, "created_at": "2026-09-16T00:00:00+00:00",
                                  **extra})


def decision(svc, decision_id, status="pending", correlation=CORR, **extra):
    message = envelope("task.result", "worker:implementation", "lead:improvement", "implement",
                       {"summary": CANARY}, correlation)
    with svc.store.transaction() as tx:
        tx.put("decisions_pending", decision_id, {"id": decision_id, "actor": "lead:improvement",
                                                  "phase": "review_lead", "status": status, "attempt": 0,
                                                  "message": message, **extra})


class FakeExecutor:
    """Stand-in that settles the first open row with a result carrying canary fields."""

    def __init__(self, svc, accepted=None):
        self.svc, self.accepted, self.calls = svc, accepted, []

    def _finish(self, bucket, agent, kind):
        self.calls.append(kind)
        with self.svc.store.transaction() as tx:
            rows = [r for r in tx.scan(bucket) if r.get("agent", r.get("actor")) == agent
                    and r["status"] in {"queued", "pending"}]
            if not rows:
                return None
            row = rows[0]
            result = {"candidate": dict(CANDIDATE), "execution_ref": "sha256:" + kind + "-ref",
                      "evidence_inspection": {"verdict": "verified", "claims": 3, "output": CANARY}, **SECRETS}
            if self.accepted is not None:
                result["accepted"] = self.accepted
            row.update(status="succeeded", result=result, attempt=1, generation=2, **SECRETS)
            tx.put(bucket, row["id"], row)
            return row

    def execute_one(self, agent, expected=None):
        return self._finish("tasks", agent, "task")

    def decide_one(self, agent, expected=None):
        return self._finish("decisions_pending", agent, "decision")


class Untouchable:
    """Any executor/bus/workflow contact from handoff is a failure."""

    def __getattr__(self, name):
        raise AssertionError("handoff touched " + name)


def set_cycle(svc, cycle_id="c1", **fields):
    with svc.store.transaction() as tx:
        row = tx.get("local_cycles", cycle_id)
        row.update(**fields)
        tx.put("local_cycles", cycle_id, row)


def handoff(svc, cycle_id="c1"):
    before = deepcopy(svc.store.data)
    view = LocalCycle(svc, Untouchable(), Untouchable(), Untouchable()).handoff(cycle_id)
    assert svc.store.data == before  # reads leave every table unchanged
    assert view["schema"] == "urn:zeus:cycle-handoff:1"
    assert view["authority"] == "observation_only" and view["automatic_resume"] is False
    assert CANARY not in repr(view)
    return view


# ----- 1. initial active cycle -----------------------------------------------------------------
def test_initial_active_cycle_has_no_target_and_full_headroom():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    view = handoff(svc)
    assert view["cycle"]["status"] == "active" and view["cycle"]["executions"] == 0
    assert view["remaining_executions"] == 2
    assert view["target_record"] == {"availability": "none", "kind": None, "id": None}
    assert set(view["cycle"]) == {"id", "correlation_id", "status", "max_executions", "executions", "in_flight",
                                  "stopped_reason", "last_execution", "created_at", "updated_at"}


# ----- 2. completed worker task / accepted review -----------------------------------------------
def test_completed_task_and_accepted_review_expose_whitelisted_metadata_only():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    task(svc, "t1")
    assert LocalCycle(svc, FakeExecutor(svc)).step("c1")["execution"]["status"] == "succeeded"
    view = handoff(svc)
    record = view["target_record"]
    assert record["availability"] == "found" and record["kind"] == "task" and record["id"] == "t1"
    assert record["status"] == "succeeded" and record["attempt"] == 1 and record["generation"] == 2
    assert record["phase"] is None
    assert record["result"] == {"candidate": {"base": "base-sha", "revision": "rev-sha", "tree": "tree-sha",
                                              "diff_hash": "diff-sha"},
                                "execution_ref": "sha256:task-ref", "evidence_verdict": "verified",
                                "accepted": None}
    assert view["remaining_executions"] == 1
    decision(svc, "d1")
    assert LocalCycle(svc, FakeExecutor(svc, accepted=True)).step("c1")["cycle"]["status"] == "awaiting_operator"
    view = handoff(svc)
    record = view["target_record"]
    assert record["kind"] == "decision" and record["id"] == "d1" and record["phase"] == "review_lead"
    assert record["result"]["accepted"] is True and record["result"]["execution_ref"] == "sha256:decision-ref"
    assert record["result"]["candidate"]["revision"] == "rev-sha"
    assert view["remaining_executions"] == 0 and view["cycle"]["status"] == "awaiting_operator"
    for key in ("input", "prompt", "summary", "stdout", "error", "messages", "settings", "message", "path", "author"):
        assert key not in record and key not in record["result"] and key not in record["result"]["candidate"]


def test_rejected_review_reports_boolean_false():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    decision(svc, "d1")
    LocalCycle(svc, FakeExecutor(svc, accepted=False)).step("c1")
    assert handoff(svc)["target_record"]["result"]["accepted"] is False


# ----- 3. stopped / budget exhausted / in flight -------------------------------------------------
def test_stopped_and_exhausted_and_in_flight_states_are_reported_without_repair():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    set_cycle(svc, status="stopped", stopped_reason="budget_exhausted", executions=2)
    view = handoff(svc)
    assert view["cycle"]["status"] == "stopped" and view["cycle"]["stopped_reason"] == "budget_exhausted"
    assert view["remaining_executions"] == 0
    set_cycle(svc, executions=5)  # over-budget residue: display clamps, stored count untouched
    view = handoff(svc)
    assert view["remaining_executions"] == 0 and view["cycle"]["executions"] == 5
    marker = {"agent": "worker:implementation", "kind": "task", "id": "t1", "at": "x"}
    set_cycle(svc, status="active", stopped_reason=None, executions=1, in_flight=marker)
    view = handoff(svc)
    assert view["cycle"]["in_flight"] == marker and view["cycle"]["status"] == "active"
    assert view["target_record"]["availability"] == "none"  # a marker is not a last execution
    assert LocalCycle(svc).status("c1")["in_flight"] == marker


# ----- 4. missing / foreign / unsupported target, malformed optional result ----------------------
def last_execution(kind, target_id):
    return {"agent": "worker:implementation", "kind": kind, "id": target_id, "status": "succeeded",
            "claimed": True, "result_id": target_id, "at": "2026-09-16T00:00:00+00:00"}


def test_missing_target_is_explicitly_missing():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    set_cycle(svc, executions=1, last_execution=last_execution("task", "t-gone"))
    assert handoff(svc)["target_record"] == {"availability": "missing", "kind": "task", "id": "t-gone"}
    set_cycle(svc, last_execution=last_execution("decision", "d-gone"))
    assert handoff(svc)["target_record"] == {"availability": "missing", "kind": "decision", "id": "d-gone"}
    set_cycle(svc, last_execution=last_execution("task", None))
    assert handoff(svc)["target_record"] == {"availability": "missing", "kind": "task", "id": None}


def test_foreign_correlation_target_yields_no_data():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    task(svc, "t-foreign", status="succeeded", correlation=FOREIGN,
         result={"candidate": dict(CANDIDATE), "execution_ref": "sha256:foreign", "accepted": True}, **SECRETS)
    set_cycle(svc, executions=1, last_execution=last_execution("task", "t-foreign"))
    assert handoff(svc)["target_record"] == {"availability": "correlation_mismatch", "kind": "task",
                                             "id": "t-foreign"}
    with svc.store.transaction() as tx:  # a target without a message has no correlation to match
        row = tx.get("tasks", "t-foreign")
        row["message"] = None
        tx.put("tasks", "t-foreign", row)
    assert handoff(svc)["target_record"]["availability"] == "correlation_mismatch"


def test_unsupported_kind_and_malformed_last_execution_are_explicit():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    set_cycle(svc, executions=1, last_execution=last_execution("release", "r1"))
    assert handoff(svc)["target_record"] == {"availability": "unsupported_kind", "kind": "release", "id": "r1"}
    set_cycle(svc, last_execution=last_execution(None, "x"))
    assert handoff(svc)["target_record"] == {"availability": "unsupported_kind", "kind": None, "id": "x"}
    set_cycle(svc, last_execution="not-a-dict")
    assert handoff(svc)["target_record"] == {"availability": "none", "kind": None, "id": None}


@pytest.mark.parametrize("result", [None, "junk", [], {}, {"candidate": "junk", "execution_ref": 7,
                                                            "evidence_inspection": "junk", "accepted": "yes"}])
def test_empty_or_malformed_result_stays_null_never_invented(result):
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    decision(svc, "d1", status="succeeded", result=result, attempt="1", generation=None, phase=None)
    set_cycle(svc, executions=1, last_execution=last_execution("decision", "d1"))
    record = handoff(svc)["target_record"]
    assert record["availability"] == "found" and record["status"] == "succeeded"
    assert record["attempt"] is None and record["generation"] is None and record["phase"] is None
    assert record["result"] == {"candidate": None, "execution_ref": None, "evidence_verdict": None, "accepted": None}


def test_partial_candidate_keeps_only_string_fields():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    task(svc, "t1", status="succeeded",
         result={"candidate": {"revision": "rev", "base": 12, "tree": None, "path": CANARY}, "accepted": True})
    set_cycle(svc, executions=1, last_execution=last_execution("task", "t1"))
    record = handoff(svc)["target_record"]
    assert record["result"]["candidate"] == {"base": None, "revision": "rev", "tree": None, "diff_hash": None}
    assert record["result"]["accepted"] is None  # acceptance is a decision result only


# ----- 5. unknown cycle / store failure / same view / current row ------------------------------
def test_unknown_cycle_and_store_failure_fail_explicitly():
    svc = service()
    with pytest.raises(ContractError, match="Unknown cycle"):
        LocalCycle(svc).handoff("absent")

    class BrokenStore:
        def transaction(self):
            raise RuntimeError("store unavailable")
    with pytest.raises(RuntimeError, match="store unavailable"):
        LocalCycle(Harness(BrokenStore(), organization())).handoff("c1")


def test_fresh_object_yields_same_view_and_changed_target_is_current_row():
    svc = service()
    LocalCycle(svc).start("c1", CORR, 2)
    task(svc, "t1")
    LocalCycle(svc, FakeExecutor(svc)).step("c1")
    first = handoff(svc)
    assert LocalCycle(svc).handoff("c1") == first
    assert LocalCycle(Harness(svc.store, organization())).handoff("c1") == first
    with svc.store.transaction() as tx:  # the row moves on after the execution that was recorded
        row = tx.get("tasks", "t1")
        row.update(status="superseded", result={"execution_ref": "sha256:later"})
        tx.put("tasks", "t1", row)
    later = handoff(svc)["target_record"]
    assert later["status"] == "superseded" and later["result"]["execution_ref"] == "sha256:later"
    assert later["result"]["candidate"] is None
    assert handoff(svc)["cycle"]["last_execution"] == first["cycle"]["last_execution"]


# ----- 6. CLI ---------------------------------------------------------------------------------
def test_cli_handoff_builds_no_executor_bus_or_observer(monkeypatch):
    svc = service()
    outputs = []
    monkeypatch.setattr(cli, "emit", outputs.append)

    def forbidden(*args, **kwargs):
        raise AssertionError("handoff built infrastructure")
    for name in ("build_executor", "build_observer", "RedisBus", "redis_url", "Workflow"):
        monkeypatch.setattr(cli, name, forbidden)
    cli.cycle_command(svc, cli.parser().parse_args(["cycle", "start", "c1", "--correlation", CORR,
                                                    "--max-executions", "2"]))
    cli.cycle_command(svc, cli.parser().parse_args(["cycle", "handoff", "c1"]))
    cli.cycle_command(svc, cli.parser().parse_args(["cycle", "status", "c1"]))
    start, view, status = outputs
    assert view["schema"] == "urn:zeus:cycle-handoff:1" and view["automatic_resume"] is False
    assert view["cycle"]["id"] == "c1" and view["target_record"]["availability"] == "none"
    assert start["status"] == "active" and "target_record" not in start and "schema" not in start
    assert status["remaining_executions"] == 2 and "target_record" not in status and "schema" not in status
    assert cli.parser().parse_args(["cycle", "step", "c1"]).cycle_command == "step"
    with pytest.raises(AssertionError, match="built infrastructure"):
        cli.cycle_command(svc, cli.parser().parse_args(["cycle", "step", "c1"]))
    with pytest.raises(ContractError, match="Unknown cycle"):
        cli.cycle_command(svc, cli.parser().parse_args(["cycle", "handoff", "absent"]))
