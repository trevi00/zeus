"""INV-AUTONOMOUS-001 with labelled fixtures: the executor, budget and role outputs below are fault
injection, never Claude, Codex or independent model debate."""
import json

import pytest

from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.autonomous import AutonomousRefused, AutonomousRun
from codex_harness.application.dge import DebateSessions, DgeRefused
from codex_harness.application.promotion import PromotionRefused, promote
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.autonomous import (
    AutonomousManifestError,
    validate_autonomous_manifest,
    verified_graph,
)
from codex_harness.domain.model import envelope
from tests.test_operation import BOUND_GOAL, GOAL, IDENTITY, Bus, Collector, FakeBudget

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
SOURCE_SHA = "b" * 64


def manifest(**overrides):
    document = {"schema": "urn:zeus:autonomous:1", "id": "auto-001", "base_revision": BASE, "goal": dict(GOAL),
                "plan": {"objective": "Add the RUNBOOK note " + CANARY, "acceptance_criteria": ["focused tests pass"],
                         "allowed_paths": ["docs/zeus/operations/autonomous-dge-001/RUNBOOK.md"]},
                "budget": {"per_host": 8, "total": 16},
                "claude": {"model": "claude-fixture-model", "timeout_seconds": 300, "max_budget_usd": 2},
                "deadline": "2030-01-01T00:00:00+00:00",
                "research": {"topic": "runbook note", "questions": ["where is the runbook?"], "search_scope": ["docs"]}}
    document.update(overrides)
    return document


def valid(**overrides):
    return validate_autonomous_manifest(manifest(**overrides), packaged_policy())


RESEARCH = {"sources": [{"id": "s1", "path": "docs/contracts.md", "sha256": SOURCE_SHA, "locator": "git", "revision": BASE, "read_scope": "all"}],
            "claims": [{"id": "c1", "kind": "fact", "text": "advisory lock " + CANARY, "source_ids": ["s1"]}],
            "questions": [{"id": "q1", "question": "where is the runbook?", "blocking": True, "status": "answered", "claim_ids": ["c1"]}],
            "ssot": {"searched_paths": ["docs"], "searched_symbols": ["RUNBOOK"], "authoritative_definition": "docs/zeus/operations",
                     "callers": [], "evidence": ["tests/test_dge.py"], "unknowns": ["contention"], "decision": "improve",
                     "rationale": "extend the runbook", "transition": {"compatibility": "additive", "rollback": "revert", "retirement": "none"}},
            "needs_user": False, "user_question": None}
ROLE_OUTPUTS = {"researcher": RESEARCH, "proposer": {"summary": "bind the plan", "claim_ids": ["c1"]},
                "attacker": {"findings": [{"id": "f1", "criterion": "focused tests pass", "severity": "minor", "scenario": "style",
                                           "claim_ids": ["c1"], "trigger": None, "impact": None, "mitigation": None}]},
                "arbiter": {"verdict": "accept", "rationale": "ok", "research_question": None,
                            "dispositions": [{"finding_id": "f1", "decision": "deferred", "reason": "backlog"}]}}


class FakeExecutor:
    """Settles the guarded row the way the real executor would (fixture); counts provider entries."""

    def __init__(self, svc, outputs=None, verdict=True, role_status="succeeded", wrong_agent=False):
        self.svc, self.outputs, self.verdict = svc, {**ROLE_OUTPUTS, **(outputs or {})}, verdict
        self.role_status, self.wrong_agent, self.calls = role_status, wrong_agent, []

    def execute_one(self, agent, expected=None):
        self.calls.append(agent)
        with self.svc.store.transaction() as tx:
            task = tx.get("tasks", expected["id"])
            details = task["message"]["what"]["details"]
            task.update(attempt=1, generation=1, lease_owner="fixture")
            if task["agent"].startswith("lead:"):
                role = details["role"]
                task["status"] = self.role_status
                task["result"] = {**self.outputs[role], "execution_ref": "sha256:" + "e" * 64, "basis_revision": BASE}
                if self.wrong_agent:
                    task["agent"] = "lead:improvement"
            else:
                candidate = {"revision": "c" * 40, "base": BASE, "tree": "t" * 40, "diff_hash": "d" * 64, "path": CANARY}
                inspection_id = "insp-" + task["id"]
                tx.put("evidence_inspections", inspection_id, {"id": inspection_id, "policy_hash": "ph", "verdict": "all_checked",
                       "binding": {"task_id": task["id"], "generation": 1, "attempt": 1, "source_revision": candidate["revision"]},
                       "denominator": {"claims": 1, "checked": 1, "missing": 0}})
                task.update(status="succeeded", result={"summary": CANARY, "candidate": candidate, "execution_ref": "sha256:" + "e" * 64,
                                                        "evidence_inspection": {"inspection_id": inspection_id, "verdict": "all_checked"}})
                report = envelope("task.result", task["agent"], "lead:improvement", "implement",
                                  {"task_id": task["id"], "result": task["result"]}, task["message"]["correlation_id"])
                tx.put("outbox", report["message_id"], {"message": report, "sent": False})
            tx.put("tasks", task["id"], task)
            return task

    def decide_one(self, agent, expected=None):
        self.calls.append(agent)
        with self.svc.store.transaction() as tx:
            row = tx.get("decisions_pending", expected["id"])
            row.update(status="succeeded", result={"accepted": self.verdict, "reason": CANARY, "execution_ref": "sha256:" + "f" * 64})
            tx.put("decisions_pending", row["id"], row)
            return row


