"""Candidate claims versus execution integrity at the WHOLE checkpoint boundary.

self-improvement-reference-001, 2026-09-21: the explicitly authorized recovery of
`6975f930-7633-4f4b-b083-e002d04776b7` stopped again on attempt 2 with
`ContractError: Unknown generator/original path`, while the actual response
`sha256:777c874c1d99b3c44f814cfe526cdda87f4361dbfdb632384cad5d8dacbf117f` carried three
human-readable links whose Base64 encodings each name an existing inventory path. The files were
present: the draft's representation was wrong. A model draft can pass type validation and still
fail relationship and evidence-claim validation, so treating every checkpoint refusal as
infrastructure failure repeats the family after each schema correction.

This file is the acceptance matrix for the revised boundary. `ResearchAudits.checkpoint` raises the
typed `AuditDraftRejected` for the candidate's OWN claims, and `AuditExecution` catches ONLY that
type, outside the store transaction, so every staged row has already rolled back. Execution
integrity - ownership, leases, trusted scope, stored anchors, artifact integrity, the database and
its commit - stays an ordinary failure that stops the service, and an ordinary `ContractError`
carrying the SAME text as a candidate refusal is still not converted.

Everything model-authored here is INJECTED: `run_model` is replaced and `FixtureRunner` supplies
receipts. The store, artifacts, `ResearchAudits`, `Workflow`, `schedule_audits` and the observation
contract are the real ones. Nothing here is evidence that a provider, Redis, PostgreSQL or a host
service ran, and no test provoked a real model to obtain a rejection sample. The PostgreSQL cases
below skip without `HARNESS_INTEGRATION=1`; the owner and CI run them without skips.
"""
import base64
from dataclasses import asdict, replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_audit_analysis_outcomes import (
    AnalysisExecutor,
    answer_for,
    assigned,
    first_assignment,
    inject,
    path_body,
    serial_answers,
    subsystem_body,
)
from test_audit_service import (  # noqa: F401  `connected` is a pytest fixture: importing registers it
    connected,
    partitions_of,
    runner,
)
from test_research_audits import (  # noqa: F401  `audit` is a pytest fixture: importing registers it
    FixtureRunner,
    activate_fixture,
    audit,
)

from codex_harness.adapters import audit_service
from codex_harness.domain.model import ContractError, canonical, digest, envelope
from codex_harness.domain.research import (
    AuditDraftRejected,
    InventoryEntry,
    PartitionCheckpoint,
    PathDisposition,
    SubsystemAnalysis,
)

# A reference of the right shape whose body was never stored: the "invented artifact" claim.
INVENTED = "sha256:" + "c" * 64
# The observed defect's own shape: a display name where an inventory identity is contracted.
DISPLAY_NAME = "docs/zeus/operations/self-improvement-reference-001/SPEC.md"

# Everything one checkpoint could ever commit, including the outbox and the knowledge graph.
WRITTEN_BUCKETS = ("research_partitions", "research_paths", "research_subsystems",
                   "research_checkpoints", "research_evidence_history", "research_receipts",
                   "outbox", "knowledge_nodes", "knowledge_edges")


def committed(store):
    with store.transaction() as tx:
        return {bucket: tx.scan(bucket) for bucket in WRITTEN_BUCKETS}


def claim_partition(service, record, name, kind="paths"):
    """One real assigned `audit_partition` task over a real partition of this audit."""
    part = next(p for p in service.partition(record["id"]) if p[kind])
    message = envelope("task.assign", "lead:research", "worker:github", "audit_partition",
                       {"audit_id": record["id"], "partition_id": part["partition_id"],
                        "generation": part["generation"]}, name)
    service.workflow.submit(message)
    return part, service.workflow.claim("worker:github", "fixture")


def binary_path(record):
    """The fixture's actual binary blob (`\\xff\\x00\\xfe`), by its inventory identity."""
    return next(e["path"] for e in record["inventory"]
                if e["mode"] == "100644" and e["size"] == 3)


