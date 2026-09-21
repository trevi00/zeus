"""Operation state machine (INV-OPERATION-001). Every executor, budget and collector here is a
labeled fixture (fault injection), never Claude, Codex or the machine ledger."""
import json
from copy import deepcopy

import pytest

from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import owner_handoff_view
from codex_harness.application.local_cycle import LocalCycle
from codex_harness.application.operation import Operation, OperationRefused
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, envelope
from codex_harness.domain.operation import (
    MAX_EXECUTIONS,
    ManifestError,
    assignment_message_id,
    validate_manifest,
)

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
GOAL = {"path": "docs/zeus/operations/GOAL.md", "sha256": "b" * 64, "criterion": "one-start entry point",
        "rationale": "the runbook task exercises the entry point"}
IDENTITY = {"repository": "r", "runtime": "d", "runtime_policy": "p", "provider": {"policy_digest": "x", "config_digest": "y"}}
BOUND_GOAL = {**GOAL, "base_revision": BASE, "bytes": 3}


def manifest(**overrides):
    document = {"schema": "urn:zeus:operation:1", "id": "op-001", "base_revision": BASE, "goal": dict(GOAL),
                "plan": {"objective": "Add the RUNBOOK note " + CANARY, "acceptance_criteria": ["focused tests pass"],
                         "allowed_paths": ["docs/zeus/operations/operation-entrypoint-001/RUNBOOK.md"]},
                "budget": {"per_host": 4, "total": 8},
                "claude": {"model": "claude-fixture-model", "timeout_seconds": 300, "max_budget_usd": 2}}
    for key, value in overrides.items():
        outer, _, inner = key.partition(".")
        if inner:
            document[outer][inner] = value
        else:
            document[outer] = value
    return document


def valid():
    return validate_manifest(manifest(), packaged_policy())


class Bus:
    def __init__(self):
        self.queued, self.acked, self.published = [], [], []

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
        self.acked.append(entry_id)

    @staticmethod
    def validate(message):
        return message

    def publish(self, message):
        entry = str(len(self.published) + 1) + "-0"
        self.published.append(message)
        self.queued.append((entry, message))
        return entry


class FakeBudget:
    """Fault-injected stand-in for the machine CallBudget."""

    def __init__(self, refuse_after=None, settle_fail=None):
        """`settle_fail` is the 1-based settlement ordinal that fails (fixture); None never fails."""
        self.reserved, self.settled, self.refuse_after, self.settle_fail = [], [], refuse_after, settle_fail
        self.settle_calls = 0

    def reserve(self, *, per_host, total, purpose, provider, model):
        if self.refuse_after is not None and len(self.reserved) >= self.refuse_after:
            raise ContractError("ledger full (fixture)")
        slot = {"id": "slot-" + str(len(self.reserved) + 1), "reserved_at": "t", "purpose": purpose,
                "per_host": per_host, "total": total, "provider": provider, "model": model}
        self.reserved.append(slot)
        return slot

    def settle(self, slot_id, *, outcome, detail=None):
        self.settle_calls += 1
        if self.settle_fail == self.settle_calls:
            raise OSError("settle failed (fixture)")
        self.settled.append((slot_id, outcome))


# Fixture bindings that belong to ANOTHER execution than the one the operation is running: one
# per field of the execution identity an inspection is bound to.
FOREIGN_BINDINGS = {"foreign": ("task_id", "someone-else"), "foreign_generation": ("generation", 7),
                    "foreign_attempt": ("attempt", 4), "foreign_revision": ("source_revision", "9" * 40)}
WITH_INSPECTION_ROW = {"bound", "incomplete", "unidentified", *FOREIGN_BINDINGS}