def build(**kwargs):
    svc = Harness(MemoryStore(), organization())
    executor = FakeExecutor(svc, **kwargs)
    budget = FakeBudget()
    run = AutonomousRun(svc, executor, Bus(), Workflow(svc.store, svc.org), budget, Collector(),
                        verify_sources=lambda packet: [{**s, "bytes": 1} for s in packet["sources"]], repository="r")
    return svc, run, executor, budget


def test_manifest_reuses_operation_rules_and_refuses_naive_deadline_or_missing_research():
    assert valid()["research"]["search_scope"] == ["docs"]
    for change in ({"deadline": "2030-01-01T00:00:00"}, {"research": {"topic": "x"}}, {"budget": {"per_host": True, "total": 2}},
                   {"extra": 1}, {"research": {"topic": "x", "questions": [], "search_scope": ["docs"]}}):
        with pytest.raises(AutonomousManifestError) as info:
            valid(**change)
        assert CANARY not in str(info.value)


def test_normal_cycle_promotes_in_one_transaction_and_reports_six_starts():
    svc, run, executor, budget = build()
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and receipt["exit_code"] == 0 and receipt["reason_code"] == "promoted"
    assert executor.calls == ["lead:researcher", "lead:proposer", "lead:attacker", "lead:arbiter", "worker:implementation", "lead:improvement"]
    assert receipt["starts"]["reserved"] == 6 == receipt["starts"]["settled"] == len(budget.reserved)
    assert receipt["invocations"] == {"researcher": 0, "proposer": 0, "attacker": 0, "arbiter": 0}, "counted independently of slots"
    assert receipt["design"]["state"] == "design_approved" and receipt["residuals"] == {"critical": [], "minor": [{"id": "f1", "status": "deferred"}]}
    assert receipt["promotion"]["repository"] == "verified:auto-001" and len(receipt["promotion"]["nodes"]) == 5
    assert receipt["roles"]["arbiter"]["origin"] == "executor_bound" and "answer" not in receipt["roles"]["arbiter"]
    with svc.store.transaction() as tx:
        session = tx.get("dge_sessions", "auto-001.design")
        assert session["origin"] == "executor_bound" and session["owner"] == "auto-001" and session["research_binding"]["task_id"]
        assert [e["origin"] for e in tx.scan("dge_events")] == ["executor_bound"] * 3 and all(e["binding"] for e in tx.scan("dge_events"))
        assert len(tx.scan("knowledge_nodes")) == 5 and len(tx.scan("knowledge_edges")) == 4
        assert tx.get("promotions", "auto-001")["graph_sha256"] == receipt["promotion"]["graph_sha256"]
        assert tx.get("operations", "auto-001.impl")["status"] == "accepted"
    assert CANARY not in json.dumps(receipt) and CANARY not in json.dumps(AutonomousRun(svc).status("auto-001"))
    with pytest.raises(DgeRefused, match="session_owned"):
        DebateSessions(svc.store).submit("auto-001.design", {"schema": "urn:zeus:debate-event:1", "id": "op-1", "expected_version": 3,
                                                             "packet_digest": receipt["packet_digest"], "round": 1, "role": "proposer", "payload": {}})
    replay = AutonomousRun(svc, FakeExecutor(svc), Bus(), None, FakeBudget(), Collector()).run(valid(), IDENTITY, BOUND_GOAL)
    assert replay["cached"] is True and replay["starts"] == receipt["starts"]
    with pytest.raises(AutonomousRefused, match="configuration_mismatch"):
        AutonomousRun(svc).run(valid(), {**IDENTITY, "runtime": "other"}, BOUND_GOAL)


