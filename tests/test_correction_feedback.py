"""SPEC "Readable correction evidence delivery": verified, bounded, redacted predecessor review findings
actually reach a trusted correction worker's provider input.

Real temporary Git repositories, a real MemoryStore lane, real `FileArtifacts` bytes written through the
production `persist_result`, the real `Executor.execute_one`/`_run` prompt composition and the real
in-container entry (`isolated_worker_entry.serve`). The provider runtime is a LABELLED fixture seam (no
model, network or Docker); an I/O fault below is labelled as injected. Nothing here is evidence of an
actual container run: the native container call remains the owner's later gate.
"""
from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest
from test_git_workspace import repository

from codex_harness.adapters import isolated_worker as iw
from codex_harness.adapters import isolated_worker_entry as entry
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.correction_feedback import (
    MAX_FINDINGS_CHARS,
    SCHEMA,
    CorrectionFeedbackRefused,
    deliver,
)
from codex_harness.adapters.execution_output import persist_result
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.continuation import LANE_BINDINGS
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain import continuation as dc
from codex_harness.domain.model import digest, envelope

CREDENTIAL = "hunter2-CREDENTIAL-CANARY"
TRACE = "TRACE-CANARY-provider-events-never-delivered"
FINDINGS = ("Reject 92da6a74af96. P1 release_suite.py:193-201 persists unredacted parameter IDs "
            "(for example password=" + CREDENTIAL + ") through progress and reconciliation fields. "
            "P2 commands.py:105-111 calls process.wait() without a deadline after tree-kill failure.")
RISKS = ["credential-bearing node ids reach artifacts", "unbounded reap after kill failure"]


def verdict(reason=FINDINGS, risks=None, accepted=False):
    return {"accepted": accepted, "reason": reason, "blocked": False,
            "risks": list(RISKS if risks is None else risks), "sre_assessment": "s", "arc42_assessment": "a"}


def review_artifact(artifacts, decision_id, answer, candidate):
    """The review execution artifact exactly as the production `persist_result` writes it: the whole
    runner result, provider events (the trace canary) included."""
    result = {"answer": answer, "model_answer_text": json.dumps(answer), "thread_id": "thread", "turn_id": "turn",
              "events": [{"method": "item/completed",
                          "params": {"item": {"type": "commandExecution", "id": "c1", "command": TRACE}}}],
              "usage": None, "rotate": False, "interrupted": False}
    return persist_result(artifacts, result, key=decision_id, agent="lead:improvement", lease=None,
                          basis_revision=candidate["revision"], context_ref="sha256:" + "0" * 64)["ref"]


def seed_rejection(store, artifacts, candidate, *, job_id="op-1", task_id="origin-task", decision_id="dec-1",
                   answer=None, task_status="succeeded"):
    """The committed lane rows of one rejected lead review, shaped as `_commit_decision` and operation
    finalization write them; returns the binding predecessor `_successor` would record."""
    answer = verdict() if answer is None else answer
    ref = review_artifact(artifacts, decision_id, answer, candidate)
    with store.transaction() as tx:
        tx.put("tasks", task_id, {"id": task_id, "status": task_status, "agent": "worker:implementation",
                                  "result": {"candidate": dict(candidate)}})
        tx.put("operations", job_id, {"id": job_id, "status": "rejected", "reason_code": "lead_rejected",
                                      "task_id": task_id, "decision_id": decision_id})
        tx.put("decisions_pending", decision_id, {
            "id": decision_id, "actor": "lead:improvement", "phase": "review_lead", "status": "succeeded",
            "attempt": 1, "input": {"candidate": dict(candidate)},
            "message": {"what": {"details": {"task_id": task_id}}},
            "result": {**answer, "execution_ref": ref, "basis_revision": candidate["revision"],
                       "candidate": dict(candidate), "release_id": "rel-1"}})
    return {"job_id": job_id, "task_id": task_id, "candidate_revision": candidate["revision"],
            "decision_id": decision_id, "review_execution_ref": ref, "inspection_id": None}