class FakeExecutor:
    """Settles the guarded row the way the real executor would; provider entries are counted."""

    def __init__(self, svc, worker="succeeded", verdict=True, inspection="bound", raise_error=None):
        self.svc, self.worker, self.verdict, self.inspection, self.raise_error = svc, worker, verdict, inspection, raise_error
        self.calls = []

    def execute_one(self, agent, expected=None):
        self.calls.append("task")
        if self.raise_error:
            raise self.raise_error
        with self.svc.store.transaction() as tx:
            task = tx.get("tasks", expected["id"])
            task.update(status=self.worker, attempt=1, generation=1, lease_owner="fixture")
            if self.inspection == "unidentified":
                # A row whose execution identity cannot be read back: the current binding is
                # incomplete, so no finding can be attributed to this run at all.
                task.update(generation=None, attempt=None)
            if self.worker == "succeeded":
                candidate = {"revision": "c" * 40, "base": BASE, "tree": "t" * 40, "diff_hash": "d" * 64,
                             "path": "D:/secret/" + CANARY}
                inspection_id = "insp-" + task["id"]
                binding = {"task_id": task["id"], "generation": 1, "attempt": 1, "source_revision": candidate["revision"]}
                if self.inspection in FOREIGN_BINDINGS:
                    field, value = FOREIGN_BINDINGS[self.inspection]
                    binding[field] = value
                if self.inspection in WITH_INSPECTION_ROW:
                    # Two host-declared checks, as a profiled inspection records them: one replayed
                    # and agreed, one the worker never reported. The raw text is the CANARY on
                    # purpose: nothing from a finding's cause may reach an owner handoff.
                    findings = [{"claim": {"kind": "project_check", "check_id": "unit", "status": "executed",
                                           "argv": ["python", "-m", "pytest", CANARY]}, "state": "checked", "cause": None},
                                {"claim": {"kind": "project_check", "check_id": "lint", "status": "missing"},
                                 "state": "not_checked", "cause": "required check has no observation " + CANARY}]
                    tx.put("evidence_inspections", inspection_id, {
                        "id": inspection_id, "binding": binding, "policy_hash": "ph", "findings": findings,
                        "verdict": "incomplete" if self.inspection == "incomplete" else "all_checked",
                        "denominator": {"claims": 2, "checked": 0 if self.inspection == "incomplete" else 1,
                                        "not_checked": 1}})
                task["result"] = {"summary": CANARY, "candidate": candidate, "execution_ref": "sha256:" + "e" * 64,
                                  "evidence_inspection": {"inspection_id": inspection_id, "verdict": "all_checked"}}
                report = envelope("task.result", task["agent"], "lead:improvement", "implement",
                                  {"task_id": task["id"], "result": task["result"]}, task["message"]["correlation_id"])
                tx.put("outbox", report["message_id"], {"message": report, "sent": False})
            else:
                task["error"] = "provider failed: " + CANARY
            tx.put("tasks", task["id"], task)
            return task

    def decide_one(self, agent, expected=None):
        self.calls.append("decision")
        with self.svc.store.transaction() as tx:
            row = tx.get("decisions_pending", expected["id"])
            row.update(status="succeeded", result={"accepted": self.verdict, "reason": CANARY,
                                                   "execution_ref": "sha256:" + "f" * 64})
            tx.put("decisions_pending", row["id"], row)
            return row


class Collector:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def collect(self):
        self.calls += 1
        return {"files": 1, "records": 3, "inserted": 3, "sink_failures": 1 if self.fail else 0, "corrupt": 0}


def build(svc=None, **kwargs):
    svc = svc or Harness(MemoryStore(), organization())
    executor = FakeExecutor(svc, **{k: v for k, v in kwargs.items() if k in {"worker", "verdict", "inspection", "raise_error"}})
    budget = kwargs.get("budget") or FakeBudget()
    collector = kwargs.get("collector") or Collector()
    operation = Operation(svc, executor, Bus(), Workflow(svc.store, svc.org), budget, collector)
    return svc, operation, executor, budget, collector


def run(**kwargs):
    svc, operation, executor, budget, collector = build(**kwargs)
    return operation.run(valid(), IDENTITY, BOUND_GOAL), svc, executor, budget, collector


