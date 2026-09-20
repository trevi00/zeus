"""Rejected analysis is retained work, not a stopped execution (self-improvement-reference-001).

2026-09-21 host canary: after the explicit recovery of `d1133291-1151-4ffd-987a-6671cd0f34bd` and
the normal task `4a1e49fc-a59f-472a-ad12-694e3082728f` both succeeded, the normal task
`6975f930-7633-4f4b-b083-e002d04776b7` failed with `ContractError: Missing generator/original link`
while its receipts and observations succeeded. The partition kept generation 0 and all 32 paths.
That is a refused typed draft, not an observed PostgreSQL, transport or scheduler failure.

Every model turn in this file is INJECTED: `run_model` is replaced and `FixtureRunner` supplies the
inspection receipts. The store, the artifacts, `ResearchAudits.checkpoint`, `schedule_audits`,
`Workflow` and the observation contract are the real ones. Nothing here is evidence that a
provider, Redis, PostgreSQL or a host service ran, and no test provokes a real model to obtain a
rejection sample.
"""
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_audit_service import (  # noqa: F401  `connected` is a pytest fixture: importing registers it
    connected,
    partitions_of,
    runner,
    spool_observer,
)
from test_research_audits import (  # noqa: F401  `audit` is a pytest fixture: importing registers it
    FixtureRunner,
    activate_fixture,
    audit,
)

from codex_harness.adapters import audit_service
from codex_harness.adapters.audit_execution import AuditExecution
from codex_harness.application.scheduling import schedule_audits
from codex_harness.domain.model import ContractError, canonical, digest, envelope
from codex_harness.domain.research import PartitionCheckpoint, PathDisposition, SubsystemAnalysis

# A credential-shaped canary that only ever exists inside an injected model answer. It must stay in
# the immutable artifact and reach no result, log, step, status read or published message.
SECRET = "password=hunter2-analysis-canary-9f1c"


# ----- injected model answers ---------------------------------------------------------------
def path_body(ref, disposition="semantic", **fields):
    record = asdict(PathDisposition("", disposition, [ref], ["symbol"], "traced", [], "", []))
    return {**{k: v for k, v in record.items() if k != "path"}, **fields}


def subsystem_body(ref, paths=None, **fields):
    record = asdict(SubsystemAnalysis("", paths or ["cGF0aA=="], ["contract"], ["main"], ["impl"],
                                      ["caller"], ["config"], ["git"], ["failure"], [], [], [ref],
                                      [], [], [{"test": "upstream suite", "reason": "unavailable",
                                                "follow_up": "run in a verified runner"}]))
    return {**{k: v for k, v in record.items() if k != "name"}, **fields}


def answer_for(part, paths=None, subsystems=None, **fields):
    """Every assigned identity present exactly once: a body for analyzed work, null for the rest."""
    return {"paths": {key: (paths or {}).get(key) for key in part["paths"]},
            "subsystems": {key: (subsystems or {}).get(key) for key in part["subsystems"]},
            "open_questions": [], "cursor": "fixture-cursor", **fields}


def rejected_answer(part, ref, justification="traced"):
    """The observed 6975 shape: a generated path with no link, or a subsystem without its trace."""
    if part["paths"]:
        return answer_for(part, {part["paths"][0]: path_body(ref, "generated", links=[],
                                                             justification=justification)})
    return answer_for(part, subsystems={part["subsystems"][0]: subsystem_body(ref, contracts=[])})


def inspection_envelope(ref, **content):
    """The shape `Executor._run` RETURNS when required inspection is blocked, verbatim from its
    return boundary: no analysis content, a stored evidence reference and a host reason.

    This is an INJECTED envelope, not an observed inspection outage: no bubblewrap, runner, host or
    provider failure happened here. The reason carries the canary because the real one carries host
    text, and no projection may repeat it.
    """
    return {"accepted": False, "inspection_blocked": True, "basis_revision": "fixture-revision",
            "reason": "inspection-blocked: namespace creation denied; " + SECRET,
            "execution_ref": ref, **content}