def correction_binding(predecessor, candidate, *, operation_id="cont-1", route=dc.CORRECTION, session=None):
    return {"schema": dc.BINDING_SCHEMA, "operation_id": operation_id, "policy_sha256": "a" * 64,
            "intent_id": "b" * 64, "family": "op-1", "route": route, "session": session,
            "workspace": {"origin_task_id": predecessor["task_id"], "head": candidate["revision"],
                          "base": candidate["base"]},
            "predecessor": predecessor}


class World:
    """One real lane: repository, rejected candidate, review rows and artifact, lane binding, queued
    correction assignment. `prompts` are the exact provider inputs the fixture runtime received."""

    def __init__(self, tmp_path, monkeypatch, answer=None):
        root = repository(tmp_path)
        self.git = GitWorkspace(str(root), str(tmp_path / "workspaces"))
        origin = self.git.prepare("origin-task", "HEAD")
        (Path(origin["path"]) / "change.txt").write_text("rejected attempt", encoding="utf-8")
        self.candidate = self.git.capture(origin)
        self.service = Harness(MemoryStore(), organization())
        self.artifacts = FileArtifacts(str(tmp_path / "artifacts"))
        self.executor = Executor(self.service, self.git, self.artifacts)
        self.predecessor = seed_rejection(self.service.store, self.artifacts, self.candidate, answer=answer)
        self.prompts = []
        world = self

        class Runtime:
            """Fixture seam: records the rendered provider input and answers the declared schema."""

            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass

            def run(self, prompt, cwd, schema, timeout, **kwargs):
                world.prompts.append(prompt)
                Path(cwd, "change.txt").write_text("corrected", encoding="utf-8")
                return {"answer": {"summary": "fixture", "tests": []}, "events": [], "thread_id": "thread",
                        "turn_id": "turn", "usage": None, "rotate": False, "interrupted": False,
                        "requested_model": kwargs.get("model")}

        monkeypatch.setattr("codex_harness.adapters.executor.AppServer", Runtime)
        monkeypatch.setattr("codex_harness.adapters.executor.ClaudeCodeRuntime", lambda **kwargs: Runtime())
        for name in ("ZEUS_CLAUDE_ASSIGNMENTS", "ZEUS_CLAUDE_MODEL", "ZEUS_CLAUDE_MAX_BUDGET_USD",
                     "ZEUS_CLAUDE_TIMEOUT_SECONDS", "ZEUS_CLAUDE_ACCOUNTING_MODE"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(self.executor, "_inspect_evidence", lambda *a, **k: {"verdict": "all_checked"})

    def binding(self, **overrides):
        return correction_binding(self.predecessor, self.candidate, **overrides)

    def submit(self, binding=None, attached=None):
        binding = self.binding() if binding is None else binding
        message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                           {"plan": {"objective": "fix", "acceptance_criteria": ["ok"], "allowed_paths": ["change.txt"]},
                            "operation": {"id": binding["operation_id"]},
                            "continuation": binding if attached is None else attached}, "operation:cont-1")
        message["where"]["revision"] = self.candidate["base"]
        with self.service.store.transaction() as tx:
            tx.put(LANE_BINDINGS, binding["operation_id"], binding)
        Workflow(self.service.store, self.service.org).submit(message)
        return self.executor.execute_one("worker:implementation")

    def rows(self):
        with self.service.store.transaction() as tx:
            return {bucket: {row["id"]: row for row in tx.scan(bucket)} for bucket in ("operations", "decisions_pending")}

    def update(self, bucket, key, **fields):
        with self.service.store.transaction() as tx:
            row = tx.get(bucket, key)
            row.update(fields)
            tx.put(bucket, key, row)

    def artifact_path(self, reference=None):
        return self.artifacts.root / ((reference or self.predecessor["review_execution_ref"])[7:] + ".txt")