# ----- manifest ------------------------------------------------------------------------------
@pytest.mark.parametrize("field, value", [
    ("schema", "urn:zeus:operation:2"), ("id", "../x"), ("id", ""), ("base_revision", "abc"), ("extra", 1),
    ("goal.path", "../GOAL.md"), ("goal.path", ".git/config.md"), ("goal.path", "C:\\GOAL.md"), ("goal.path", "goal.txt"),
    ("goal.sha256", "B" * 64), ("goal.criterion", ""), ("plan.acceptance_criteria", []), ("plan.allowed_paths", ["src/../x"]),
    ("plan.allowed_paths", []), ("budget.per_host", True), ("budget.total", 1), ("budget.per_host", "2"),
    ("claude.max_budget_usd", float("inf")), ("claude.max_budget_usd", 50), ("claude.timeout_seconds", 5),
    ("claude.timeout_seconds", 300.0), ("claude.model", "gpt-5"), ("claude.model", True)])
def test_manifest_refuses_unknown_wrong_typed_unsafe_and_out_of_policy_values(field, value):
    with pytest.raises(ManifestError) as info:
        validate_manifest(manifest(**{field: value}), packaged_policy())
    assert CANARY not in str(info.value) and "gpt-5" not in str(info.value)


def test_manifest_accepts_the_documented_example_and_is_deterministic():
    first, second = valid(), valid()
    assert first == second and first["budget"] == {"per_host": 4, "total": 8}
    assert assignment_message_id(first) == assignment_message_id(second)
    assert assignment_message_id(validate_manifest(manifest(id="op-002"), packaged_policy())) != assignment_message_id(first)
    with pytest.raises(ManifestError, match="missing fields"):
        validate_manifest({k: v for k, v in manifest().items() if k != "goal"}, packaged_policy())


# ----- matrix --------------------------------------------------------------------------------
def test_normal_two_stage_success_is_accepted_with_two_settled_slots_and_no_conductor():
    receipt, svc, executor, budget, collector = run()
    assert receipt["status"] == "accepted" and receipt["exit_code"] == 0 and receipt["lead_accepted"] is True
    assert executor.calls == ["task", "decision"] and len(budget.reserved) == 2 == len(budget.settled)
    assert receipt["calls"] == {"reserved": 2, "settled": 2, "slots": [
        {"id": "slot-1", "kind": "task", "agent": "worker:implementation", "provider": "claude", "outcome": "succeeded", "settled": True, "settle_error": None},
        {"id": "slot-2", "kind": "decision", "agent": "lead:improvement", "provider": "codex", "outcome": "succeeded", "settled": True, "settle_error": None}]}
    assert budget.reserved[0]["per_host"] == 4 and budget.reserved[0]["total"] == 8 and budget.reserved[0]["model"] == "claude-fixture-model"
    assert receipt["evidence"]["candidate"]["revision"] == "c" * 40 and receipt["evidence"]["inspection_id"].startswith("insp-")
    assert receipt["collection"]["sink_failures"] == 0 and collector.calls == 1
    assert receipt["cycle"]["cycle"]["executions"] == 2 == MAX_EXECUTIONS and receipt["cycle"]["automatic_resume"] is False
    with svc.store.transaction() as tx:
        assert tx.scan("release_queue") == [] and tx.get("operations", "op-001")["status"] == "accepted"
        assert [d["actor"] for d in tx.scan("decisions_pending")] == ["lead:improvement"]
    assert CANARY not in json.dumps(receipt) and CANARY not in json.dumps(Operation(svc).status("op-001"))


def test_same_id_replay_returns_the_saved_receipt_without_calls_or_a_new_assignment():
    receipt, svc, executor, budget, _ = run()
    again = Operation(svc, FakeExecutor(svc), Bus(), None, FakeBudget(), Collector())
    replay = again.run(valid(), IDENTITY, BOUND_GOAL)
    assert replay["cached"] is True and replay["exit_code"] == 0 and replay["calls"] == receipt["calls"]
    assert again.budget.reserved == [] and again.executor.calls == []
    with svc.store.transaction() as tx:
        assert len(tx.scan("outbox")) == 2  # assignment and task.result only
    with pytest.raises(OperationRefused, match="configuration_mismatch"):
        again.run(valid(), {**IDENTITY, "runtime_policy": "changed"}, BOUND_GOAL)
    with pytest.raises(OperationRefused, match="configuration_mismatch"):
        again.run(valid(), {**IDENTITY, "runtime": "other-resolved-runtime-dir"}, BOUND_GOAL)
    assert again.run(valid(), dict(IDENTITY), BOUND_GOAL)["calls"] == receipt["calls"], "unchanged restart, same receipt"
    with pytest.raises(OperationRefused, match="configuration_mismatch"):
        again.run(validate_manifest(manifest(**{"plan.objective": "other"}), packaged_policy()), IDENTITY, BOUND_GOAL)
    assert again.budget.reserved == []