# ----- every candidate claim in the matrix is a typed rejection, and writes nothing -------------
def relationship_cases(service, record, part, task, ref):
    """The candidate-claim matrix as (id, arguments to `checkpoint`, expected message).

    Each case is a claim the DRAFT makes: a relationship between records, a reference it names, or
    its own account of the remaining work. None of them says anything about the store or the host.
    """
    trusted = PartitionCheckpoint(**part)
    semantic = PathDisposition(part["paths"][0], "semantic", [ref], ["symbol"], "traced", [], "", [])
    cases = [
        ("duplicate_records", trusted, [semantic, replace(semantic, disposition="unreviewed",
                                                          evidence_refs=[], justification="")],
         [], "Duplicate coverage"),
        ("foreign_record", trusted, [replace(semantic, path="Zm9yZWlnbg==")], [],
         "Cross-partition evidence"),
        ("display_name_link", trusted, [replace(semantic, disposition="generated",
                                                links=[DISPLAY_NAME])], [],
         "Unknown generator/original path"),
        ("unknown_link_identity", trusted, [replace(semantic, disposition="duplicate",
                                                    links=[base64.b64encode(b"absent").decode()])],
         [], "Unknown generator/original path"),
        ("invented_evidence", trusted, [replace(semantic, evidence_refs=[INVENTED])], [],
         "Claimed evidence artifact is absent"),
        ("invented_checkpoint_evidence", replace(trusted, evidence_refs=[INVENTED]), [], [],
         "Claimed evidence artifact is absent"),
        ("binary_without_receipt", trusted,
         [replace(semantic, path=binary_path(record))], [], "Binary coverage requires verified runner inspection"),
        ("unsupported_binary_claim", trusted,
         [replace(semantic, path=binary_path(record), disposition="binary", method="eyeballed",
                  receipt_ids=["invented-receipt"])], [],
         "Runner receipt missing, stale, blocked or unsuccessful"),
        ("missing_receipt_claim", trusted, [replace(semantic, receipt_ids=["invented-receipt"])],
         [], "Runner receipt missing, stale, blocked or unsuccessful"),
    ]
    return cases


@pytest.mark.parametrize("case", ["duplicate_records", "foreign_record", "display_name_link",
                                  "unknown_link_identity", "invented_evidence",
                                  "invented_checkpoint_evidence", "binary_without_receipt",
                                  "unsupported_binary_claim", "missing_receipt_claim"])
def test_every_candidate_relationship_claim_is_a_typed_rejection_that_commits_nothing(
        audit, case):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task = claim_partition(service, record, "claim-" + case)
    ref = service.artifacts.put("one traced path", "fixture")["ref"]
    cases = relationship_cases(service, record, part, task, ref)
    _, checkpoint, dispositions, analyses, expected = next(c for c in cases if c[0] == case)
    before = committed(service.store)

    with pytest.raises(AuditDraftRejected, match=expected):
        service.checkpoint(task, checkpoint, dispositions, analyses)

    # A typed rejection, and not one row of the refused batch survived it.
    assert committed(service.store) == before
    coverage = service.coverage(record["id"])
    assert coverage["reviewed_paths"] == 0 and coverage["remaining_subsystems"] == ["core"]
    assert len(coverage["remaining_paths"]) == len(record["inventory"])


@pytest.mark.parametrize("case", ["unknown_subsystem_path", "unproven_test_command"])
def test_subsystem_trace_claims_are_typed_rejections_that_commit_nothing(
        audit, case):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    import json

    service, record, _, _, _ = audit
    activate_fixture(service)
    service.runner = FixtureRunner(service.artifacts)
    part, task = claim_partition(service, record, "trace-" + case, kind="subsystems")
    ref = service.artifacts.put("subsystem evidence", "fixture")["ref"]
    analysis = SubsystemAnalysis("core", [record["inventory"][0]["path"]], ["contract"], ["main"],
                                 ["impl"], ["caller"], ["config"], ["git"], ["failure"], [], [],
                                 [ref], [], [],
                                 [{"test": "upstream suite", "reason": "isolation unavailable",
                                   "follow_up": "run in a verified runner"}])
    if case == "unknown_subsystem_path":
        analysis = replace(analysis, paths=[base64.b64encode(b"never/inventoried").decode()])
        expected = "Unknown subsystem path"
    else:
        # A real runner receipt for an INERT source listing cannot attest a test command.
        receipt = service.execute(task, record["id"], ["source-list"])
        analysis = replace(analysis, tests=[json.dumps(["pytest", "-q"])],
                           receipt_ids=[receipt["id"]], tests_not_run=[])
        expected = "Claimed test lacks matching successful execution command"
    before = committed(service.store)

    with pytest.raises(AuditDraftRejected, match=expected):
        service.checkpoint(task, replace(PartitionCheckpoint(**part), remaining_subsystems=[]),
                           [], [analysis])

    assert committed(service.store) == before
    assert service.coverage(record["id"])["remaining_subsystems"] == ["core"]