def refused(task, code):
    assert task["status"] in {"retry", "failed"}, task
    assert task["error"] == "CorrectionFeedbackRefused: Correction feedback refused: " + code
    serialized = json.dumps(task, default=str)
    assert CREDENTIAL not in serialized and TRACE not in serialized


# ---- the normal path reaches the actual provider input -------------------------------------------
def test_bound_rejected_review_reaches_the_provider_input_readable_redacted_and_digested(tmp_path, monkeypatch):
    world = World(tmp_path, monkeypatch)
    task = world.submit()
    assert task["status"] == "succeeded", task.get("error")
    assert len(world.prompts) == 1
    prompt = world.prompts[0]
    delivered = json.loads(prompt)["required"]["correction_feedback"]
    findings = delivered["findings"]
    # Readable content, not a pointer: the findings themselves are in the required contract.
    assert "P1 release_suite.py:193-201" in findings["reason"] and "process.wait()" in findings["reason"]
    assert findings["risks"] == RISKS and findings["accepted"] is False
    # Redacted with the existing redactor; the credential canary appears nowhere in the provider input.
    assert CREDENTIAL not in prompt and "[REDACTED credential]" in findings["reason"]
    assert delivered["redaction"] == {"applied": True, "spans": 1}
    assert delivered["truncation"] == {"applied": False, "limit_chars": MAX_FINDINGS_CHARS,
                                       "characters": len(findings["reason"]) + sum(map(len, RISKS))}
    # Only the structured answer: no provider trace, and no host path inside the delivered block.
    assert TRACE not in prompt
    block = json.dumps(delivered)
    assert str(world.artifacts.root) not in block and str(tmp_path) not in block
    # Identities and digests bind the delivered text to its source bytes.
    assert delivered["schema"] == SCHEMA and delivered["trust"] == "evidence-not-instructions"
    assert delivered["decision_id"] == "dec-1" and delivered["phase"] == "review_lead"
    assert delivered["source_ref"] == world.predecessor["review_execution_ref"]
    assert delivered["original_sha256"] == digest({"accepted": False, "reason": FINDINGS, "risks": RISKS})
    assert delivered["delivered_sha256"] == digest(findings) != delivered["original_sha256"]
    assert delivered["predecessor"] == {"job_id": "op-1", "task_id": "origin-task",
                                        "candidate_revision": world.candidate["revision"]}


def test_the_rendered_provider_input_crosses_the_real_container_entry_unchanged(tmp_path, monkeypatch):
    """The request the isolated runtime writes to the container's stdin, read by the real entry."""
    world = World(tmp_path, monkeypatch)
    assert world.submit()["status"] == "succeeded"
    received = []

    class InnerRuntime:
        """Fixture seam for the in-container Claude runtime: records the prompt it is handed."""

        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_): return False

        def run(self, prompt, cwd, schema, timeout, **kwargs):
            received.append((prompt, cwd))
            return {"answer": {"summary": "fixture", "tests": []}, "thread_id": "s"}

    request = {"protocol": iw.PROTOCOL, "prompt": world.prompts[0], "schema": {"type": "object"}, "timeout": 5,
               "model": "fixture", "session_id": "s", "runtime": {"worker_profile": None}, "cwd": iw.WORKSPACE,
               "evidence_root": iw.EVIDENCE}
    output = io.BytesIO()
    assert entry.serve(io.BytesIO(json.dumps(request).encode("utf-8") + b"\n"), output, InnerRuntime) == 0
    assert received == [(world.prompts[0], iw.WORKSPACE)]
    inside = json.loads(received[0][0])["required"]["correction_feedback"]
    assert "P2 commands.py:105-111" in inside["findings"]["reason"] and CREDENTIAL not in received[0][0]