def assigned(service, record, name, kind="paths"):
    """One claimed `audit_partition` execution of a real partition, with fixture receipts."""
    part = next(p for p in service.partition(record["id"]) if p[kind])
    message = envelope("task.assign", "lead:research", "worker:github", "audit_partition",
                       {"audit_id": record["id"], "partition_id": part["partition_id"],
                        "generation": part["generation"]}, name)
    service.workflow.submit(message)
    task = service.workflow.claim("worker:github", "fixture")
    executor = SimpleNamespace(service=SimpleNamespace(store=service.store),
                               artifacts=service.artifacts, workflow=service.workflow)
    return part, task, AuditExecution(executor, FixtureRunner(service.artifacts))


def inject(execution, monkeypatch, answer, ref=None, commands=()):
    """Replace ONLY the model turn; `ref` is added where `Executor._run` adds its own reference."""
    calls = []

    def run_model(task, objective, evidence, result_schema):
        calls.append(result_schema)
        if "commands" in result_schema["properties"]:
            return {"commands": [list(command) for command in commands]}
        return answer if ref is None else {**answer, "execution_ref": ref}

    monkeypatch.setattr(execution, "run_model", run_model)
    return calls


def store_state(service, audit_id):
    """Everything a checkpoint would have written, so a rejection can be proven to write none."""
    with service.store.transaction() as tx:
        return {bucket: tx.scan(bucket) for bucket in
                ("research_partitions", "research_paths", "research_subsystems",
                 "research_checkpoints", "research_evidence_history")}


# ----- the content boundary: valid content still checkpoints ---------------------------------
@pytest.mark.parametrize("analyzed", [False, True], ids=["all-null", "one-record"])
def test_valid_content_checkpoints_and_binds_partial_progress(
        audit, monkeypatch, analyzed):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = assigned(service, record, "valid-" + str(analyzed))
    ref = service.artifacts.put("one traced path", "fixture")["ref"]
    draft = service.artifacts.put("the accepted draft", "fixture")["ref"]
    bodies = {part["paths"][0]: path_body(ref)} if analyzed else {}
    inject(execution, monkeypatch, answer_for(part, bodies), ref=draft)
    result = execution.execute(task)

    analysis = result["analysis"]
    assert analysis["outcome"] == "analysis_checkpointed" and analysis["checkpointed"] is True
    assert analysis["execution_ref"] == draft and analysis["version"] == 1
    assert (analysis["task_id"], analysis["task_generation"], analysis["attempt"]) == (
        task["id"], task["generation"], task["attempt"])
    assert (analysis["audit_id"], analysis["partition_id"]) == (record["id"], part["partition_id"])
    assert analysis["partition_generation"] == part["generation"]
    assert analysis["checkpoint_generation"] == part["generation"] + 1
    # The marker travels with the task result; the persisted canonical checkpoint is unchanged.
    with service.store.transaction() as tx:
        stored = tx.get("research_partitions", part["partition_id"])
    assert "analysis" not in stored
    assert {k: v for k, v in result.items() if k != "analysis"} == stored
    PartitionCheckpoint(**stored).validate()
    assert stored["generation"] == part["generation"] + 1
    covered = {part["paths"][0]} if analyzed else set()
    assert set(stored["remaining_paths"]) == set(part["remaining_paths"]) - covered
    # A checkpoint is partial progress, never semantic acceptance of the whole source.
    coverage = service.coverage(record["id"])
    assert not coverage["whole_analysis_complete"] and not coverage["adoption_eligible"]


