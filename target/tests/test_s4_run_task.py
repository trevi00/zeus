"""S4 RunTask boundaries the `execution.run_task` / `effects.context_packet` goldens do not reach (fixture proof only).

- **Both-provider guard.** Every case stubs the host App Server with a fixture and the Claude runtime with a stub
  that raises when constructed. A routing change can never reach a real provider.
- **CE-1.** The transport's hook load receipts (`hook_receipts`, `isolation.host_observed_hook_receipts`) reach
  the persisted execution record unchanged.
- **Declared S5/S8 boundaries.** An action or composition that needs an absent port refuses before any provider
  call (CE-9: never a silent fallback). The attempt fails through the ordinary disposition.
- **RF-RT (addendum A1 v2, S4 part).** With a research admission port, plan/implement are admitted only on
  `admit`/`exempt`. Any other disposition refuses before the provider (`ResearchRequired`). Without the port the
  path is M7's, and composition (S10) must wire it (PLANNED).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codex_harness.context.adapters.composition_sources import (
    GitRepository,
    ProjectSkills,
    SkillHistoryRecorder,
)
from codex_harness.context.application.compose import ContextComposer
from codex_harness.coordination.application.breaker import Breaker
from codex_harness.coordination.application.execution_records import ExecutionRecords
from codex_harness.coordination.application.invocation_admission import InvocationBreaker
from codex_harness.coordination.application.sessions import SessionCheckpoints
from codex_harness.coordination.application.task_ownership import TaskOwnership
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.execution.adapters import execution_output, output_schema
from codex_harness.execution.adapters.containers import handoff
from codex_harness.execution.adapters.transports import Transports
from codex_harness.execution.application.invocation_ledger import InvocationLedger
from codex_harness.execution.application.run_task import ResearchRequired, RunTask
from codex_harness.intake.application import tickets
from codex_harness.kernel.message import envelope
from codex_harness.observation.adapters.observation_spool import MemorySpool
from codex_harness.observation.application.observations import (
    MemoryDirectory,
    Observer,
    PostExecutionRecordFailure,
    ReconciliationRequired,
)
from codex_harness.research.application.audit_gate import inspect_approval, require_adoption
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.routing.adapters.provider_policy import host_policy
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

ORG = packaged_organization()
PLAN = {"title": "t", "objective": "Tighten one fixture", "summary": "s", "acceptance_criteria": ["passes"],
        "allowed_paths": ["src/x.py"], "evidence": "e", "risk": "low", "rollback": "revert"}


class ClaudeRefused:
    def __init__(self, *args, **kwargs):
        raise AssertionError("ClaudeCodeRuntime reached in a RunTask fixture")


def answer_for(schema):
    out = {}
    for name, spec in (schema.get("properties") or {}).items():
        kind = spec.get("type")
        out[name] = (PLAN[name] if name in PLAN else [] if kind == "array" else 0 if kind == "integer"
                     else False if kind == "boolean" else answer_for(spec) if kind == "object" else "fixture")
    return out


def build(tmp_path, *, extra=None, **ports):
    calls, extra = [], extra or {}

    class Fixture:
        enters_on_open = True

        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def run(self, prompt, cwd, schema, *a, **kw):
            calls.append(prompt)
            event = {"method": "item/completed", "params": {"item": {"id": "c1", "type": "command"}}}
            kw["on_event"](event)
            return {"events": [event], "thread_id": "th", "turn_id": "tu", "usage": {"totalTokens": 1},
                    "rotate": False, "interrupted": False, "answer": answer_for(schema), **extra}

    store, interpreter = MemoryStore(), tmp_path / "bin" / "python"
    interpreter.parent.mkdir()
    interpreter.write_text("#!/bin/sh\nexit 97\n")
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    git = SimpleNamespace(repository=tmp_path, _git=lambda *a, **kw: "harness")
    observer = Observer(store, MemorySpool("0" * 31 + "1"), component="executor", directory=MemoryDirectory())
    workflow = Workflow(store, ORG, ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                        adoption=require_adoption, park_terminal=lambda tx, message: None)
    run_task = RunTask(
        store, ORG, git, artifacts, ledger=TaskOwnership(workflow, store=store),
        admission=InvocationBreaker(Breaker(store)), invocations=InvocationLedger(store),
        sessions=SessionCheckpoints(store, ORG, workflow=workflow), records=ExecutionRecords(ORG),
        observer=observer,
        composer=ContextComposer(artifacts, artifacts.root, GitRepository(git), ProjectSkills(git, artifacts, None),
                                 SkillHistoryRecorder(store, artifacts, git), None),
        transports=Transports(host_app_server=Fixture, host_hooks=lambda: {}, claude_runtime=ClaudeRefused),
        results=SimpleNamespace(persist=execution_output.persist_result, tool_usage=execution_output.tool_usage,
                                preflight=output_schema.preflight, handoff_refs=handoff.handoff_refs,
                                retain_evidence_handoff=handoff.retain_evidence_handoff),
        execution_policy=host_policy({}), review_context=lambda cwd: {"interpreter": str(interpreter)},
        host_python=str(interpreter), ticket_binding=tickets.ticket_binding, inspect_approval=inspect_approval,
        ReconciliationRequired=ReconciliationRequired, PostExecutionRecordFailure=PostExecutionRecordFailure,
        **ports)
    return run_task, workflow, store, artifacts, calls


def submit(workflow, action="plan", details=None, sender="conductor", recipient="lead:improvement"):
    workflow.submit(envelope("task.assign", sender, recipient, action, details or {"plan": dict(PLAN)}, "corr"))


def task_row(store):
    with store.transaction() as tx:
        return next(r["body"] for r in tx.records() if r["bucket"] == "tasks")


def test_plan_runs_on_the_fixture_app_server_and_never_constructs_claude(tmp_path):
    run_task, workflow, store, _, calls = build(tmp_path)
    submit(workflow)
    out = run_task.execute_one("lead:improvement")
    assert out["status"] == "succeeded" and len(calls) == 1


def test_ce1_hook_load_receipts_reach_the_execution_record_unchanged(tmp_path):
    receipts = {"hook_receipts": [{"hook": "pre", "status": "loaded"}],
                "isolation": {"host_observed_hook_receipts": [{"hook": "pre", "digest": "sha256:" + "a" * 64}]}}
    run_task, workflow, store, artifacts, _ = build(tmp_path, extra=receipts)
    submit(workflow)
    run_task.execute_one("lead:improvement")
    record = artifacts.document(task_row(store)["result"]["execution_ref"])
    assert record["hook_receipts"] == receipts["hook_receipts"]
    assert record["isolation"]["host_observed_hook_receipts"] == receipts["isolation"]["host_observed_hook_receipts"]


@pytest.mark.parametrize("action, sender, recipient, details, wording", [
    ("dge_role", "conductor", "lead:improvement", {"plan": dict(PLAN)}, "Role execution is not wired"),
    ("research", "lead:research", "worker:github", {"source": "github", "intent": "user_request"},
     "Research provider unavailable"),
    ("implement", "lead:improvement", "worker:implementation",
     {"plan": dict(PLAN), "continuation": {"operation_id": "op"}}, "Continuation lanes are not wired"),
])
def test_an_absent_s5_s8_port_refuses_before_any_provider(tmp_path, action, sender, recipient, details, wording):
    run_task, workflow, store, _, calls = build(tmp_path)
    submit(workflow, action, details, sender, recipient)
    out = run_task.execute_one(recipient)
    assert calls == [] and out["status"] in {"retry", "failed"} and wording in (out.get("error") or "")


@pytest.mark.parametrize("kwargs, wording", [
    ({"delivery": {"inline": []}}, "Council delivery composition is not wired"),
    ({"correction_feedback": {"findings": []}}, "Correction feedback composition is not wired"),
])
def test_s8_composition_inputs_refuse_before_reservation(tmp_path, kwargs, wording):
    run_task, _, store, _, calls = build(tmp_path)
    with pytest.raises(Exception, match=wording):
        run_task._run("lead:improvement", "k1", "o", {"plan": dict(PLAN)}, str(tmp_path), {"type": "object"},
                      True, **kwargs)
    with store.transaction() as tx:
        assert tx.scan("invocation_reservations") == [] and calls == []


@pytest.mark.parametrize("disposition, admitted", [("admit", True), ("exempt", True), ("research", False),
                                                   ("blocked", False)])
def test_rf_rt_admission_gates_plan_dispatch(tmp_path, disposition, admitted):
    seen = []
    port = SimpleNamespace(admit=lambda tx, task, action: seen.append(action) or
                           {"disposition": disposition, "reason": "fixture"})
    run_task, workflow, store, _, calls = build(tmp_path, research_admission=port)
    submit(workflow)
    out = run_task.execute_one("lead:improvement")
    assert seen == ["plan"]
    if admitted:
        assert out["status"] == "succeeded" and len(calls) == 1
    else:
        assert calls == [] and out["status"] in {"retry", "failed"}
        assert "Research-first admission: " + disposition in out["error"]


def test_research_required_is_a_contract_refusal():
    exc = ResearchRequired("research", "package missing")
    assert exc.disposition == "research" and "package missing" in str(exc)