def test_a_submodule_classification_claim_is_a_typed_rejection(
        audit):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """The fixture repository has no gitlink, so the submodule entry is a LABELLED fixture record.

    It is written as a second audit's trusted inventory (the same verified source identity), which
    is what `checkpoint` reads; no real submodule was acquired or verified here.
    """
    service, record, source, _, _ = audit
    activate_fixture(service)
    gitlink = base64.b64encode(b"vendor/nested").decode()
    entry = InventoryEntry(gitlink, "160000", "b" * 40, None, None)
    entry.validate()
    audit_id = digest({"fixture": "submodule-claim"})
    checkpoint = PartitionCheckpoint(audit_id, digest({"fixture": "submodule-partition"}), 0,
                                     [gitlink], [], [], [gitlink], [], [], "pending")
    checkpoint.validate()
    with service.store.transaction() as tx:
        tx.put("research_audits", audit_id, {"id": audit_id, "version": 1,
                                             "source": asdict(source), "inventory": [asdict(entry)],
                                             "subsystems": [],
                                             "status": "source_verified_not_reviewed"})
        tx.put("research_partitions", checkpoint.partition_id, asdict(checkpoint))
    message = envelope("task.assign", "lead:research", "worker:github", "audit_partition",
                       {"audit_id": audit_id, "partition_id": checkpoint.partition_id,
                        "generation": 0}, "submodule-claim")
    service.workflow.submit(message)
    task = service.workflow.claim("worker:github", "fixture")
    ref = service.artifacts.put("claimed submodule reading", "fixture")["ref"]
    claim = PathDisposition(gitlink, "semantic", [ref], ["symbol"], "traced", [], "", [])
    before = committed(service.store)

    with pytest.raises(AuditDraftRejected, match="Submodule requires its own verified audit"):
        service.checkpoint(task, replace(checkpoint, remaining_paths=[]), [claim], [])

    assert committed(service.store) == before


def test_a_late_reconciliation_rejection_rolls_back_rows_it_already_staged(
        audit):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """The discriminating rollback case: coverage and history rows ARE staged, then refused.

    `checkpoint` writes `research_subsystems` and `research_evidence_history` before it reconciles
    the candidate's own remaining-work claim. The typed rejection leaves the transaction, so none
    of those staged rows is committed - on MemoryStore here, on PostgreSQL below.
    """
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task = claim_partition(service, record, "late-reconcile", kind="subsystems")
    ref = service.artifacts.put("subsystem evidence", "fixture")["ref"]
    # Justified unexecuted tests: persistable, incomplete evidence that earns no subsystem coverage.
    analysis = SubsystemAnalysis("core", [record["inventory"][0]["path"]], ["contract"], ["main"],
                                 ["impl"], ["caller"], ["config"], ["git"], ["failure"], [], [],
                                 [ref], [], [],
                                 [{"test": "upstream suite", "reason": "isolation unavailable",
                                   "follow_up": "run in a verified runner"}])
    before = committed(service.store)

    # The claim "nothing is left" contradicts the coverage this very batch establishes.
    with pytest.raises(AuditDraftRejected, match="Remaining work does not reconcile"):
        service.checkpoint(task, replace(PartitionCheckpoint(**part), remaining_subsystems=[]),
                           [], [analysis])

    after = committed(service.store)
    assert after == before
    assert after["research_subsystems"] == [] and after["research_evidence_history"] == []
    assert after["research_checkpoints"] == []
    stored = next(p for p in after["research_partitions"] if p["partition_id"] == part["partition_id"])
    assert stored == part, "the partition kept its generation and its whole scope"
    # The honest version of the same batch still checkpoints: rejection is not relaxation.
    saved = service.checkpoint(task, PartitionCheckpoint(**part), [], [analysis])
    assert saved["generation"] == part["generation"] + 1
    assert saved["remaining_subsystems"] == part["remaining_subsystems"]