def test_running_residue_and_preexisting_cycle_are_refused_without_takeover():
    svc, operation, executor, budget, _ = build()
    claimed = operation.claim(valid(), IDENTITY, BOUND_GOAL)
    assert claimed["cached"] is False
    with svc.store.transaction() as tx:
        assert tx.get("local_cycles", "operation:op-001")["executions"] == 0
        assert tx.get("outbox", assignment_message_id(valid()))["sent"] is False
    competitor = Operation(svc, FakeExecutor(svc), Bus(), None, FakeBudget(), Collector())
    with pytest.raises(OperationRefused, match="running_residue"):
        competitor.run(valid(), IDENTITY, BOUND_GOAL)
    assert competitor.executor.calls == [] and competitor.budget.reserved == []
    with svc.store.transaction() as tx:
        assert tx.get("operations", "op-001")["status"] == "running"
    fresh = Harness(MemoryStore(), organization())
    LocalCycle(fresh).start("operation:op-001", "operation:op-001", 2)
    with pytest.raises(OperationRefused, match="cycle_residue"):
        Operation(fresh, FakeExecutor(fresh), Bus(), None, FakeBudget(), Collector()).run(valid(), IDENTITY, BOUND_GOAL)
    with svc.store.transaction() as tx:
        assert tx.get("operations", "op-001") is not None
    with fresh.store.transaction() as tx:
        assert tx.get("operations", "op-001") is None


def test_interrupted_run_restart_makes_no_new_calls():
    svc, operation, executor, budget, _ = build()
    operation.claim(valid(), IDENTITY, BOUND_GOAL)
    with svc.store.transaction() as tx:  # a crash left the worker marker in flight (fixture)
        row = tx.get("local_cycles", "operation:op-001")
        row.update(in_flight={"agent": "worker:implementation", "kind": "task", "id": "t", "at": "x"}, executions=1)
        tx.put("local_cycles", "operation:op-001", row)
    restarted = Operation(svc, FakeExecutor(svc), Bus(), None, FakeBudget(), Collector())
    with pytest.raises(OperationRefused, match="running_residue"):
        restarted.run(valid(), IDENTITY, BOUND_GOAL)
    assert restarted.budget.reserved == [] and Operation(svc).status("op-001")["status"] == "running"


@pytest.mark.parametrize("worker, code", [("retry", "execution_retry"), ("failed", "execution_failed")])
def test_worker_failure_stops_before_any_reviewer_call(worker, code):
    receipt, _, executor, budget, _ = run(worker=worker)
    assert receipt["status"] == "failed" and receipt["reason_code"] == code and receipt["exit_code"] == 1
    assert executor.calls == ["task"] and len(budget.reserved) == 1 and budget.settled == [("slot-1", worker)]
    assert CANARY not in json.dumps(receipt)


def test_worker_exception_settles_the_slot_and_fails():
    receipt, _, executor, budget, _ = run(raise_error=RuntimeError(CANARY))
    assert receipt["status"] == "failed" and receipt["reason_code"] == "exception:RuntimeError"
    assert budget.settled == [("slot-1", "exception")] and executor.calls == ["task"] and CANARY not in json.dumps(receipt)


@pytest.mark.parametrize("inspection", ["missing", "foreign", "foreign_generation", "foreign_attempt",
                                        "foreign_revision", "unidentified", "incomplete"])