def test_an_answer_without_executor_evidence_checkpoints_and_stays_unclassified(
        audit, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """A binding needs the executor-owned reference; without one the outcome is not asserted.

    `Executor._run` always supplies that reference, so this is the injected/legacy answer shape:
    the checkpoint is still the retained work, and the service reports it as unclassified rather
    than carrying a marker that binds to no evidence.
    """
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = assigned(service, record, "valid-unbound")
    inject(execution, monkeypatch, answer_for(part))
    result = execution.execute(task)
    assert "analysis" not in result and result["generation"] == part["generation"] + 1
    assert audit_service.analysis_facts(result)["analysis_outcome"] == "analysis_unclassified"


# ----- the content boundary: a refused draft is retained --------------------------------------
@pytest.mark.parametrize("shape", ["generated_without_link", "missing_subsystem_trace",
                                   "malformed_shape", "invalid_cursor", "invalid_questions"])
def test_a_refused_draft_is_retained_without_checkpoint_coverage_or_history(
        audit, monkeypatch, shape):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    service, record, _, _, _ = audit
    activate_fixture(service)
    kind = "subsystems" if shape == "missing_subsystem_trace" else "paths"
    part, task, execution = assigned(service, record, "rejected-" + shape, kind=kind)
    draft = service.artifacts.put("the refused draft, retained verbatim", "fixture")["ref"]
    before = store_state(service, record["id"])
    answer = {
        "generated_without_link": lambda: rejected_answer(part, draft),
        "missing_subsystem_trace": lambda: rejected_answer(part, draft),
        "malformed_shape": lambda: {**answer_for(part),
                                    "paths": {"Zm9yZWlnbg==": path_body(draft)}},
        "invalid_cursor": lambda: answer_for(part, cursor=""),
        "invalid_questions": lambda: answer_for(part, open_questions=["", 7]),
    }[shape]()
    expected = {"generated_without_link": "Missing generator/original link",
                "missing_subsystem_trace": "Missing subsystem trace: contracts",
                "malformed_shape": "Assigned output identities changed",
                "invalid_cursor": "Invalid partition checkpoint",
                "invalid_questions": "Invalid analysis open questions"}[shape]
    inject(execution, monkeypatch, answer, ref=draft)

    result = execution.execute(task)
    analysis = result["analysis"]
    assert set(result) == {"analysis"}, "a rejection is not a checkpoint body"
    assert analysis["outcome"] == "analysis_rejected" and analysis["checkpointed"] is False
    assert analysis["reason_code"] == "analysis_content_rejected"
    assert analysis["error_type"] == "ContractError"
    assert analysis["error_digest"] == digest(expected), "the refusal is identified, not quoted"
    assert analysis["execution_ref"] == draft
    assert (analysis["audit_id"], analysis["partition_id"]) == (record["id"], part["partition_id"])
    assert analysis["partition_generation"] == part["generation"]
    # Not one row of the refused batch was written, and the whole assigned scope is still open.
    assert store_state(service, record["id"]) == before
    coverage = service.coverage(record["id"])
    assert coverage["reviewed_paths"] == 0 and coverage["remaining_subsystems"] == ["core"]
    assert len(coverage["remaining_paths"]) == len(record["inventory"])


def test_no_raw_text_from_a_refused_draft_reaches_the_retained_result(
        audit, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """INJECTED FAULT: a refusal whose own message carries the canary, which no domain rule emits.

    It proves the projection rule rather than the wording of any current message: only the type and
    a digest leave the boundary, whatever the refusal says.
    """
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = assigned(service, record, "rejected-secret")
    draft = service.artifacts.put("the refused draft with " + SECRET, "fixture")["ref"]
    message = "Unknown disposition in " + SECRET

    def refusing_boundary(trusted, answer):
        raise ContractError(message)

    monkeypatch.setattr(execution, "proposed_checkpoint", refusing_boundary)
    inject(execution, monkeypatch, rejected_answer(part, draft, justification=SECRET), ref=draft)
    result = execution.execute(task)
    assert result["analysis"]["error_digest"] == digest(message)
    assert SECRET not in canonical(result) and "hunter2" not in canonical(result)


# ----- everything outside that boundary stays an execution failure ----------------------------
@pytest.mark.parametrize("missing", ["absent", "unknown_artifact", "modified_artifact"])
def test_missing_or_unreadable_rejection_evidence_stays_a_failure(
        audit, monkeypatch, missing):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """Without retained content there is nothing to review later, so this is not a rejection."""
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = assigned(service, record, "evidence-" + missing)
    draft = service.artifacts.put("the refused draft, retained verbatim", "fixture")["ref"]
    before = store_state(service, record["id"])
    if missing == "unknown_artifact":
        ref = "sha256:" + "b" * 64
    elif missing == "modified_artifact":
        ref = draft
        (service.artifacts.root / (draft[7:] + ".txt")).write_text("rewritten", encoding="utf-8")
    else:
        ref = None
    inject(execution, monkeypatch, rejected_answer(part, draft), ref=ref)
    with pytest.raises((ContractError, OSError)):
        execution.execute(task)
    assert store_state(service, record["id"]) == before


@pytest.mark.parametrize("failure", ["model", "runner", "checkpoint", "trusted_partition",
                                     "stale_assignment"])
def test_failures_outside_the_content_boundary_are_never_converted(
        audit, monkeypatch, failure):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = assigned(service, record, "failure-" + failure)
    draft = service.artifacts.put("the refused draft, retained verbatim", "fixture")["ref"]
    before = store_state(service, record["id"])
    calls = inject(execution, monkeypatch, rejected_answer(part, draft), ref=draft,
                   commands=[["source-list"]] if failure == "runner" else ())
    if failure == "model":
        monkeypatch.setattr(execution, "run_model", lambda *args: (_ for _ in ()).throw(
            ContractError("injected provider refusal")))
    elif failure == "runner":
        monkeypatch.setattr(execution.audits, "runner", SimpleNamespace(
            execute_assigned=lambda *args: (_ for _ in ()).throw(
                ContractError("injected runner loss"))))
    elif failure == "checkpoint":
        monkeypatch.setattr(execution.audits, "checkpoint", lambda *args, **kwargs: (
            _ for _ in ()).throw(ContractError("Runner receipt missing, stale, blocked or unsuccessful")))
        monkeypatch.setattr(execution, "proposed_checkpoint",
                            lambda trusted, answer: (trusted, [], []))
    elif failure in {"trusted_partition", "stale_assignment"}:
        with service.store.transaction() as tx:
            row = tx.get("research_partitions", part["partition_id"])
            change = ({"remaining_paths": ["Zm9yZWlnbg=="]} if failure == "trusted_partition"
                      else {"generation": row["generation"] + 1})
            tx.put("research_partitions", part["partition_id"], {**row, **change})
        before = store_state(service, record["id"])
    with pytest.raises(ContractError):
        execution.execute(task)
    assert store_state(service, record["id"]) == before
    if failure in {"trusted_partition", "stale_assignment"}:
        assert calls == [], "the trusted assignment is checked before any model turn"


@pytest.mark.parametrize("turn", ["planning", "semantic", "semantic_carrying_content"])
def test_a_returned_inspection_refusal_is_never_a_rejected_draft(
        audit, monkeypatch, turn):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """An execution failure is not always a raised exception.

    `Executor._run` RETURNS its inspection-blocked envelope, whose missing analysis content would
    read as a refused draft at the pure boundary. The refusal is classified before that boundary,
    from either turn, and it wins even when the same envelope also carries valid-looking content.
    """
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = assigned(service, record, "returned-blocked-" + turn)
    retained = service.artifacts.put("the blocked inspection output, retained", "fixture")["ref"]
    before = store_state(service, record["id"])
    schemas = []

    def run_model(assignment, objective, evidence, result_schema):
        schemas.append(result_schema)
        if "commands" in result_schema["properties"]:
            return inspection_envelope(retained) if turn == "planning" else {"commands": []}
        content = (answer_for(part, {part["paths"][0]: path_body(retained)})
                   if turn == "semantic_carrying_content" else {})
        return inspection_envelope(retained, **content)

    monkeypatch.setattr(execution, "run_model", run_model)
    with pytest.raises(ContractError) as refusal:
        execution.execute(task)

    # A fixed safe error: the returned reason is never quoted, even into the exception.
    assert str(refusal.value) == "Execution inspection blocked"
    assert SECRET not in str(refusal.value) and "hunter2" not in str(refusal.value)
    # A refused planning turn reaches no semantic turn, and neither refusal runs a command.
    assert len(schemas) == (1 if turn == "planning" else 2)
    with service.store.transaction() as tx:
        assert [row for row in tx.scan("research_receipts")] == []
    # Nothing is checkpointed, credited or held: this is a stopped execution, not retained work.
    assert store_state(service, record["id"]) == before
    coverage = service.coverage(record["id"])
    assert coverage["reviewed_paths"] == 0 and coverage["remaining_subsystems"] == ["core"]
    assert len(coverage["remaining_paths"]) == len(record["inventory"])


# ----- the service: one rejected partition does not stop the run ------------------------------
class InjectedAnalysis(AuditExecution):
    """The real `AuditExecution` with only its model turn injected.

    `planning` replaces the planning turn's own returned value; `turns` records which turns the
    real `execute` actually reached, so a refused planning turn can be shown to reach no other.
    """

    def __init__(self, audits, answer, planning=None, turns=None):
        super().__init__(SimpleNamespace(service=SimpleNamespace(store=audits.store),
                                         artifacts=audits.artifacts, workflow=audits.workflow),
                         FixtureRunner(audits.artifacts))
        self.answer, self.planning = answer, planning
        self.turns = [] if turns is None else turns

    def run_model(self, task, objective, evidence, result_schema):
        if "commands" in result_schema["properties"]:
            self.turns.append("planning")
            return {"commands": []} if self.planning is None else self.planning
        self.turns.append("semantic")
        return self.answer(evidence["partition"])


class AnalysisExecutor:
    """Stand-in for the real `Executor` around the REAL `AuditExecution`: it claims with the given
    guard, runs the real decode and checkpoint boundary on an injected answer, and completes or
    fails the task the way `Executor.execute_one` does. No provider is entered."""

    def __init__(self, audits, answer, planning=None):
        self.audits, self.answer, self.planning = audits, answer, planning
        self.calls, self.turns = [], []

    def execute_one(self, agent, expected=None):
        self.calls.append({"agent": agent, "expected": expected})
        workflow = self.audits.workflow
        task = workflow.claim(agent, "analysis-fixture-" + uuid4().hex, expected=expected)
        if task is None:
            return None
        try:
            result = InjectedAnalysis(self.audits, self.answer, self.planning,
                                      self.turns).execute(task)
        except ContractError as exc:  # the disposition a contract refusal gets in the executor
            return workflow.fail_execution(task, exc)
        return workflow.complete(task, result)


def serial_answers(audits, rejected_partition, bind=True, justification="traced"):
    draft = audits.artifacts.put("the refused draft with " + SECRET, "fixture")["ref"]

    def answer(partition):
        if partition["partition_id"] == rejected_partition:
            body = rejected_answer(partition, draft, justification=justification)
        else:
            body = answer_for(partition)
        return {**body, "execution_ref": draft} if bind else body

    return answer, draft


def first_assignment(connected):  # noqa: F811  the imported fixture is the parameter
    """The partition the runner will bind first, read from the durable rows it will read."""
    schedule_audits(connected.service, audit_id=connected.audit_id)
    probe, _, _ = runner(connected)
    return probe._pending()[0]["partition_id"]


def test_a_rejected_partition_is_followed_by_a_valid_one_in_one_serial_run(connected):  # noqa: F811
    held_partition = first_assignment(connected)
    before = next(p for p in partitions_of(connected)
                  if p["partition_id"] == held_partition)
    answer, draft = serial_answers(connected.audits, held_partition, justification=SECRET)
    observer = spool_observer(connected)
    service_runner, bus, executor = runner(
        connected, executor=AnalysisExecutor(connected.audits, answer), max_tasks=2,
        observer=observer)
    summary = service_runner.run(once=True)

    tasks = [step for step in summary["steps"] if step["action"] == "task"]
    assert summary["completed_tasks"] == 2 and summary["stop_reason"] == "max_tasks_reached"
    assert [step["status"] for step in tasks] == ["succeeded", "succeeded"]
    assert [step["analysis_outcome"] for step in tasks] == ["analysis_rejected",
                                                            "analysis_checkpointed"]
    assert summary["analysis"] == {"analysis_rejected": 1, "analysis_checkpointed": 1}
    assert tasks[0]["partition_id"] == held_partition
    assert tasks[0]["analysis_reason"] == "analysis_content_rejected"
    assert tasks[0]["analysis_ref"] == draft and tasks[1]["analysis_reason"] is None
    # The rejected partition kept its generation and its whole scope; the valid one advanced.
    partitions = {p["partition_id"]: p for p in partitions_of(connected)}
    assert partitions[held_partition] == before
    assert partitions[tasks[1]["partition_id"]]["generation"] == 1
    with connected.store.transaction() as tx:
        assert not [row for row in tx.scan("research_paths")]
        rejected_task = tx.get("tasks", tasks[0]["task_id"])
    assert rejected_task["status"] == "succeeded"
    assert rejected_task["result"]["analysis"]["outcome"] == "analysis_rejected"

    # Logs and every projection carry fixed codes, identifiers and counts only.
    from codex_harness.adapters.contracts import validate_observation
    from codex_harness.domain.observation import REGISTRY

    events = [event for event in observer.spool.records()
              if event["event_type"] == "operations.audit_service_task"
              and event["outcome"] != "started"]
    for event in observer.spool.records():
        validate_observation(event)
        assert set(event["attributes"]) <= set(REGISTRY[event["event_type"]])
    assert [event["attributes"]["analysis_outcome"] for event in events] == [
        "analysis_rejected", "analysis_checkpointed"]
    assert [event["outcome"] for event in events] == ["succeeded", "succeeded"]
    assert events[0]["reason_code"] == "analysis_content_rejected"
    assert observer.counters["refused"] == 0
    with connected.store.transaction() as tx:
        published = [row["message"] for row in tx.scan("outbox")]
    projections = canonical([summary, [e for e in observer.spool.records()], published,
                             audit_service.status(connected.service, SimpleNamespace(
                                 audit_service_command="status", audit_id=connected.audit_id))])
    assert SECRET not in projections and "hunter2" not in projections


def test_status_counts_the_outcomes_and_lists_the_held_partition(connected):  # noqa: F811
    held_partition = first_assignment(connected)
    answer, draft = serial_answers(connected.audits, held_partition)
    service_runner, _, _ = runner(connected, executor=AnalysisExecutor(connected.audits, answer),
                                  max_tasks=2)
    summary = service_runner.run(once=True)
    args = SimpleNamespace(audit_service_command="status", audit_id=connected.audit_id)
    status = audit_service.execute(connected.service, args)

    assert status["exit_code"] == 0 and status["completed_tasks"] == 2
    assert status["assignments"]["succeeded"] == 2
    assert status["analysis"]["outcomes"] == {"analysis_rejected": 1, "analysis_checkpointed": 1}
    assert status["analysis"]["held_partitions"] == 1
    held = status["analysis"]["held"][0]
    assert held["partition_id"] == held_partition and held["execution_ref"] == draft
    assert held["reason_code"] == "analysis_content_rejected" and held["partition_generation"] == 0
    # The last settled execution is reported with BOTH facts: what it did and what it produced.
    assert status["last_task"]["status"] == "succeeded"
    assert status["last_task"]["analysis_outcome"] == "analysis_checkpointed"
    assert status["admission_blocked"] is None and summary["stop_reason"] == "max_tasks_reached"
    # Scope is untouched by the rejection: the held partition's work is all still remaining.
    assert status["partitions"]["with_remaining_work"] == 4


def test_a_repeated_tick_and_a_restart_never_rerun_the_held_generation(connected):  # noqa: F811
    held_partition = first_assignment(connected)
    answer, _ = serial_answers(connected.audits, held_partition)
    service_runner, _, _ = runner(connected, executor=AnalysisExecutor(connected.audits, answer),
                                  max_tasks=2)
    service_runner.run(once=True)
    before = next(p for p in partitions_of(connected) if p["partition_id"] == held_partition)

    def assignments_of(partition_id):
        with connected.store.transaction() as tx:
            return [t for t in tx.scan("tasks")
                    if t["message"]["what"]["details"].get("partition_id") == partition_id]

    held_tasks = assignments_of(held_partition)
    assert len(held_tasks) == 1 and held_tasks[0]["status"] == "succeeded"
    # A restart reconciles from the durable rows: the held partition is not pending and the
    # same-generation schedule key holds it, so the next admission takes other work.
    restarted, _, executor = runner(connected, executor=AnalysisExecutor(
        connected.audits, answer), max_tasks=1)
    assert restarted.reconcile()["status"] == "clear"
    assert held_partition not in {row["partition_id"] for row in restarted._pending()}
    summary = restarted.run(once=True)
    assert summary["completed_tasks"] == 1
    step = [s for s in summary["steps"] if s["action"] == "task"][0]
    assert step["partition_id"] != held_partition and step["analysis_outcome"] != "analysis_rejected"
    # Nothing about the held draft moved: same single attempt, same generation, same scope.
    assert assignments_of(held_partition) == held_tasks
    assert next(p for p in partitions_of(connected)
                if p["partition_id"] == held_partition) == before
    # A second tick of the SAME runner cannot pick it up either.
    assert held_partition not in {row["partition_id"] for row in restarted._pending()}
    # A crash-shaped restart settles the bound attempt from its OWN durable result, with both
    # facts, and still repeats nothing.
    crashed, _, third = runner(connected, executor=AnalysisExecutor(connected.audits, answer))
    crashed._write(current_task={"task_id": held_tasks[0]["id"], "partition_id": held_partition,
                                 "correlation_id": held_tasks[0]["message"]["correlation_id"],
                                 "bound_at": "now"})
    settled = crashed.reconcile()
    assert settled["status"] == "settled" and settled["analysis_outcome"] == "analysis_rejected"
    assert settled["analysis_reason"] == "analysis_content_rejected"
    assert crashed.state()["last_task"]["analysis_outcome"] == "analysis_rejected"
    assert assignments_of(held_partition) == held_tasks and third.calls == []


def test_an_execution_failure_still_stops_the_service(connected):  # noqa: F811
    """The discriminating control: the same refused content, but with no retained evidence.

    The rejection boundary cannot bind an outcome, so this is an ordinary execution failure: the
    task is not settled as succeeded, admission stops and nothing is retried.
    """
    held_partition = first_assignment(connected)
    answer, _ = serial_answers(connected.audits, held_partition, bind=False)
    service_runner, _, executor = runner(connected, executor=AnalysisExecutor(
        connected.audits, answer), max_tasks=2)
    summary = service_runner.run(once=True)

    assert summary["stop_reason"] == "task_retry" and summary["completed_tasks"] == 0
    assert summary["analysis"] == {} and len(executor.calls) == 1
    step = [s for s in summary["steps"] if s["action"] == "task"][0]
    assert step["status"] == "retry" and step["analysis_outcome"] is None
    assert next(p for p in partitions_of(connected)
                if p["partition_id"] == held_partition)["generation"] == 0
    status = audit_service.status(connected.service, SimpleNamespace(
        audit_service_command="status", audit_id=connected.audit_id))
    assert status["analysis"] == {"outcomes": {}, "held_partitions": 0, "held": []}
    assert status["admission_blocked"]["reason_code"] == "task_retry"
    # A restart admits nothing while the failed attempt stands: a failure is not retained work.
    restarted, _, second = runner(connected, executor=AnalysisExecutor(connected.audits, answer))
    assert restarted.run(once=True)["stop_reason"] == "task_retry" and second.calls == []


@pytest.mark.parametrize("turn", ["planning", "semantic"])
def test_a_returned_inspection_refusal_stops_the_service_after_one_task(connected, turn):  # noqa: F811
    """The same control at the service: an INJECTED returned envelope, not a real inspection outage.

    The task is not settled as succeeded, no coverage or checkpoint is written, admission stops
    before a second partition, and the returned host reason reaches no projection.
    """
    held_partition = first_assignment(connected)
    retained = connected.audits.artifacts.put("the blocked inspection output", "fixture")["ref"]
    blocked = inspection_envelope(retained)

    def answer(partition):
        # In the semantic case the SAME envelope also carries content that would checkpoint.
        return {**answer_for(partition), **blocked} if turn == "semantic" else answer_for(partition)

    observer = spool_observer(connected)
    service_runner, _, executor = runner(
        connected, executor=AnalysisExecutor(connected.audits, answer,
                                             planning=blocked if turn == "planning" else None),
        max_tasks=2, observer=observer)
    summary = service_runner.run(once=True)

    assert summary["stop_reason"] == "task_retry" and summary["completed_tasks"] == 0
    assert summary["analysis"] == {} and len(executor.calls) == 1, "no next partition ran"
    assert executor.turns == (["planning"] if turn == "planning" else ["planning", "semantic"])
    step = [s for s in summary["steps"] if s["action"] == "task"][0]
    assert step["status"] == "retry" and step["analysis_outcome"] is None
    # Zero checkpoint and zero coverage: every partition kept its generation and its whole scope.
    assert {p["generation"] for p in partitions_of(connected)} == {0}
    assert next(p for p in partitions_of(connected)
                if p["partition_id"] == held_partition)["generation"] == 0
    with connected.store.transaction() as tx:
        assert not [row for row in tx.scan("research_paths")]
        assert not [row for row in tx.scan("research_checkpoints")]
        published = [row["message"] for row in tx.scan("outbox")]
    status = audit_service.status(connected.service, SimpleNamespace(
        audit_service_command="status", audit_id=connected.audit_id))
    assert status["analysis"] == {"outcomes": {}, "held_partitions": 0, "held": []}
    assert status["admission_blocked"]["reason_code"] == "task_retry"
    projections = canonical([summary, [e for e in observer.spool.records()], published, status])
    assert SECRET not in projections and "hunter2" not in projections