def test_the_owned_task_can_still_be_completed_after_a_rejection_rolled_back(
        audit):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """A rejection is retained work: the lease survives and completion is its own transaction."""
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task = claim_partition(service, record, "retained-completion", kind="subsystems")
    ref = service.artifacts.put("subsystem evidence", "fixture")["ref"]
    analysis = SubsystemAnalysis("core", [record["inventory"][0]["path"]], ["contract"], ["main"],
                                 ["impl"], ["caller"], ["config"], ["git"], ["failure"], [], [],
                                 [ref], [], [],
                                 [{"test": "upstream suite", "reason": "isolation unavailable",
                                   "follow_up": "run in a verified runner"}])
    with pytest.raises(AuditDraftRejected):
        service.checkpoint(task, replace(PartitionCheckpoint(**part), remaining_subsystems=[]),
                           [], [analysis])

    completed = service.workflow.complete(task, {"analysis": {"outcome": "analysis_rejected"}})
    assert completed["status"] == "succeeded"
    with service.store.transaction() as tx:
        assert tx.scan("research_subsystems") == []
        assert tx.get("research_partitions", part["partition_id"]) == part


# ----- the same claims through the real execution boundary become retained work -----------------
@pytest.mark.parametrize("claim", ["display_name_link", "unknown_subsystem_path",
                                   "invented_evidence", "invented_receipt", "binary_claim"])
def test_a_refused_candidate_claim_is_retained_analysis_rejected_not_a_failure(
        audit, monkeypatch, claim):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    service, record, _, _, _ = audit
    activate_fixture(service)
    kind = "subsystems" if claim == "unknown_subsystem_path" else "paths"
    part, task, execution = assigned(service, record, "retained-" + claim, kind=kind)
    ref = service.artifacts.put("one traced path", "fixture")["ref"]
    draft = service.artifacts.put("the refused candidate draft, retained verbatim", "fixture")["ref"]
    before = committed(service.store)
    if claim == "unknown_subsystem_path":
        answer = answer_for(part, subsystems={part["subsystems"][0]: subsystem_body(
            ref, paths=[base64.b64encode(b"never/inventoried").decode()])})
        expected = "Unknown subsystem path"
    elif claim == "display_name_link":
        answer = answer_for(part, {part["paths"][0]: path_body(ref, "generated",
                                                               links=[DISPLAY_NAME])})
        expected = "Unknown generator/original path"
    elif claim == "invented_evidence":
        answer = answer_for(part, {part["paths"][0]: path_body(INVENTED)})
        expected = "Claimed evidence artifact is absent"
    elif claim == "invented_receipt":
        answer = answer_for(part, {part["paths"][0]: path_body(ref,
                                                               receipt_ids=["invented-receipt"])})
        expected = "Runner receipt missing, stale, blocked or unsuccessful"
    else:
        answer = answer_for(part, {binary_path(record): path_body(ref)})
        expected = "Binary coverage requires verified runner inspection"
    inject(execution, monkeypatch, answer, ref=draft)

    result = execution.execute(task)

    analysis = result["analysis"]
    assert set(result) == {"analysis"}, "a rejection is not a checkpoint body"
    assert analysis["outcome"] == "analysis_rejected" and analysis["checkpointed"] is False
    assert analysis["reason_code"] == "analysis_content_rejected"
    # The claim family is named by TYPE, and the refusal itself is identified by digest only.
    assert analysis["error_type"] == "AuditDraftRejected"
    assert analysis["error_digest"] == digest(expected), "the refusal is identified, not quoted"
    assert analysis["execution_ref"] == draft
    assert (analysis["audit_id"], analysis["partition_id"]) == (record["id"], part["partition_id"])
    assert analysis["partition_generation"] == part["generation"]
    assert committed(service.store) == before
    coverage = service.coverage(record["id"])
    assert coverage["reviewed_paths"] == 0 and coverage["remaining_subsystems"] == ["core"]
    assert len(coverage["remaining_paths"]) == len(record["inventory"])