def test_all_checked_summary_without_a_bound_all_checked_row_stops_before_review(inspection):
    receipt, svc, executor, budget, _ = run(inspection=inspection)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "evidence_gate_refused"
    assert executor.calls == ["task"] and len(budget.reserved) == 1, "reviewer reservation and call remain zero"
    with svc.store.transaction() as tx:
        # INV-OPERATION-FINALIZATION-001: the never-started review decision is retired with the
        # failed outcome, keeping its message and input; it is not executed and not left runnable.
        [decision] = tx.scan("decisions_pending")
        assert decision["status"] == "cancelled" and decision["retirement"]["before"]["status"] == "pending"
        assert decision["input"] is not None and decision["message"]["correlation_id"] == "operation:op-001"
    assert receipt["finalization"]["retired"]["decisions_pending"] == [decision["id"]]


# ----- evidence refusal owner handoff ----------------------------------------------------------
def test_evidence_refusal_leaves_one_bounded_pending_owner_handoff_beside_the_failed_outcome():
    receipt, svc, executor, budget, _ = run(inspection="incomplete")
    handoff = receipt["owner_handoff"]
    assert receipt["status"] == "failed" and receipt["reason_code"] == "evidence_gate_refused", "outcome unchanged"
    assert handoff["schema"] == "urn:zeus:operation-evidence-handoff:1" and handoff["status"] == "pending_owner"
    assert handoff["owner"] == "lead:improvement" and handoff["next_action"] == "inspect_evidence_contract"
    assert handoff["reason_code"] == "evidence_gate_refused" and handoff["operation_id"] == "op-001"
    assert handoff["correlation_id"] == "operation:op-001" and handoff["candidate"]["revision"] == "c" * 40
    with svc.store.transaction() as tx:
        [task] = tx.scan("tasks")
    # The refusal precedes the review, so the operation itself names no task: the handoff still binds
    # the actual candidate execution and the inspection row the gate refused.
    assert receipt["task_id"] is None and handoff["task_id"] == task["id"]
    assert handoff["generation"] == 1 and handoff["attempt"] == 1
    inspection = handoff["inspection"]
    assert inspection["id"] == "insp-" + task["id"] and inspection["bound"] is True
    assert inspection["known"] is True and inspection["verdict"] == "incomplete"
    assert [item["check_id"] for item in inspection["passed"]] == ["unit"]
    assert [item["check_id"] for item in inspection["remaining"]] == ["lint"]
    assert inspection["remaining"][0]["state"] == "not_checked" and inspection["remaining"][0]["reported"] == "missing"
    assert inspection["claim_status_counts"] == {"executed": 1, "missing": 1}
    assert inspection["denominator"] == {"claims": 2, "checked": 0, "not_checked": 1}
    # No cause, command, output or path leaves; the handoff itself grants nothing.
    assert CANARY not in json.dumps(handoff) and "argv" not in json.dumps(handoff)
    assert "never a retry" in handoff["retry"] or "no follow-up" in handoff["retry"]
    assert "no retry" in handoff["authority"]


def test_the_owner_handoff_is_visible_idempotent_and_schedules_nothing():
    receipt, svc, executor, budget, _ = run(inspection="incomplete")
    read = Operation(svc).status("op-001")
    assert read["owner_handoff"] == receipt["owner_handoff"], "the same record through the status projection"
    again = Operation(svc, FakeExecutor(svc), Bus(), Workflow(svc.store, svc.org), FakeBudget(), Collector())
    replay = again.run(valid(), IDENTITY, BOUND_GOAL)
    assert replay["cached"] is True and replay["owner_handoff"] == receipt["owner_handoff"]
    assert again.executor.calls == [] and again.budget.reserved == [], "no retry, no reservation, no provider entry"
    with svc.store.transaction() as tx:
        assert [row["status"] for row in tx.scan("decisions_pending")] == ["cancelled"]
        assert [row["status"] for row in tx.scan("tasks")] == ["succeeded"], "the candidate task stays as it was"


PROGRESS_KEYS = ("verdict", "denominator", "claim_status_counts", "passed", "remaining", "truncated")