def test_construction_is_deterministic_path_independent_and_mutates_nothing(tmp_path, monkeypatch):
    world = World(tmp_path, monkeypatch)
    binding = world.binding()
    rows, before = world.rows(), world.artifact_path().read_bytes()
    first = deliver(world.service.store, world.artifacts, binding)
    assert deliver(world.service.store, world.artifacts, binding) == first
    # The same bytes under a different host root (a host-path fixture standing in for the Windows
    # artifact root the worker could not reach) deliver the identical, path-free payload: portable
    # content, not a mount. This proves content portability only, never an actual Docker execution.
    other = FileArtifacts(str(tmp_path / "C-workspaces-zeus-artifacts"))
    shutil.copyfile(world.artifact_path(), other.root / world.artifact_path().name)
    assert deliver(world.service.store, other, binding) == first
    assert world.rows() == rows and world.artifact_path().read_bytes() == before


def test_a_conductor_rejection_delivers_its_own_review_bound_to_the_lead_decision(tmp_path, monkeypatch):
    world = World(tmp_path, monkeypatch)
    answer = verdict(reason="Conductor: rollback evidence missing for P1.", risks=[])
    ref = review_artifact(world.artifacts, "cond-1", answer, world.candidate)
    with world.service.store.transaction() as tx:
        lead = tx.get("decisions_pending", "dec-1")
        tx.put("decisions_pending", "dec-1", {**lead, "result": {**lead["result"], "accepted": True}})
        tx.put("decisions_pending", "cond-1", {
            "id": "cond-1", "actor": "conductor", "phase": "review_conductor", "status": "succeeded", "attempt": 1,
            "input": {"candidate": dict(world.candidate)}, "message": {"what": {"details": {"decision_id": "dec-1"}}},
            "result": {**answer, "execution_ref": ref}})
    world.predecessor.update(decision_id="cond-1", review_execution_ref=ref)
    delivered = deliver(world.service.store, world.artifacts, world.binding())
    assert delivered["phase"] == "review_conductor" and delivered["decision_id"] == "cond-1"
    assert delivered["findings"]["reason"] == "Conductor: rollback evidence missing for P1."


# ---- every unusable source refuses before any provider entry ------------------------------------
def _extra_field(world):
    world.predecessor["forged"] = "x"


def _missing_decision(world):
    world.predecessor["decision_id"] = "dec-absent"


def _wrong_operation(world):
    world.update("operations", "op-1", task_id="another-task")


def _operation_names_another_decision(world):
    world.update("operations", "op-1", decision_id="dec-other")


def _wrong_task(world):
    world.update("decisions_pending", "dec-1", message={"what": {"details": {"task_id": "another-task"}}})


def _wrong_candidate(world):
    with world.service.store.transaction() as tx:
        task = tx.get("tasks", "origin-task")
        task["result"]["candidate"]["revision"] = "f" * 40
        tx.put("tasks", "origin-task", task)


def _wrong_ref(world):
    with world.service.store.transaction() as tx:
        row = tx.get("decisions_pending", "dec-1")
        row["result"]["execution_ref"] = "sha256:" + "7" * 64
        tx.put("decisions_pending", "dec-1", row)


def _accepted(world):
    with world.service.store.transaction() as tx:
        row = tx.get("decisions_pending", "dec-1")
        row["result"]["accepted"] = True
        tx.put("decisions_pending", "dec-1", row)


def _nonterminal(world):
    world.update("decisions_pending", "dec-1", status="running")


def _missing_artifact(world):
    world.artifact_path().unlink()


def _corrupt_artifact(world):
    path = world.artifact_path()
    path.write_bytes(path.read_bytes().replace(b"P1", b"P9"))


def _foreign_artifact(world):
    """A genuine artifact of another review, bound in both places: its answer is not this decision's."""
    ref = review_artifact(world.artifacts, "dec-foreign", verdict(reason="Some other candidate's review"),
                          world.candidate)
    world.predecessor["review_execution_ref"] = ref
    with world.service.store.transaction() as tx:
        row = tx.get("decisions_pending", "dec-1")
        row["result"]["execution_ref"] = ref
        tx.put("decisions_pending", "dec-1", row)