def test_valid_and_justified_partial_work_still_checkpoints_through_the_same_boundary(
        audit, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """The control for every rejection above: unchanged acceptance, unchanged evidence rules."""
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = assigned(service, record, "accepted-partial")
    ref = service.artifacts.put("one traced path", "fixture")["ref"]
    draft = service.artifacts.put("the accepted draft", "fixture")["ref"]
    analyzed = part["paths"][0]
    inject(execution, monkeypatch, answer_for(part, {analyzed: path_body(ref)}), ref=draft)
    result = execution.execute(task)

    assert result["analysis"]["outcome"] == "analysis_checkpointed"
    assert result["generation"] == part["generation"] + 1
    assert result["remaining_paths"] == sorted(set(part["paths"]) - {analyzed})
    with service.store.transaction() as tx:
        assert [r["record"]["path"] for r in tx.scan("research_paths")] == [analyzed]


# ----- execution integrity is never converted, whatever the message says ------------------------
@pytest.mark.parametrize("failure", ["anchored_body_missing", "unanchored_body_modified",
                                     "unanchored_metadata_missing", "injected_permission_error"])
def test_execution_integrity_failures_are_never_retained_as_a_rejected_draft(
        audit, monkeypatch, failure):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """Only an ABSENT unanchored body is the candidate's fault; the artifact store's health is not.

    `anchored_body_missing` removes a VERIFIED inventory artifact the answer names, so the same
    `FileNotFoundError` that would be a draft rejection for an invented reference stays a hard
    failure for an authoritative one. `injected_permission_error` is an injected fault: no real
    permission failure happened in this container.
    """
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = assigned(service, record, "integrity-" + failure)
    ref = service.artifacts.put("one traced path", "fixture")["ref"]
    draft = service.artifacts.put("the draft, retained verbatim", "fixture")["ref"]
    answer = answer_for(part, {part["paths"][0]: path_body(ref)})
    expected = ContractError
    if failure == "anchored_body_missing":
        # A VERIFIED inventory artifact, named by the answer and then removed from the store.
        anchored = next(e["artifact_ref"] for e in record["inventory"] if e["artifact_ref"])
        answer = answer_for(part, {part["paths"][0]: path_body(anchored)})
        (service.artifacts.root / (anchored[7:] + ".txt")).unlink()
        expected = FileNotFoundError
    elif failure == "unanchored_body_modified":
        (service.artifacts.root / (ref[7:] + ".txt")).write_text("rewritten", encoding="utf-8")
    elif failure == "unanchored_metadata_missing":
        (service.artifacts.root / (ref[7:] + ".json")).unlink()
    elif failure == "injected_permission_error":
        inspect = service.artifacts.inspect

        def refusing_inspect(reference):
            if reference == ref:
                raise PermissionError("injected artifact permission failure")
            return inspect(reference)

        monkeypatch.setattr(service.artifacts, "inspect", refusing_inspect)
        expected = PermissionError
    before = committed(service.store)
    inject(execution, monkeypatch, answer, ref=draft)

    with pytest.raises(expected) as failed:
        execution.execute(task)

    assert not isinstance(failed.value, AuditDraftRejected)
    assert committed(service.store) == before
    assert service.coverage(record["id"])["reviewed_paths"] == 0


def test_an_ordinary_contract_error_with_a_candidate_message_is_not_an_analysis_outcome(
        audit, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """The same text, the other type: the execution fails and nothing is retained.

    The paired positive is `test_a_refused_candidate_claim_is_retained_analysis_rejected_not_a_failure`,
    which gets `analysis_rejected` for exactly this message from `AuditDraftRejected`.
    """
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = assigned(service, record, "same-text-control")
    ref = service.artifacts.put("one traced path", "fixture")["ref"]
    draft = service.artifacts.put("the draft, retained verbatim", "fixture")["ref"]
    message = "Unknown generator/original path"
    monkeypatch.setattr(execution.audits, "checkpoint", lambda *args, **kwargs: (
        _ for _ in ()).throw(ContractError(message)))
    inject(execution, monkeypatch, answer_for(part, {part["paths"][0]: path_body(ref)}), ref=draft)
    before = committed(service.store)

    with pytest.raises(ContractError) as failure:
        execution.execute(task)

    assert type(failure.value) is ContractError and str(failure.value) == message
    assert not isinstance(failure.value, AuditDraftRejected)
    assert committed(service.store) == before


@pytest.mark.parametrize("trusted", ["stale_generation", "changed_scope", "foreign_assignment"])
def test_trusted_anchor_failures_stay_ordinary_execution_failures(
        audit, trusted):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task = claim_partition(service, record, "anchor-" + trusted)
    ref = service.artifacts.put("one traced path", "fixture")["ref"]
    disposition = PathDisposition(part["paths"][0], "semantic", [ref], ["symbol"], "traced",
                                  [], "", [])
    checkpoint = PartitionCheckpoint(**part)
    if trusted == "stale_generation":
        checkpoint = replace(checkpoint, generation=part["generation"] + 1)
        expected = "Stale partition writer"
    elif trusted == "changed_scope":
        checkpoint = replace(checkpoint, paths=part["paths"][:1],
                             remaining_paths=part["remaining_paths"][:1])
        expected = "Partition scope changed"
    else:
        checkpoint = replace(checkpoint, partition_id=digest({"foreign": "partition"}))
        expected = "Execution is not assigned this partition"
    before = committed(service.store)

    with pytest.raises(ContractError) as failure:
        service.checkpoint(task, checkpoint, [disposition], [])

    assert not isinstance(failure.value, AuditDraftRejected), "integrity is not a candidate claim"
    assert expected in str(failure.value)
    assert committed(service.store) == before


# ----- the service: a refused candidate is settled work, a failure still stops ------------------
def candidate_answers(audits, rejected_partition):
    """A draft that passes the typed decoder and fails only on a claim it makes itself.

    A path partition gets the actual observed defect: a display name where the contract is an
    inventory identity. A subsystem partition claims a trace path that was never inventoried.
    """
    draft = audits.artifacts.put("the refused candidate draft", "fixture")["ref"]
    evidence = audits.artifacts.put("one traced path", "fixture")["ref"]
    unknown = base64.b64encode(b"never/inventoried").decode()

    def answer(partition):
        if partition["partition_id"] != rejected_partition:
            body = answer_for(partition)
        elif partition["paths"]:
            body = answer_for(partition, {partition["paths"][0]: path_body(
                evidence, "generated", links=[DISPLAY_NAME])})
        else:
            body = answer_for(partition, subsystems={partition["subsystems"][0]: subsystem_body(
                evidence, paths=[unknown])})
        return {**body, "execution_ref": draft}

    return answer, draft


def test_a_refused_candidate_partition_is_followed_by_a_valid_one_and_is_never_retried(
        connected):  # noqa: F811  the imported fixture is the parameter
    held = first_assignment(connected)
    before = next(p for p in partitions_of(connected) if p["partition_id"] == held)
    answer, draft = candidate_answers(connected.audits, held)
    service_runner, _, executor = runner(
        connected, executor=AnalysisExecutor(connected.audits, answer), max_tasks=2)
    summary = service_runner.run(once=True)

    tasks = [step for step in summary["steps"] if step["action"] == "task"]
    assert summary["completed_tasks"] == 2 and summary["stop_reason"] == "max_tasks_reached"
    assert [step["status"] for step in tasks] == ["succeeded", "succeeded"]
    assert [step["analysis_outcome"] for step in tasks] == ["analysis_rejected",
                                                            "analysis_checkpointed"]
    assert tasks[0]["partition_id"] == held and tasks[0]["analysis_ref"] == draft
    assert tasks[0]["analysis_reason"] == "analysis_content_rejected"
    partitions = {p["partition_id"]: p for p in partitions_of(connected)}
    assert partitions[held] == before, "the refused partition kept generation and scope"
    assert partitions[tasks[1]["partition_id"]]["generation"] == 1
    with connected.store.transaction() as tx:
        assert [row for row in tx.scan("research_paths")] == []
        rejected_task = tx.get("tasks", tasks[0]["task_id"])
        published = [row["message"] for row in tx.scan("outbox")]
    assert rejected_task["result"]["analysis"]["error_type"] == "AuditDraftRejected"
    # The refused claim itself is model-authored text: it stays in the immutable artifact and
    # reaches no step, summary, published message or status read.
    status = audit_service.status(connected.service, SimpleNamespace(
        audit_service_command="status", audit_id=connected.audit_id))
    assert status["analysis"]["outcomes"] == {"analysis_rejected": 1, "analysis_checkpointed": 1}
    assert DISPLAY_NAME not in canonical([summary, published, status])

    # A restart reconciles from the durable rows and never reruns the held generation.
    restarted, _, second = runner(connected, executor=AnalysisExecutor(connected.audits, answer),
                                  max_tasks=1)
    assert restarted.reconcile()["status"] == "clear"
    assert held not in {row["partition_id"] for row in restarted._pending()}
    restarted.run(once=True)
    assert next(p for p in partitions_of(connected) if p["partition_id"] == held) == before
    assert held not in {row["partition_id"] for row in restarted._pending()}


def test_an_unbindable_refused_candidate_still_stops_the_service(
        connected):  # noqa: F811  the imported fixture is the parameter
    """The control: the same refusal with no retained evidence is an execution failure."""
    held = first_assignment(connected)
    answer, _ = serial_answers(connected.audits, held, bind=False)
    service_runner, _, executor = runner(
        connected, executor=AnalysisExecutor(connected.audits, answer), max_tasks=2)
    summary = service_runner.run(once=True)

    assert summary["stop_reason"] == "task_retry" and summary["completed_tasks"] == 0
    assert summary["analysis"] == {} and len(executor.calls) == 1
    assert {p["generation"] for p in partitions_of(connected)} == {0}


# ----- the same rollback on MemoryStore and on a real PostgreSQL transaction --------------------
BACKENDS = ["memory", pytest.param("postgres", marks=pytest.mark.integration)]


@pytest.fixture
def rollback_store(request):
    """One store surface, two real implementations.

    `memory` runs everywhere and proves `MemoryStore` publishes its draft only after a successful
    yield. `postgres` is the real transaction proof and SKIPS without `HARNESS_INTEGRATION=1`; the
    owner and CI run it without skips, in a per-test schema, so no production row is touched.
    """
    from codex_harness.adapters.store import MemoryStore
    if request.param == "memory":
        return MemoryStore()
    return request.getfixturevalue("isolated_pgstore")


def transaction_class(store):
    """The transaction type whose `put` the injected store fault replaces, for this backend."""
    from codex_harness.adapters.store import MemoryTransaction, PostgresTransaction
    return MemoryTransaction if type(store).__name__ == "MemoryStore" else PostgresTransaction


def audit_on(audit, store):  # noqa: F811  the imported fixture is the parameter
    """The same verified source, inventory and artifacts, imported into this store."""
    from codex_harness.application.research import ResearchAudits
    from codex_harness.application.workflow import Workflow
    from codex_harness.bootstrap import organization

    service, _, source, entries, _ = audit
    workflow = Workflow(store, organization())
    audits = ResearchAudits(store, service.verifier, service.artifacts, workflow,
                            FixtureRunner(service.artifacts))
    record = audits.import_audit(source, entries, ["core"])
    audits.partition(record["id"])
    return audits, record


def subsystem_task(audits, record, name):
    part = next(p for p in audits.partition(record["id"]) if p["subsystems"])
    message = envelope("task.assign", "lead:research", "worker:github", "audit_partition",
                       {"audit_id": record["id"], "partition_id": part["partition_id"],
                        "generation": part["generation"]}, name + "-" + uuid4().hex)
    audits.workflow.submit(message)
    ref = audits.artifacts.put("subsystem evidence", "fixture")["ref"]
    analysis = SubsystemAnalysis("core", [record["inventory"][0]["path"]], ["contract"], ["main"],
                                 ["impl"], ["caller"], ["config"], ["git"], ["failure"], [], [],
                                 [ref], [], [],
                                 [{"test": "upstream suite", "reason": "isolation unavailable",
                                   "follow_up": "run in a verified runner"}])
    return part, audits.workflow.claim("worker:github", "rollback-fixture"), analysis


@pytest.mark.parametrize("rollback_store", BACKENDS, indirect=True)
def test_a_late_typed_rejection_rolls_back_then_the_owned_task_still_completes(
        audit, rollback_store):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """The staged coverage and history of a refused batch reach no committed row.

    psycopg's connection context rolls back on an escaping exception
    (https://www.psycopg.org/psycopg3/docs/basic/transactions.html, read 2026-09-21, page labelled
    3.3.7.dev1) and `MemoryStore` publishes its draft only after a successful yield. That
    documentation explains the placement; these two runs are the proof for THIS code path.
    """
    audits, record = audit_on(audit, rollback_store)
    part, task, analysis = subsystem_task(audits, record, "late-reject")
    before = committed(rollback_store)

    with pytest.raises(AuditDraftRejected, match="Remaining work does not reconcile"):
        audits.checkpoint(task, replace(PartitionCheckpoint(**part), remaining_subsystems=[]),
                          [], [analysis])

    after = committed(rollback_store)
    assert after["research_subsystems"] == [] and after["research_evidence_history"] == []
    assert after["research_checkpoints"] == [] and after["outbox"] == before["outbox"]
    assert after["research_partitions"] == before["research_partitions"]
    # The rejection did not consume the lease: completion is its own separate transaction.
    completed = audits.workflow.complete(task, {"analysis": {"outcome": "analysis_rejected"}})
    assert completed["status"] == "succeeded"
    with rollback_store.transaction() as tx:
        assert tx.get("research_partitions", part["partition_id"]) == part
        assert tx.get("tasks", task["id"])["status"] == "succeeded"


@pytest.mark.parametrize("rollback_store", BACKENDS, indirect=True)
def test_an_ordinary_store_failure_is_not_retained_as_a_refused_draft(
        audit, rollback_store, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """INJECTED FAULT: the checkpoint's own write fails after its coverage rows were staged.

    No real PostgreSQL or memory-store outage happened here. The failure is an ordinary store
    error, so it must leave the boundary as itself - never as `AuditDraftRejected` and never as a
    retained draft - and it must commit nothing.
    """
    import psycopg

    audits, record = audit_on(audit, rollback_store)
    part, task, analysis = subsystem_task(audits, record, "store-failure")
    before = committed(rollback_store)
    transactions = transaction_class(rollback_store)
    original = transactions.put

    def failing_put(self, bucket, key, body):
        if bucket == "research_checkpoints":
            raise psycopg.OperationalError("injected store write failure")
        return original(self, bucket, key, body)

    monkeypatch.setattr(transactions, "put", failing_put)

    with pytest.raises(psycopg.OperationalError) as failure:
        audits.checkpoint(task, PartitionCheckpoint(**part), [], [analysis])

    assert not isinstance(failure.value, AuditDraftRejected)
    monkeypatch.undo()
    after = committed(rollback_store)
    assert after["research_subsystems"] == [] and after["research_evidence_history"] == []
    assert after["research_checkpoints"] == []
    assert after["research_partitions"] == before["research_partitions"]


@pytest.mark.parametrize("rollback_store", BACKENDS, indirect=True)
def test_the_whole_valid_checkpoint_commits_in_one_transaction(
        audit, rollback_store):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """The acceptance control for both rollback cases above: valid work still commits whole."""
    audits, record = audit_on(audit, rollback_store)
    part, task, analysis = subsystem_task(audits, record, "valid")

    saved = audits.checkpoint(task, PartitionCheckpoint(**part), [], [analysis])

    assert saved["generation"] == part["generation"] + 1
    with rollback_store.transaction() as tx:
        assert [r["record"] for r in tx.scan("research_subsystems")] == [asdict(analysis)]
        assert any(r["record"] == asdict(analysis) for r in tx.scan("research_evidence_history"))
        assert tx.get("research_partitions", part["partition_id"]) == saved
        assert len(tx.scan("research_checkpoints")) == 1
    # Unexecuted tests are incomplete evidence: persisted, never subsystem coverage.
    assert audits.coverage(record["id"])["remaining_subsystems"] == ["core"]


def test_the_model_instructions_state_the_path_reference_contract_once(
        audit, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """Guidance, not authority: the same run still has to pass the validation above.

    The observed attempt 2 answer used display names where the contract is an inventory identity,
    so the semantic turn now says that for keys, links and subsystem trace paths together.
    """
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = assigned(service, record, "instruction-contract")
    ref = service.artifacts.put("one traced path", "fixture")["ref"]
    objectives = []

    def run_model(assignment, objective, evidence, result_schema):
        objectives.append(objective)
        if "commands" in result_schema["properties"]:
            return {"commands": []}
        return answer_for(part, {part["paths"][0]: path_body(ref)})

    monkeypatch.setattr(execution, "run_model", run_model)
    execution.execute(task)

    semantic = objectives[-1]
    for clause in ("exact Base64 identity", "the links of a generated or duplicate disposition",
                   "the paths of a subsystem record", "never in a key, a link or a trace path",
                   "never encoded, decoded, corrected or deduplicated for you",
                   # The accepted earlier clauses must not drift out with this one.
                   "null", "partition.paths", "partial is not a disposition"):
        assert clause in semantic, clause


def test_the_candidate_type_keeps_every_existing_contract_expectation():
    """Legacy compatibility: the new type IS a `ContractError`, and `require` is not it."""
    from codex_harness.domain.model import require
    from codex_harness.domain.research import reject

    assert issubclass(AuditDraftRejected, ContractError)
    with pytest.raises(ContractError, match="a candidate claim") as rejected:
        reject(False, "a candidate claim")
    assert type(rejected.value) is AuditDraftRejected
    with pytest.raises(ContractError) as ordinary:
        require(False, "a candidate claim")
    assert type(ordinary.value) is ContractError
    assert not isinstance(ordinary.value, AuditDraftRejected), "same text, different owner"