@pytest.mark.parametrize("inspection, reason", [
    ("missing", "inspection_unknown"),
    ("foreign", "inspection_bound_elsewhere"),
    ("foreign_generation", "inspection_bound_elsewhere"),
    ("foreign_attempt", "inspection_bound_elsewhere"),
    ("foreign_revision", "inspection_bound_elsewhere"),
    ("unidentified", "execution_binding_incomplete")])
def test_an_unbound_or_absent_inspection_is_unknown_and_earns_no_progress_credit(inspection, reason):
    """The reproduced finding: a real `all_checked` row of ANOTHER execution (or an execution this
    run cannot identify) must never be summarized as this run's completed checklist. The inspection
    id stays for diagnosis; verdict, denominator, counts and the passed/remaining items do not."""
    receipt, svc, _, _, _ = run(inspection=inspection)
    handoff = receipt["owner_handoff"]
    summary = handoff["inspection"]
    assert receipt["status"] == "failed" and receipt["reason_code"] == "evidence_gate_refused"
    assert summary["id"] is not None, "the id is kept so an owner can inspect the foreign row"
    assert summary["bound"] is False and summary["known"] is False and summary["reason_code"] == reason
    assert all(key not in summary for key in PROGRESS_KEYS), "unknown is absent, not a zero workload"
    # Identity, owner and next action are untouched by the refusal to credit progress.
    assert handoff["status"] == "pending_owner" and handoff["owner"] == "lead:improvement"
    assert handoff["next_action"] == "inspect_evidence_contract" and handoff["reason_code"] == "evidence_gate_refused"
    # The same real receipt through the lane projection: no passed/remaining count either.
    view = owner_handoff_view(handoff)
    assert view["inspection_id"] == summary["id"] and view["inspection_bound"] is False
    assert view["inspection_known"] is False and view["inspection_reason_code"] == reason
    assert view["passed"] is None and view["remaining"] is None
    assert view["status"] == "pending_owner" and view["next_action"] == "inspect_evidence_contract"
    assert Operation(svc).status("op-001")["owner_handoff"] == handoff, "read-only and idempotent"
    assert CANARY not in json.dumps(receipt) and CANARY not in json.dumps(view)


def test_an_inspection_bound_to_this_execution_keeps_its_checklist_and_counts():
    """The positive control of the same matrix: complete, matching binding still projects the
    useful passed/remaining checklist, both on the receipt and through the lane projection."""
    receipt, svc, _, _, _ = run(inspection="incomplete")
    summary = receipt["owner_handoff"]["inspection"]
    with svc.store.transaction() as tx:
        [task] = tx.scan("tasks")
        row = tx.get("evidence_inspections", summary["id"])
    assert row["binding"] == {"task_id": task["id"], "generation": 1, "attempt": 1, "source_revision": "c" * 40}
    assert summary["bound"] is True and summary["known"] is True and summary["reason_code"] is None
    assert [item["check_id"] for item in summary["passed"]] == ["unit"]
    assert [item["check_id"] for item in summary["remaining"]] == ["lint"]
    assert summary["denominator"] == {"claims": 2, "checked": 0, "not_checked": 1}
    view = owner_handoff_view(receipt["owner_handoff"])
    assert view["inspection_bound"] is True and view["inspection_known"] is True
    assert view["passed"] == 1 and view["remaining"] == 1 and view["inspection_reason_code"] is None


@pytest.mark.parametrize("kwargs", [{}, {"verdict": False}, {"worker": "failed"}])
def test_only_an_evidence_refusal_produces_a_handoff(kwargs):
    receipt, _, _, _, _ = run(**kwargs)
    assert receipt["reason_code"] != "evidence_gate_refused" and receipt["owner_handoff"] is None


def test_lead_rejection_stops_without_rework_and_unknown_verdict_is_unknown():
    receipt, svc, executor, budget, _ = run(verdict=False)
    assert receipt["status"] == "rejected" and receipt["reason_code"] == "lead_rejected" and receipt["exit_code"] == 1
    assert executor.calls == ["task", "decision"] and len(budget.reserved) == 2
    receipt, _, executor, budget, _ = run(verdict="maybe")
    assert receipt["status"] == "unknown" and receipt["reason_code"] == "review_verdict_unknown"