def test_rejected_review_and_rejected_design_never_promote_or_dispatch_further():
    svc, run, executor, budget = build(verdict=False)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "rejected" and receipt["reason_code"] == "review_rejected" and receipt["promotion"] is None
    with svc.store.transaction() as tx:
        assert tx.scan("knowledge_nodes") == [] and tx.get("promotions", "auto-001") is None
    svc, run, executor, budget = build(outputs={"arbiter": {"verdict": "reject", "rationale": "no", "research_question": None,
                                                            "dispositions": [{"finding_id": "f1", "decision": "resolved", "reason": "r"}]}})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "rejected" and receipt["reason_code"] == "design_rejected" and len(executor.calls) == 4
    with svc.store.transaction() as tx:
        assert tx.get("operations", "auto-001.impl") is None


def test_unbound_stale_or_unsupported_role_output_stops_before_the_next_role():
    svc, run, executor, budget = build(wrong_agent=True)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "role_task_unbound" and executor.calls == ["lead:researcher"]
    critical = {"findings": [{"id": "f2", "criterion": "focused tests pass", "severity": "critical", "scenario": "s", "claim_ids": ["c1"],
                              "trigger": None, "impact": None, "mitigation": None}]}
    svc, run, executor, budget = build(outputs={"attacker": critical})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"] == "debate_refused:ContractError" and len(executor.calls) == 3, "unsupported critical is refused"
    svc, run, executor, budget = build(outputs={"researcher": {**RESEARCH, "needs_user": True, "user_question": "which doc?"}})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "needs_user" and executor.calls == ["lead:researcher"]
    svc, run, executor, budget = build()
    with pytest.raises(AutonomousRefused, match="deadline_expired"):
        run.run(valid(deadline="2000-01-01T00:00:00+00:00"), IDENTITY, BOUND_GOAL)
    assert executor.calls == [] and budget.reserved == []


def test_running_residue_is_refused_without_takeover_and_budget_refusal_ends_exhausted():
    svc, run, executor, budget = build()
    run.claim(valid(), IDENTITY, BOUND_GOAL)
    with pytest.raises(AutonomousRefused, match="running_residue"):
        AutonomousRun(svc, FakeExecutor(svc), Bus(), Workflow(svc.store, svc.org), FakeBudget(), Collector()).run(valid(), IDENTITY, BOUND_GOAL)
    svc, run, executor, budget = build()
    run.budget = FakeBudget(refuse_after=2)
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "exhausted" and receipt["reason_code"] == "budget_exhausted" and len(executor.calls) == 2


def test_promotion_is_idempotent_refuses_conflict_and_rolls_back_with_the_receipt():
    store = MemoryStore()
    refs = {"base_revision": BASE, "goal": {"path": "g.md", "sha256": SOURCE_SHA}, "packet_digest": "p" * 64,
            "research_execution_ref": "sha256:" + "e" * 64, "research_task_id": "t1", "session_id": "s", "decision_event_id": "arb",
            "role_bindings": {}, "candidate": {"revision": "c" * 40, "base": BASE, "tree": "t" * 40, "diff_hash": "d" * 64},
            "implementation_task_id": "t2", "implementation_execution_ref": "sha256:" + "e" * 64, "decision_id": "d1",
            "review_execution_ref": "sha256:" + "f" * 64, "inspection_id": "i1", "operation_id": "op", "verification_scope": {}}
    graph = verified_graph("run-1", refs)
    with store.transaction() as tx:
        first = promote(tx, "run-1", graph, {"decision_id": "d1"})
        assert promote(tx, "run-1", graph, {"decision_id": "d1"})["cached"] is True
        with pytest.raises(PromotionRefused, match="promotion_conflict"):
            promote(tx, "run-1", verified_graph("run-1", {**refs, "inspection_id": "i2"}), {})
        with pytest.raises(PromotionRefused, match="namespace_mismatch"):
            promote(tx, "run-2", graph, {})
    assert first["cached"] is False and first["repository"] == "verified:run-1"
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            promote(tx, "run-3", verified_graph("run-3", refs), {})
            raise RuntimeError("commit failure (fixture)")
    with store.transaction() as tx:
        assert tx.get("promotions", "run-3") is None and len(tx.scan("knowledge_nodes")) == 5, "rollback wrote neither"