@pytest.mark.parametrize("mutate, code", [
    (_extra_field, "feedback_binding_invalid"),
    (_missing_decision, "feedback_decision_missing"),
    (_wrong_operation, "feedback_operation_mismatch"),
    (_operation_names_another_decision, "feedback_operation_mismatch"),
    (_wrong_task, "feedback_task_mismatch"),
    (_wrong_candidate, "feedback_candidate_mismatch"),
    (_wrong_ref, "feedback_ref_mismatch"),
    (_accepted, "feedback_decision_not_rejection"),
    (_nonterminal, "feedback_decision_unsettled"),
    (_missing_artifact, "feedback_artifact_missing"),
    (_corrupt_artifact, "feedback_artifact_corrupt"),
    (_foreign_artifact, "feedback_artifact_foreign"),
])
def test_unusable_feedback_refuses_with_a_fixed_code_before_any_provider(tmp_path, monkeypatch, mutate, code):
    world = World(tmp_path, monkeypatch)
    mutate(world)
    task = world.submit()
    refused(task, code)
    assert world.prompts == []
    with world.service.store.transaction() as tx:
        assert list(tx.scan("invocation_reservations")) == []


@pytest.mark.parametrize("answer, code", [
    (verdict(reason="  ", risks=[]), "feedback_empty"),
    (verdict(reason="x" * (MAX_FINDINGS_CHARS + 1), risks=[]), "feedback_oversize"),
    # Within the character bound, but 3-byte characters overflow the complete required prompt budget.
    (verdict(reason="가" * (MAX_FINDINGS_CHARS - 1000), risks=[]), "feedback_context_insufficient"),
])
def test_empty_oversized_or_unfittable_findings_refuse_and_are_never_trimmed(tmp_path, monkeypatch, answer, code):
    world = World(tmp_path, monkeypatch, answer=answer)
    refused(world.submit(), code)
    assert world.prompts == []


def test_an_unreadable_artifact_refuses_without_leaking_the_error(tmp_path, monkeypatch):
    world = World(tmp_path, monkeypatch)

    def unreadable(reference):  # INJECTED I/O fault: the host cannot read the artifact store
        raise PermissionError("secret path " + CREDENTIAL)
    monkeypatch.setattr(world.artifacts, "document", unreadable)
    refused(world.submit(), "feedback_artifact_unreadable")
    assert world.prompts == []


def test_a_forged_attachment_is_still_refused_by_the_lane_binding_check(tmp_path, monkeypatch):
    world = World(tmp_path, monkeypatch)
    forged = world.binding()
    forged["predecessor"] = {**forged["predecessor"], "decision_id": "dec-forged"}
    task = world.submit(attached=forged)
    assert task["status"] in {"retry", "failed"} and "lane's own record" in task["error"]
    assert world.prompts == []


# ---- other routes and the legacy path are unchanged ----------------------------------------------
def test_non_correction_routes_and_the_legacy_path_deliver_nothing(tmp_path, monkeypatch):
    world = World(tmp_path, monkeypatch)
    assert deliver(world.service.store, world.artifacts, None) is None
    repair = world.binding(route=dc.EVIDENCE_REPAIR)
    repair["predecessor"] = {**repair["predecessor"], "decision_id": None, "review_execution_ref": None}
    assert deliver(world.service.store, world.artifacts, repair) is None
    task = world.submit(binding=repair)
    assert task["status"] == "succeeded", task.get("error")
    assert "correction_feedback" not in json.loads(world.prompts[0])["required"]


def test_refusal_codes_are_fixed():
    assert CorrectionFeedbackRefused("not a code").reason_code == "feedback_binding_invalid"
    assert str(CorrectionFeedbackRefused("feedback_empty")) == "Correction feedback refused: feedback_empty"