def test_ledger_exhaustion_refuses_the_reviewer_and_ends_exhausted():
    receipt, _, executor, budget, _ = run(budget=FakeBudget(refuse_after=1))
    assert receipt["status"] == "exhausted" and receipt["reason_code"] == "budget_exhausted"
    assert executor.calls == ["task"] and len(budget.reserved) == 1
    receipt, _, executor, budget, _ = run(budget=FakeBudget(refuse_after=0))
    assert receipt["status"] == "exhausted" and executor.calls == [] and budget.reserved == []


def test_first_settlement_failure_stops_before_the_reviewer_reservation():
    receipt, svc, executor, budget, _ = run(budget=FakeBudget(settle_fail=1))
    assert receipt["status"] == "failed" and receipt["reason_code"] == "settlement_failed" and receipt["exit_code"] == 1
    assert receipt["lead_accepted"] is False and receipt["decision_id"] is None
    assert executor.calls == ["task"] and len(budget.reserved) == 1 and budget.settled == [], "reviewer calls and reservation stay zero"
    assert receipt["calls"] == {"reserved": 1, "settled": 0, "slots": [
        {"id": "slot-1", "kind": "task", "agent": "worker:implementation", "provider": "claude", "outcome": "succeeded", "settled": False, "settle_error": "OSError"}]}
    assert receipt["cycle"]["cycle"]["executions"] == 1
    with svc.store.transaction() as tx:
        assert tx.scan("decisions_pending") == [] and tx.get("operations", "op-001")["status"] == "failed"
    assert CANARY not in json.dumps(receipt)


def test_second_settlement_failure_fails_after_the_accepted_review_by_contrast():
    receipt, _, executor, budget, _ = run(budget=FakeBudget(settle_fail=2))
    assert receipt["status"] == "failed" and receipt["reason_code"] == "settlement_failed" and receipt["exit_code"] == 1
    assert receipt["lead_accepted"] is True and executor.calls == ["task", "decision"] and len(budget.reserved) == 2
    assert receipt["calls"]["settled"] == 1 and budget.settled == [("slot-1", "succeeded")]
    assert [s["settle_error"] for s in receipt["calls"]["slots"]] == [None, "OSError"]


def test_collection_failure_never_becomes_success():
    receipt, _, _, _, _ = run(collector=Collector(fail=True))
    assert receipt["status"] == "failed" and receipt["reason_code"] == "collection_failed" and receipt["exit_code"] == 1


def test_finite_idle_stop_makes_no_calls():
    svc, operation, executor, budget, _ = build()
    operation.bus = None  # nothing ever delivers the assignment (fixture)
    receipt = operation.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "idle" and executor.calls == [] and budget.reserved == []


def test_status_reads_the_store_only_and_omits_manifest_text():
    receipt, svc, _, _, _ = run()
    view = Operation(svc).status("op-001")
    assert view["status"] == "accepted" and view["schema"] == "urn:zeus:operation-receipt:1"
    assert "plan" not in view and "manifest" not in view and CANARY not in json.dumps(view)
    assert view["manifest_sha256"] == receipt["manifest_sha256"]
    with pytest.raises(ContractError, match="Unknown operation"):
        Operation(svc).status("nope")


def test_postgres_claim_is_atomic_across_instances(isolated_pgstore):
    svc = Harness(isolated_pgstore, organization())
    first = Operation(svc, FakeExecutor(svc), Bus(), Workflow(svc.store, svc.org), FakeBudget(), Collector())
    assert first.claim(valid(), IDENTITY, BOUND_GOAL)["cached"] is False
    again = Harness(isolated_pgstore, organization())
    with pytest.raises(OperationRefused, match="running_residue"):
        Operation(again, FakeExecutor(again), Bus(), None, FakeBudget(), Collector()).run(valid(), IDENTITY, BOUND_GOAL)
    with pytest.raises(OperationRefused, match="configuration_mismatch"):
        Operation(again).claim(valid(), deepcopy({**IDENTITY, "repository": "elsewhere"}), BOUND_GOAL)
    with again.store.transaction() as tx:
        assert tx.get("operations", "op-001")["status"] == "running"
