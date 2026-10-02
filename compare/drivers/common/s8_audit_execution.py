"""Shared S8 scenario steps (`research.audit_execution`): M7 `adapters/audit_execution.py` (`AuditExecution`: `run_model`, `typed_schema`,
`partition_schema`, `decode_assigned`, `proposed_checkpoint`, `refused_execution`, `evidence_ref`, `analysis_binding`, `rejected_analysis`,
`execute`, `review`; the module's `schema`, `assigned_body` and `output_definitions`), characterized BEFORE the module moves (DESIGN-s8 §20 V24,
batch B3). The golden is placement-neutral: it observes SOURCE behaviour only; the move is the NEXT commits.

- **b1_discovery**: `execute` of `audit_discovery` (mapped, replayed, unmapped, unknown, lost lease, the provider failing).
- **b2_acquire**: `execute` of `audit_acquire` (the labelled runner's `acquire`, the taxonomy turn, the import and the backlog update).
- **b3_propose**: `execute` of `audit_propose` (a deferral, an adoption proposal over a complete audit, the author mismatch, replay).
- **b4_partition**: the default partition analysis (M7 `tests/test_audit_output_identity.py`, `tests/test_audit_analysis_outcomes.py`, and the
  scopes test of `tests/test_research_audits.py`): the planning and semantic turns, the checkpoint, the retained refused draft, every failure
  that is NOT converted, a returned inspection refusal, a repair context.
- **b5_review**: `review(lease)` (accepted, rejected, blocked inspection, a model-reported `inspection_blocked`, the redelivery, failures).
- **b6_static**: the static outputs (`typed_schema`, `partition_schema`, `decode_assigned`, `proposed_checkpoint`, `refused_execution`,
  `evidence_ref`, `analysis_binding`, the module constants).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a target)
driver builds. LABELLED doubles (nothing here is an actual Codex, Git, Docker, model or production verification):
- the EXECUTOR: `Executor`, whose `_run` has M7's signature and returns SCRIPTED answers (a list consumed in order, or a callable that sees
  the evidence the adapter passed); it records every call (the agent, the key, the cwd, the stage, the workload, the digests of the objective,
  the evidence and the schema). It has `git.repository` and `research.github_detail` (a recorded answer). On the REFERENCE side it also
  exposes `service.store`, `artifacts` and `workflow`, which M7's constructor reads; on the target side (`api.m7_executor` false) it has
  `store` and `artifacts` only, as the target `RunTask` has: no `service`, no `workflow`.
- the RUNNER: `AcquireRunner`, the pilot 70 `Runner` (injected receipts, never an isolated execution) plus a scripted `acquire`;
- the verifier is the pilot 70 `Verifier` (no Git); the artifacts are the product's own `FileArtifacts` over a run-scoped directory;
- the rows `Releases.promote` writes (`activate`) and the planted discovery and backlog rows are LABELLED where they are made.
Where a state has no honest call path the case is LABELLED where it is made. The store digests of the buckets each operation writes are
recorded before and after every call; every case names the M7 test it mirrors in `M7_TESTS`.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict
from pathlib import PurePosixPath
from types import SimpleNamespace

import s8_audit_core as C
import s8_research_program as R

WATCHED = ("research_discoveries", "research_backlog", "research_audits", "research_partitions", "research_paths", "research_subsystems",
           "research_checkpoints", "research_evidence_history", "research_receipts", "research_adaptations", "research_reviews",
           "research_approvals", "research_proposal_runs", "decisions_pending", "tasks", "outbox", "execution_notices",
           "execution_notice_errors", "workflow_inbox", "events")
SECRET = "password=hunter2-analysis-canary-9f1c"
REPO = "fixture/repo"
DETAIL = {"url": "https://github.com/fixture/repo", "revision": "d" * 40}
UNKNOWN_REF = "sha256:" + "b" * 64
PATH = base64.b64encode(b"normal").decode()
OTHER = base64.b64encode(b"other").decode()


# ---- labelled doubles ------------------------------------------------------------------------------------------------------
class Executor:
    """LABELLED. The executor the adapter calls: `_run` has M7's signature (the target `RunTask._run` has the identical one) and returns
    the next scripted answer; a scripted exception is raised; a callable answer is called with the evidence and this executor. `beat`
    makes the call run the `heartbeat` it was given (the real lease extension)."""

    def __init__(self, api, store, artifacts, workflow):
        self.api, self.script, self.calls, self.details, self.beat = api, [], [], [], False
        self.git = SimpleNamespace(repository=PurePosixPath("/labelled/repository"))
        self.research = SimpleNamespace(github_detail=self.github_detail)
        if api.m7_executor:   # what M7's constructor reads
            self.service, self.artifacts, self.workflow = SimpleNamespace(store=store), artifacts, workflow
        else:                 # what the target RunTask has
            self.store, self.artifacts = store, artifacts

    def github_detail(self, repository):
        self.details.append(repository)
        return dict(DETAIL)

    def take(self):
        calls, self.calls = self.calls, []
        return calls

    def _run(self, agent, key, objective, evidence, cwd, schema, read_only=False, heartbeat=None, lease=None, stage=None,
             workload="final_validation", importance=None, action=None, max_handoffs=4, delivery=None, task_session=None,
             correction_feedback=None):
        digest = self.api.digest
        beat = None
        if self.beat and heartbeat is not None:
            heartbeat()
            beat = True
        self.calls.append({
            "agent": agent, "key": key, "cwd": cwd, "read_only": read_only, "workload": workload, "stage": stage,
            "lease": None if lease is None else lease["id"], "heartbeat_given": heartbeat is not None, "heartbeat_called": beat,
            "objective_head": objective[:56], "objective_chars": len(objective), "objective": digest(objective),
            "evidence_keys": sorted(evidence), "evidence": digest(evidence), "schema_keys": sorted(schema.get("properties", {})),
            "schema": digest(schema), "defaults": [importance, action, max_handoffs, delivery, task_session, correction_feedback]})
        if not self.script:
            raise AssertionError("an unscripted model turn")
        answer = self.script.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer(evidence, self) if callable(answer) else answer


class AcquireRunner(C.Runner):
    """LABELLED. The pilot 70 `Runner` plus the scripted `acquire` of the real runner (`acquired` is the `(source, entries,
    verifier)` it returns; `fail` an exception it raises)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.acquired, self.fail, self.acquires = None, None, []

    def acquire(self, repository, commit):
        self.acquires.append([repository, commit])
        if self.fail is not None:
            raise self.fail
        return self.acquired


# ---- the environment ---------------------------------------------------------------------------------------------------------
def build(api, ws, name, imported=True, **runner_kwargs):
    """A `MemoryStore`, the real `Workflow` over the packaged organization, the product's `FileArtifacts`, the labelled verifier, runner
    and executor, the adapter under test (`api.audit_execution` wires the product's own ports) and, by default, the imported audit."""
    store = api.MemoryStore()
    workflow = api.Workflow(store, api.organization())
    artifacts = api.FileArtifacts(str(ws.case(name) / "artifacts"))
    verifier = C.Verifier(api, artifacts)
    runner = AcquireRunner(api, artifacts, **runner_kwargs)
    executor = Executor(api, store, artifacts, workflow)
    exe = api.audit_execution(executor, runner, store, artifacts, workflow)
    exe.audits.verifier = verifier
    env = SimpleNamespace(api=api, ws=ws, name=name, store=store, workflow=workflow, artifacts=artifacts, verifier=verifier, runner=runner,
                          executor=executor, exe=exe, service=exe.audits, record=None)
    env.source, env.entries = C.fixture_source(api, artifacts)
    runner.acquired = (env.source, env.entries, verifier)
    if imported:
        env.record = env.service.import_audit(env.source, env.entries, ["core"])
    return env


def snap(store) -> dict:
    """`bucket -> "<rows>:<digest16>"` of the watched buckets, and the digest of the whole store."""
    with store.transaction() as tx:
        rows = tx.records()
    out = {}
    for bucket in WATCHED:
        mine = sorted([r["id"], C.canonical_digest(r["body"])] for r in rows if r["bucket"] == bucket)
        out[bucket] = "%d:%s" % (len(mine), C.canonical_digest(mine)[:16])
    out["all"] = C.canonical_digest(sorted([r["bucket"], r["id"], C.canonical_digest(r["body"])] for r in rows))[:16]
    return out


def step(env, fn, *args, view=None, script=None, **kwargs):
    """One operation: the scripted model turns, the whole-store digest before and after, the buckets that changed, the calls the
    adapter made on its executor, runner and `github_detail`, and one tick of the fake clock."""
    if script is not None:
        env.executor.script = list(script)
    env.executor.details.clear()
    env.runner.calls.clear()
    env.runner.acquires.clear()
    before = snap(env.store)
    out = C.outcome(env.api, fn, *args, view=view, **kwargs)
    after = snap(env.store)
    env.api.advance(0.001)
    return {**out, "model_calls": env.executor.take(), "unused_answers": len(env.executor.script),
            "runner_execute_assigned": list(env.runner.calls), "runner_acquire": list(env.runner.acquires),
            "github_detail": list(env.executor.details), "store_before": before["all"], "store_after": after["all"],
            "changed": [k for k in before if k != "all" and before[k] != after[k]]}


def row(env, bucket, key):
    return C.get(env.store, bucket, key)


def result_view(result):
    """The facts of an `execute`/`review` result: its keys, the status, the analysis marker (identifiers and fixed codes only)."""
    if type(result) is not dict:
        return {"type": type(result).__name__}
    out = {"keys": sorted(result)}
    for key in ("status", "generation", "cursor", "remaining_paths", "remaining_subsystems", "accepted", "inspection_blocked"):
        if key in result:
            value = result[key]
            out[key] = len(value) if key.startswith("remaining") else value
    if "analysis" in result:
        out["analysis"] = result["analysis"]
    return out


def backlog_view(rows):
    return sorted(rows, key=lambda r: r["id"])


def backlog_of(env):
    return backlog_view(C.scan(env.store, "research_backlog"))


def answer_ref(env, text):
    return env.artifacts.put(text, "fixture")["ref"]


def plant_backlog(env, **overrides):
    """LABELLED. The backlog row `schedule_audits` writes for a mapped repository (no honest call path without the scheduler)."""
    body = {"id": "bk-1", "repository": C.REPO, "revision": C.COMMIT, "priority": 100, "status": "discovered_not_reviewed",
            "discovery_id": "disc-1", "mapping_ref": None, "manifest_ref": None}
    body.update(overrides)
    C.put(env.store, "research_backlog", body["id"], body)
    return body


def fresh(env, details, action="audit_partition", name="fixture", agent="worker:github"):
    """A real submitted and claimed task. The adapter never settles its task, so what an earlier case left running is settled first
    (LABELLED: a direct `tasks` write; no honest call path settles a task the adapter abandoned)."""
    with env.store.transaction() as tx:
        for old in tx.scan("tasks"):
            if old["status"] == "running":
                tx.put("tasks", old["id"], {**old, "status": "cancelled"})
    return C.assign(env, details, action=action, name=name, agent=agent)


# ---- b1: audit_discovery -----------------------------------------------------------------------------------------------------
def b1_discovery(api, ws):
    out = {}
    env = build(api, ws, "discovery", imported=False)
    C.put(env.store, "research_discoveries", "disc-1", {"id": "disc-1", "title": "labelled discovery", "status": "open"})   # LABELLED plant
    mapping = {"repository": REPO, "reason": "named in the cited evidence", "execution_ref": answer_ref(env, "the mapping answer")}

    env.executor.beat = True
    task = fresh(env, {"discovery_id": "disc-1"}, action="audit_discovery", name="disc-mapped")
    out["mapped_writes_one_backlog_row"] = step(env, env.exe.execute, task, script=[mapping], view=lambda r: r)
    env.executor.beat = False
    out["backlog_after_mapped"] = backlog_of(env)
    task2 = fresh(env, {"discovery_id": "disc-1"}, action="audit_discovery", name="disc-replay")
    out["replay_does_not_rewrite_the_row"] = step(env, env.exe.execute, task2, script=[mapping], view=lambda r: r)
    out["backlog_after_replay"] = backlog_of(env)

    task3 = fresh(env, {"discovery_id": "disc-1"}, action="audit_discovery", name="disc-unmapped")
    out["unmapped_returns_the_reason_and_writes_nothing"] = step(
        env, env.exe.execute, task3, script=[{"repository": "", "reason": "no canonical repository", "execution_ref": answer_ref(env, "unmapped")}],
        view=lambda r: r)
    task4 = fresh(env, {"discovery_id": "no-such-discovery"}, action="audit_discovery", name="disc-unknown")
    out["unknown_discovery_is_refused_before_any_model_turn"] = step(env, env.exe.execute, task4, script=[mapping])
    task5 = fresh(env, {"discovery_id": "disc-1"}, action="audit_discovery", name="disc-provider-failure")
    out["a_failing_provider_propagates"] = step(env, env.exe.execute, task5, script=[env.api.ContractError("injected provider refusal")])
    task6 = fresh(env, {"discovery_id": "disc-1"}, action="audit_discovery", name="disc-lost-lease")
    other = {"repository": "fixture/other", "reason": "named", "execution_ref": answer_ref(env, "other mapping")}

    def lose_the_lease(evidence, executor):   # LABELLED seam: the task settles while the model works
        env.workflow.complete(task6, {"settled": "elsewhere"})
        return other
    out["a_lost_lease_refuses_the_write"] = step(env, env.exe.execute, task6, script=[lose_the_lease])
    out["backlog_after_the_refusals"] = backlog_of(env)
    task7 = fresh(env, {}, action="audit_discovery", name="disc-no-id")
    out["missing_discovery_id_is_a_key_error"] = step(env, env.exe.execute, task7, script=[mapping])
    return out


# ---- b2: audit_acquire -------------------------------------------------------------------------------------------------------
def audit_view(env):
    return {"audits": len(C.scan(env.store, "research_audits")), "partitions": len(C.scan(env.store, "research_partitions")),
            "backlog": backlog_of(env)}


def b2_acquire(api, ws):
    out = {}
    env = build(api, ws, "acquire", imported=False)
    plant_backlog(env)
    details = {"repository": C.REPO, "commit": C.COMMIT, "backlog_id": "bk-1"}
    task = fresh(env, details, action="audit_acquire", name="acquire-first")
    out["acquire_imports_partitions_and_updates_the_backlog"] = step(
        env, env.exe.execute, task, script=[{"subsystems": ["core", "tests"]}],
        view=lambda r: {"keys": sorted(r), "audit_id_is_set": bool(r["audit_id"]), "source": r["source"]})
    out["state_after_acquire"] = audit_view(env)
    out["the_verifier_is_installed_on_the_audits"] = env.service.verifier is env.verifier
    task2 = fresh(env, details, action="audit_acquire", name="acquire-replay")
    out["acquire_replay_is_idempotent"] = step(env, env.exe.execute, task2, script=[{"subsystems": ["core", "tests"]}],
                                               view=lambda r: {"keys": sorted(r), "audit_id_is_set": bool(r["audit_id"])})
    out["state_after_replay"] = audit_view(env)

    env = build(api, ws, "acquire-refusals", imported=False)
    plant_backlog(env)
    task = fresh(env, details, action="audit_acquire", name="acquire-empty-taxonomy")
    out["an_empty_taxonomy_is_refused_by_the_import"] = step(env, env.exe.execute, task, script=[{"subsystems": []}])
    task = fresh(env, details, action="audit_acquire", name="acquire-duplicate-taxonomy")
    out["a_duplicate_taxonomy_is_refused_by_the_import"] = step(env, env.exe.execute, task, script=[{"subsystems": ["core", "core"]}])
    task = fresh(env, details, action="audit_acquire", name="acquire-no-taxonomy")
    out["a_taxonomy_without_subsystems_is_a_key_error"] = step(env, env.exe.execute, task, script=[{}])
    env.runner.fail = env.api.ContractError("injected acquire refusal")
    task = fresh(env, details, action="audit_acquire", name="acquire-runner-failure")
    out["a_failing_acquire_runs_no_model_turn"] = step(env, env.exe.execute, task, script=[{"subsystems": ["core"]}])
    env.runner.fail = None

    env = build(api, ws, "acquire-backlog", imported=False)
    plant_backlog(env, revision="f" * 40)
    task = fresh(env, details, action="audit_acquire", name="acquire-changed-backlog")
    out["a_changed_backlog_source_is_refused_after_the_import"] = step(env, env.exe.execute, task, script=[{"subsystems": ["core"]}])
    out["state_after_the_changed_backlog"] = audit_view(env)
    env = build(api, ws, "acquire-no-backlog", imported=False)
    task = fresh(env, details, action="audit_acquire", name="acquire-no-row")
    out["an_unknown_backlog_row_is_refused_after_the_import"] = step(env, env.exe.execute, task, script=[{"subsystems": ["core"]}])
    out["state_after_the_unknown_backlog"] = audit_view(env)
    return out


# ---- b3: audit_propose -------------------------------------------------------------------------------------------------------
def proposal_answer(env, **overrides):
    return asdict(C.proposal(env, **overrides))


def b3_propose(api, ws):
    out = {}
    env = build(api, ws, "propose")
    audit_id = env.record["id"]
    run_view = lambda r: {"keys": sorted(r), "status": r.get("status"), "decision": r.get("decision")}   # noqa: E731
    task = fresh(env, {"audit_id": audit_id}, action="audit_propose", name="propose-defer")
    out["a_deferral_is_stored_and_recorded"] = step(env, env.exe.execute, task, script=[proposal_answer(env, decision="defer")], view=run_view)
    out["proposal_run_row"] = row(env, "research_proposal_runs", audit_id)
    task = fresh(env, {"audit_id": audit_id}, action="audit_propose", name="propose-replay")
    out["a_replay_of_the_same_proposal_is_idempotent"] = step(env, env.exe.execute, task, script=[proposal_answer(env, decision="defer")], view=run_view)
    task = fresh(env, {"audit_id": audit_id}, action="audit_propose", name="propose-author")
    out["another_author_is_refused_before_the_proposal"] = step(env, env.exe.execute, task, script=[proposal_answer(env, decision="defer", author="lead:research")])
    task = fresh(env, {"audit_id": "no-such-audit"}, action="audit_propose", name="propose-unknown")
    out["an_unknown_audit_is_refused_before_any_model_turn"] = step(env, env.exe.execute, task, script=[proposal_answer(env, decision="defer")])
    task = fresh(env, {"audit_id": audit_id}, action="audit_propose", name="propose-missing-key")
    broken = proposal_answer(env, decision="defer")
    broken.pop("reason")
    out["an_answer_missing_a_schema_key_is_a_key_error"] = step(env, env.exe.execute, task, script=[broken])
    task = fresh(env, {"audit_id": audit_id}, action="audit_propose", name="propose-invalid")
    out["an_invalid_decision_is_refused_by_the_decoder"] = step(env, env.exe.execute, task, script=[proposal_answer(env, decision="maybe")])
    task = fresh(env, {"audit_id": audit_id}, action="audit_propose", name="propose-before-coverage")
    out["an_adoption_before_any_coverage_is_refused"] = step(env, env.exe.execute, task, script=[proposal_answer(env, decision="adapt")])

    env = build(api, ws, "propose-adopt")
    C.activate(env)
    adopted = C.complete_audit(env)
    task = fresh(env, {"audit_id": env.record["id"]}, action="audit_propose", name="propose-adapt")
    out["an_adaptation_over_a_complete_audit_queues_the_lead_review"] = step(
        env, env.exe.execute, task, script=[asdict(adopted)], view=run_view)
    out["queued_reviews"] = [C.decision_view(r) for r in C.scan(env.store, "decisions_pending")]
    return out


# ---- b4: the default partition analysis --------------------------------------------------------------------------------------
def path_body(env, path, ref, kind="semantic", **fields):
    values = {k: v for k, v in asdict(C.path_disposition(env, path, kind, ref)).items() if k != "path"}
    values.update(fields)
    return values


def subsystem_body(env, ref, **fields):
    values = {k: v for k, v in asdict(C.analysis(env, ref)).items() if k != "name"}
    values.update(fields)
    return values


def answer_for(part, paths=None, subsystems=None, **fields):
    """Every assigned identity present exactly once: a body for analyzed work, null for the rest (M7 `answer_for`)."""
    return {"paths": {key: (paths or {}).get(key) for key in part["paths"]},
            "subsystems": {key: (subsystems or {}).get(key) for key in part["subsystems"]},
            "open_questions": [], "cursor": "fixture-cursor", **fields}


def inspection_envelope(ref, **content):
    """The shape `Executor._run` RETURNS when required inspection is blocked (M7 `inspection_envelope`): an INJECTED envelope."""
    return {"accepted": False, "inspection_blocked": True, "basis_revision": "fixture-revision",
            "reason": "inspection-blocked: namespace creation denied; " + SECRET, "execution_ref": ref, **content}


def partition_state(env):
    return {bucket: C.scan(env.store, bucket) for bucket in ("research_partitions", "research_paths", "research_subsystems",
                                                             "research_checkpoints", "research_evidence_history", "research_receipts")}


def planned(commands):
    return {"commands": [list(c) for c in commands]}


def analysis_case(env, task, script, view=result_view):
    """One partition execution plus the stored state it left (the digests of the research rows and the coverage)."""
    before = partition_state(env)
    out = step(env, env.exe.execute, task, script=script, view=view)
    out["research_rows_unchanged"] = partition_state(env) == before
    return out


def partition_env(api, ws, name, kind="paths", limit=2, **kwargs):
    env = build(api, ws, name, **kwargs)
    C.activate(env)
    part, task = C.assigned(env, kind=kind, limit=limit, name=name, generation=True)
    return env, part, task


def b4_partition(api, ws):
    out = {}
    # the accepted checkpoint: all null, one record, with and without the executor-owned reference (M7 analysis_outcomes tests 1-2,
    # output_identity tests 8-9, the scopes test of test_research_audits)
    env, part, task = partition_env(api, ws, "analysis-all-null")
    draft = answer_ref(env, "the accepted draft")
    out["partition_shape"] = {"paths": len(part["paths"]), "subsystems": part["subsystems"], "generation": part["generation"]}
    out["all_null_advances_the_generation_without_coverage"] = analysis_case(env, task, [planned([]), answer_for(
        part, open_questions=["nothing analyzed yet"]) | {"execution_ref": draft}])
    out["all_null_coverage"] = C.coverage_of(env)
    out["all_null_research_paths"] = len(C.scan(env.store, "research_paths"))

    env, part, task = partition_env(api, ws, "analysis-one-record")
    ref = answer_ref(env, "one traced path")
    draft = answer_ref(env, "the accepted draft")
    answer = answer_for(part, {part["paths"][0]: path_body(env, part["paths"][0], ref)}, open_questions=["the remaining paths are not read"],
                        cursor="1") | {"execution_ref": draft}
    out["one_record_checkpoints_and_binds_partial_progress"] = analysis_case(env, task, [planned([]), answer])
    out["one_record_coverage"] = C.coverage_of(env)
    out["one_record_rows"] = {"paths": [r["record"]["path"] == part["paths"][0] for r in C.scan(env.store, "research_paths")],
                              "history": len(C.scan(env.store, "research_evidence_history"))}
    out["one_record_model_calls_name_the_turns"] = [[c["workload"], c["schema_keys"], c["read_only"]] for c in
                                                    out["one_record_checkpoints_and_binds_partial_progress"]["model_calls"]]

    env, part, task = partition_env(api, ws, "analysis-unbound")
    ref = answer_ref(env, "one traced path")
    out["an_answer_without_executor_evidence_checkpoints_and_stays_unclassified"] = analysis_case(
        env, task, [planned([]), answer_for(part, {part["paths"][0]: path_body(env, part["paths"][0], ref)})])

    # planning with commands: the runner executes each under the lease, the receipts reach the semantic turn
    env, part, task = partition_env(api, ws, "analysis-receipts", limit=1)
    seen = {}

    def semantic(evidence, executor):
        receipt = evidence["receipts"][0]
        seen["receipts"] = len(evidence["receipts"])
        ref = receipt["receipt"]["output_ref"]
        body = path_body(env, part["paths"][0], ref, method="fixture-inspection", receipt_ids=[receipt["id"]])
        return answer_for(part, {part["paths"][0]: body}, cursor="done") | {"execution_ref": answer_ref(env, "the receipt-bound draft")}
    out["receipts_reach_the_semantic_turn_and_credit_the_path"] = analysis_case(
        env, task, [planned([["fixture-inspection"]]), semantic])
    out["receipts_seen_by_the_semantic_turn"] = seen
    out["receipt_bound_coverage"] = C.coverage_of(env)

    # the subsystem partition (the scopes test, subsystems param)
    env, part, task = partition_env(api, ws, "analysis-subsystem", kind="subsystems", limit=2)
    ref = answer_ref(env, "partial semantic trace")
    out["a_subsystem_partition_checkpoints_partial_progress"] = analysis_case(env, task, [planned([]), answer_for(
        part, subsystems={part["subsystems"][0]: subsystem_body(env, ref)}, open_questions=["remaining work"], cursor="partial") | {
        "execution_ref": answer_ref(env, "subsystem draft")}])

    # the retained refused draft (M7 analysis_outcomes test 3 and output_identity test 10): one fresh task per shape
    def shape(name, e, p, d):
        first, alien = p["paths"][0], "Zm9yZWlnbg=="
        base = answer_for(p)
        return {"generated_without_link": lambda: answer_for(p, {first: path_body(e, first, d, "generated", links=[])}),
                "malformed_shape": lambda: {**base, "paths": {alien: path_body(e, first, d)}},
                "invalid_cursor": lambda: answer_for(p, cursor=""),
                "invalid_questions": lambda: answer_for(p, open_questions=["", 7]),
                "foreign_key": lambda: {**base, "paths": {**base["paths"], alien: path_body(e, first, d)}},
                "missing_key": lambda: {**base, "paths": {first: path_body(e, first, d)}},
                "legacy_array": lambda: {**base, "paths": [{**path_body(e, first, d), "path": first}]},
                "inner_identity": lambda: {**base, "paths": {**base["paths"], first: {**path_body(e, first, d), "path": first}}}}[name]()
    names = ("generated_without_link", "malformed_shape", "invalid_cursor", "invalid_questions", "foreign_key", "missing_key", "legacy_array",
             "inner_identity")
    out["the_rejected_shapes"] = list(names)
    for name in names:
        e, p, t = partition_env(api, ws, "analysis-rejected-" + name)
        d = answer_ref(e, "the refused draft, retained verbatim")
        out["refused_draft_" + name] = analysis_case(e, t, [planned([]), shape(name, e, p, d) | {"execution_ref": d}])
        out["refused_draft_" + name + "_coverage"] = {k: v for k, v in C.coverage_of(e).items() if k in ("reviewed_paths", "remaining_subsystems")}
    e, p, t = partition_env(api, ws, "analysis-rejected-subsystem", kind="subsystems", limit=2)
    d = answer_ref(e, "the refused draft, retained verbatim")
    out["refused_draft_missing_subsystem_trace"] = analysis_case(e, t, [planned([]), answer_for(
        p, subsystems={p["subsystems"][0]: subsystem_body(e, d, contracts=[])}) | {"execution_ref": d}])

    # the second half of the boundary: AuditDraftRejected from the checkpoint (an invented evidence artifact; a blocked receipt)
    e, p, t = partition_env(api, ws, "analysis-checkpoint-rejected")
    d = answer_ref(e, "the refused draft, retained verbatim")
    out["a_checkpoint_rejection_is_retained_like_a_refused_draft"] = analysis_case(e, t, [planned([]), answer_for(
        p, {p["paths"][0]: path_body(e, p["paths"][0], C.INVENTED)}) | {"execution_ref": d}])
    e, p, t = partition_env(api, ws, "analysis-blocked-receipt", limit=1)
    e.runner.blocked, e.runner.passed, e.runner.outcome = True, False, "isolation_unavailable"
    d = answer_ref(e, "the blocked-receipt draft")

    def cites_blocked(evidence, executor):
        receipt = evidence["receipts"][0]
        body = path_body(e, p["paths"][0], receipt["receipt"]["output_ref"], method="fixture-inspection", receipt_ids=[receipt["id"]])
        return answer_for(p, {p["paths"][0]: body}) | {"execution_ref": d}
    out["a_claim_over_a_blocked_receipt_is_a_checkpoint_rejection"] = analysis_case(e, t, [planned([["fixture-inspection"]]), cites_blocked])

    # the canary stays out of the retained result (analysis_outcomes test 4); the refusal message is an INJECTED fault (the seam M7 patches)
    e, p, t = partition_env(api, ws, "analysis-secret")
    d = answer_ref(e, "the refused draft with " + SECRET)
    message = "Unknown disposition in " + SECRET

    def refusing_boundary(trusted, answer):
        raise e.api.ContractError(message)
    e.exe.proposed_checkpoint = refusing_boundary   # LABELLED seam: M7 `monkeypatch.setattr(execution, "proposed_checkpoint", ...)`
    result = analysis_case(e, t, [planned([]), answer_for(p) | {"execution_ref": d}])
    out["no_raw_text_from_a_refused_draft_reaches_the_result"] = {
        "case": result, "error_digest_is_the_injected_messages": result["view"]["analysis"]["error_digest"] == e.api.digest(message),
        "canary_in_the_result": SECRET in e.api.canonical(result), "hunter2_in_the_result": "hunter2" in e.api.canonical(result)}

    # missing or unreadable rejection evidence stays a failure (analysis_outcomes test 5)
    for kind in ("absent", "unknown_artifact", "modified_artifact"):
        e, p, t = partition_env(api, ws, "analysis-evidence-" + kind)
        d = answer_ref(e, "the refused draft, retained verbatim")
        ref = {"absent": None, "unknown_artifact": UNKNOWN_REF, "modified_artifact": d}[kind]
        if kind == "modified_artifact":
            (e.artifacts.root / (d[7:] + ".txt")).write_text("rewritten", encoding="utf-8")
        bad = answer_for(p, {p["paths"][0]: path_body(e, p["paths"][0], d, "generated", links=[])})
        out["rejection_evidence_" + kind + "_stays_a_failure"] = analysis_case(
            e, t, [planned([]), bad if ref is None else bad | {"execution_ref": ref}])

    # failures outside the content boundary are never converted (analysis_outcomes test 6)
    e, p, t = partition_env(api, ws, "analysis-failure-model")
    out["a_model_failure_is_not_converted"] = analysis_case(e, t, [e.api.ContractError("injected provider refusal")])
    e, p, t = partition_env(api, ws, "analysis-failure-runner")
    d = answer_ref(e, "the refused draft, retained verbatim")

    class LostRunner:   # LABELLED seam: M7 patches `execution.audits.runner` the same way
        def execute_assigned(self, *args):
            raise e.api.ContractError("injected runner loss")
    e.exe.audits.runner = LostRunner()
    out["a_runner_failure_is_not_converted"] = analysis_case(e, t, [planned([["source-list"]]), answer_for(p) | {"execution_ref": d}])
    e, p, t = partition_env(api, ws, "analysis-failure-checkpoint")
    d = answer_ref(e, "the refused draft, retained verbatim")

    def failing_checkpoint(*args, **kwargs):   # LABELLED seam: an ordinary ContractError carrying a checkpoint-looking message
        raise e.api.ContractError("Runner receipt missing, stale, blocked or unsuccessful")
    e.exe.audits.checkpoint = failing_checkpoint
    e.exe.proposed_checkpoint = lambda trusted, answer: (trusted, [], [])
    out["an_ordinary_checkpoint_refusal_is_not_converted"] = analysis_case(e, t, [planned([]), answer_for(p) | {"execution_ref": d}])
    for failure in ("trusted_partition", "stale_assignment", "missing_partition"):
        e, p, t = partition_env(api, ws, "analysis-failure-" + failure)
        row_ = C.get(e.store, "research_partitions", p["partition_id"])
        if failure == "trusted_partition":
            C.put(e.store, "research_partitions", p["partition_id"], {**row_, "remaining_paths": ["Zm9yZWlnbg=="]})   # LABELLED plant
        elif failure == "stale_assignment":
            C.put(e.store, "research_partitions", p["partition_id"], {**row_, "generation": row_["generation"] + 1})   # LABELLED plant
        else:
            with e.store.transaction() as tx:
                tx.delete("research_partitions", p["partition_id"]) if hasattr(tx, "delete") else tx.put(
                    "research_partitions", p["partition_id"], None)
        out["the_trusted_assignment_failure_" + failure] = analysis_case(e, t, [planned([]), answer_for(p) | {"execution_ref": "sha256:" + "0" * 64}])
    e, p, t = partition_env(api, ws, "analysis-failure-no-generation")
    task_no_gen = fresh(e, {"audit_id": e.record["id"], "partition_id": p["partition_id"]}, name="analysis-no-generation")
    out["an_assignment_without_a_generation_is_a_key_error"] = analysis_case(e, task_no_gen, [planned([]), answer_for(p)])
    e, p, t = partition_env(api, ws, "analysis-failure-unknown-audit")
    task_unknown = fresh(e, {"audit_id": "no-such-audit", "partition_id": p["partition_id"], "generation": 1}, name="analysis-unknown-audit")
    out["an_unknown_audit_is_refused_before_any_model_turn"] = analysis_case(e, task_unknown, [planned([])])
    e, p, t = partition_env(api, ws, "analysis-command-budget")
    out["more_than_four_commands_exceed_the_budget"] = analysis_case(e, t, [planned([["source-list"]] * 5)])
    e, p, t = partition_env(api, ws, "analysis-plan-without-commands")
    out["a_plan_without_commands_is_a_key_error"] = analysis_case(e, t, [{}])
    e, p, t = partition_env(api, ws, "analysis-one-command-runs-under-the-lease", limit=1)
    out["each_planned_command_runs_through_the_runner"] = analysis_case(e, t, [planned([["source-list", "0"], ["source-read", "x", "0", "0"]]), answer_for(p) | {
        "execution_ref": answer_ref(e, "draft")}])

    # a returned inspection refusal is never a rejected draft (analysis_outcomes test 7)
    for turn in ("planning", "semantic", "semantic_carrying_content"):
        e, p, t = partition_env(api, ws, "analysis-returned-" + turn)
        retained = answer_ref(e, "the blocked inspection output, retained")
        if turn == "planning":
            script = [inspection_envelope(retained)]
        elif turn == "semantic":
            script = [planned([]), inspection_envelope(retained)]
        else:
            script = [planned([]), inspection_envelope(retained, **answer_for(p, {p["paths"][0]: path_body(e, p["paths"][0], retained)}))]
        out["a_returned_inspection_refusal_" + turn] = analysis_case(e, t, script)
        out["a_returned_inspection_refusal_" + turn + "_receipts"] = len(C.scan(e.store, "research_receipts"))

    # the bounded repair context of ONE refused predecessor (`repair_evidence`), allow-listed into the evidence and the instruction
    e, p, t = partition_env(api, ws, "analysis-repair")
    repair = {"schema": "urn:zeus:audit-repair:1", "version": 1, "correction_id": "corr-1", "source_task_id": "task-1",
              "source_execution_ref": UNKNOWN_REF, "diagnosis": "missing_test_disposition", "attempt": 1, "subsystems": ["core", "bad name"],
              "subsystems_total": 2, "subsystems_truncated": False, "injected": "never reaches the prompt"}
    rt = fresh(e, {"audit_id": e.record["id"], "partition_id": p["partition_id"], "generation": p["generation"], "repair": repair},
                  name="analysis-repair-task")
    out["a_repair_context_reaches_the_evidence_and_the_instruction"] = analysis_case(
        e, rt, [planned([]), answer_for(p) | {"execution_ref": answer_ref(e, "repair draft")}])
    e, p, t = partition_env(api, ws, "analysis-repair-foreign")
    rt = fresh(e, {"audit_id": e.record["id"], "partition_id": p["partition_id"], "generation": p["generation"],
                      "repair": {**repair, "schema": "urn:foreign"}}, name="analysis-repair-foreign-task")
    out["a_foreign_repair_context_leaves_an_ordinary_continuation"] = analysis_case(
        e, rt, [planned([]), answer_for(p) | {"execution_ref": answer_ref(e, "foreign draft")}])
    return out


# ---- b5: review --------------------------------------------------------------------------------------------------------------
def proposed(api, ws, name, **runner_kwargs):
    """An activated audit, completed under successful receipts and proposed for adoption (the reviews are the case's own)."""
    env = build(api, ws, name, **runner_kwargs)
    C.activate(env)
    adopted = C.complete_audit(env)
    env.service.propose(env.record["id"], adopted)
    return env, adopted


def review_answer(env, accepted=True, **overrides):
    values = {"accepted": accepted, "license_assessment": "license", "dependency_assessment": "deps", "sre_assessment": "sre",
              "architecture_assessment": "architecture", "graph_assessment": "graph", "execution_ref": answer_ref(env, "review answer")}
    values.update(overrides)
    return values


def decision_state(env):
    return {"decisions": [(r["actor"], r["status"]) for r in sorted(C.scan(env.store, "decisions_pending"), key=lambda r: (r["actor"], r["status"]))],
            "reviews": len(C.scan(env.store, "research_reviews")), "approvals": C.approvals_of(env),
            "notices": len(C.scan(env.store, "execution_notices")), "outbox": len(C.scan(env.store, "outbox"))}


def review_result(r):
    return {"keys": sorted(r), "status": r.get("status"), "accepted": (r.get("result") or {}).get("accepted"),
            "result_keys": sorted(r.get("result") or {}), "attempt": r.get("attempt"), "completed_at_is_set": bool(r.get("completed_at"))}


def b5_review(api, ws):
    out = {}
    env, adopted = proposed(api, ws, "review-lifecycle")
    lead = C.lease_review(env, "lead:research")
    out["lead_accepts_and_the_conductor_is_queued"] = step(env, env.exe.review, lead, script=[review_answer(env)], view=review_result)
    out["after_the_lead"] = decision_state(env)
    conductor = C.lease_review(env, "conductor")
    out["conductor_accepts_and_the_approval_is_recorded"] = step(env, env.exe.review, conductor, script=[review_answer(env)], view=review_result)
    out["after_the_conductor"] = decision_state(env)
    out["coverage_after_both"] = C.coverage_of(env)["adoption_eligible"]

    env, adopted = proposed(api, ws, "review-rejected")
    lead = C.lease_review(env, "lead:research")
    out["a_rejected_review_succeeds_as_a_decision"] = step(env, env.exe.review, lead, script=[review_answer(env, accepted=False)], view=review_result)
    out["after_the_rejection"] = decision_state(env)

    env, adopted = proposed(api, ws, "review-inspection-blocked")
    env.runner.blocked, env.runner.passed, env.runner.outcome = True, False, "isolation_unavailable"
    lead = C.lease_review(env, "lead:research")
    out["a_blocked_inspection_runs_no_model_turn"] = step(env, env.exe.review, lead, script=[review_answer(env)], view=review_result)
    out["after_the_blocked_inspection"] = decision_state(env)
    out["the_blocked_decision_row"] = {k: v for k, v in (row(env, "decisions_pending", lead["id"]) or {}).items()
                                       if k in ("status", "result")}

    env, adopted = proposed(api, ws, "review-model-blocked")
    lead = C.lease_review(env, "lead:research")
    blocked_answer = {"accepted": False, "inspection_blocked": True, "reason": "model reports a blocked inspection",
                      "execution_ref": answer_ref(env, "blocked answer")}
    out["a_model_reported_inspection_block_is_recorded_with_a_notice"] = step(env, env.exe.review, lead, script=[blocked_answer], view=review_result)
    out["after_the_model_block"] = decision_state(env)

    env, adopted = proposed(api, ws, "review-failures")
    lead = C.lease_review(env, "lead:research")
    out["a_provider_failure_leaves_only_the_inspection_receipt"] = step(env, env.exe.review, lead, script=[env.api.ContractError("injected provider refusal")])
    incomplete = review_answer(env)
    incomplete.pop("graph_assessment")
    out["an_answer_missing_an_assessment_is_a_key_error"] = step(env, env.exe.review, lead, script=[incomplete])

    def lose_the_lease(evidence, executor):   # LABELLED seam: the decision is settled elsewhere while the model works
        C.put(env.store, "decisions_pending", lead["id"], {**row(env, "decisions_pending", lead["id"]), "status": "failed"})
        return review_answer(env)
    out["a_lost_lease_refuses_the_final_write"] = step(env, env.exe.review, lead, script=[lose_the_lease])
    out["the_lost_lease_row_status"] = row(env, "decisions_pending", lead["id"])["status"]

    env, adopted = proposed(api, ws, "review-unauthorized")
    lead = C.lease_review(env, "lead:research")
    other = {**lead, "actor": "worker:github"}
    C.put(env.store, "decisions_pending", lead["id"], {**row(env, "decisions_pending", lead["id"]), "actor": "worker:github"})   # LABELLED plant
    out["a_decision_of_an_unauthorized_actor_is_refused_by_the_audit_review"] = step(env, env.exe.review, other, script=[review_answer(env)])
    out["the_unauthorized_attempt_left_the_decision"] = decision_state(env)
    stale = {**lead, "generation": lead["generation"] + 1}
    out["a_lease_of_another_generation_is_stale"] = step(env, env.exe.review, stale, script=[review_answer(env)])

    env, adopted = proposed(api, ws, "review-redelivery")
    lead = C.lease_review(env, "lead:research")
    out["the_first_delivery_records_the_review"] = step(env, env.exe.review, lead, script=[review_answer(env)], view=review_result)
    out["a_redelivery_after_the_decision_succeeded_is_refused"] = step(env, env.exe.review, lead, script=[review_answer(env)], view=review_result)
    return out


# ---- b6: the static outputs --------------------------------------------------------------------------------------------------
def b6_static(api, ws):
    out = {}
    A = api.module.AuditExecution
    digest = api.digest

    def outcome(fn, *args, view=None):
        return C.outcome(api, fn, *args, view=view)

    # constants and the schema helpers
    out["constants"] = {"ANALYSIS_VERSION": api.module.ANALYSIS_VERSION, "INSPECTION_REFUSED": api.module.INSPECTION_REFUSED,
                        "PRE_SUBMISSION": digest(api.module.PRE_SUBMISSION), "REPAIR_INSTRUCTION": digest(api.module.REPAIR_INSTRUCTION),
                        "TEXT": api.module.TEXT, "STRINGS": api.module.STRINGS, "NULL": api.module.NULL}
    out["schema_helper"] = api.module.schema(a=api.module.TEXT, b=api.module.NULL)
    definition = {"properties": {"path": {"type": "string"}, "justification": {"type": "string"}}, "required": ["path", "justification"], "type": "object"}
    out["assigned_body_drops_the_identity"] = api.module.assigned_body(definition, "path")
    definitions = api.module.output_definitions()
    out["output_definitions"] = {"keys": sorted(definitions), "digest": digest(definitions),
                                 "tests_not_run_items": definitions["SubsystemAnalysis"]["properties"]["tests_not_run"]["items"],
                                 "disposition": definitions["PathDisposition"]["properties"]["disposition"]}
    for kind in ("AdaptationProposal", "IndependentReview", "PathDisposition", "SubsystemAnalysis", "SourceIdentity", "PartitionCheckpoint"):
        out["typed_schema_" + kind] = outcome(A.typed_schema, kind, view=lambda s: {"digest": digest(s), "keys": sorted(s.get("properties", {})),
                                                                                    "defs": sorted(s["$defs"]), "required": s.get("required")})
    out["typed_schema_unknown_kind"] = outcome(A.typed_schema, "Nope")
    out["typed_schema_is_fresh_each_call"] = A.typed_schema("PathDisposition") is not A.typed_schema("PathDisposition")

    # partition_schema: unscoped, scoped, empty, duplicate identity (output_identity tests 1-3, the vocabulary test)
    view = lambda s: {"digest": digest(s), "properties": sorted(s["properties"]), "defs": sorted(s["$defs"]), "paths": s["properties"]["paths"],   # noqa: E731
                      "subsystems": s["properties"]["subsystems"]}
    out["partition_schema_unscoped"] = outcome(A.partition_schema, view=view)
    for name, partition in (("paths_only", {"paths": [PATH, OTHER], "subsystems": []}), ("subsystems_only", {"paths": [], "subsystems": ["core"]}),
                            ("empty", {"paths": [], "subsystems": []}), ("both", {"paths": [PATH], "subsystems": ["core", "tests"]})):
        out["partition_schema_" + name] = outcome(A.partition_schema, partition, view=view)
        out["partition_schema_" + name + "_assigned_defs"] = outcome(
            A.partition_schema, partition, view=lambda s: {k: s["$defs"][k] for k in sorted(s["$defs"]) if k.startswith("Assigned")})
    out["partition_schema_duplicate_path"] = outcome(A.partition_schema, {"paths": [PATH, PATH], "subsystems": []})
    out["partition_schema_duplicate_subsystem"] = outcome(A.partition_schema, {"paths": [], "subsystems": ["core", "core"]})
    out["partition_schema_does_not_mutate_the_packaged_definitions"] = digest(api.module.output_definitions()) == out["output_definitions"]["digest"]

    # decode_assigned (output_identity tests 4-7)
    ref = "sha256:" + "0" * 64

    def body(kind="semantic", **fields):
        values = {"disposition": kind, "evidence_refs": [ref], "symbols": ["symbol"], "justification": "traced", "links": [], "method": "",
                  "receipt_ids": []}
        values.update(fields)
        return values
    names = lambda records: [(r.path, r.disposition) for r in records]   # noqa: E731
    out["decode_injects_the_trusted_key_and_omits_nulls"] = outcome(
        A.decode_assigned, "PathDisposition", "path", [PATH, OTHER], {PATH: body(), OTHER: None}, view=names)
    out["decode_empty_subsystems"] = outcome(A.decode_assigned, "SubsystemAnalysis", "name", [], {}, view=len)
    for label, results in (("empty_results", {}), ("one_missing", {PATH: None}), ("foreign_key", {PATH: None, OTHER: None, "foreign": None}),
                           ("a_list", []), ("none", None), ("a_list_body", {PATH: [], OTHER: None}), ("a_string_body", {PATH: "semantic", OTHER: None}),
                           ("a_body_carrying_its_identity", {PATH: {**body(), "path": OTHER}, OTHER: None}),
                           ("a_body_carrying_the_same_identity", {PATH: {**body(), "path": PATH}, OTHER: None}),
                           ("an_unknown_disposition", {PATH: body("partial"), OTHER: None}),
                           ("a_missing_field", {PATH: {k: v for k, v in body().items() if k != "method"}, OTHER: None}),
                           ("a_string_for_a_list", {PATH: body(symbols="symbol"), OTHER: None}),
                           ("repeated_rows_as_a_list", [{**body(), "path": PATH}, {**body("unreviewed"), "path": PATH}])):
        out["decode_refuses_" + label] = outcome(A.decode_assigned, "PathDisposition", "path", [PATH, OTHER], results, view=names)
    out["decode_duplicate_assigned_identity"] = outcome(A.decode_assigned, "PathDisposition", "path", [PATH, PATH], {PATH: None})
    out["decode_unknown_kind"] = outcome(A.decode_assigned, "Nope", "path", [PATH], {PATH: body()})

    # refused_execution, evidence_ref, analysis_binding
    out["refused_execution"] = {"envelope": A.refused_execution({"inspection_blocked": True}), "false_flag": A.refused_execution({"inspection_blocked": False}),
                                "absent": A.refused_execution({}), "not_a_dict": A.refused_execution("blocked"), "none": A.refused_execution(None),
                                "truthy_text": A.refused_execution({"inspection_blocked": "yes"})}
    out["evidence_ref"] = {"valid": A.evidence_ref({"execution_ref": ref}), "empty": A.evidence_ref({"execution_ref": ""}),
                           "non_string": A.evidence_ref({"execution_ref": 7}), "absent": A.evidence_ref({})}
    trusted = SimpleNamespace(audit_id="a-1", partition_id="p-1", generation=3)
    task = {"id": "t-1", "generation": 2, "attempt": 1}
    out["analysis_binding"] = A.analysis_binding(task, trusted, "analysis_checkpointed", ref, checkpoint_generation=4, checkpointed=True)
    out["analysis_binding_without_facts"] = A.analysis_binding(task, trusted, "analysis_rejected", None)
    return out


def b6_proposed_checkpoint(api, ws):
    """`proposed_checkpoint` over a real trusted partition (output_identity tests 8-10 at the pure boundary)."""
    out = {}
    env = build(api, ws, "proposed-checkpoint")
    A = api.module.AuditExecution
    partitions = env.service.partition(env.record["id"], 2)
    part = next(p for p in partitions if len(p["paths"]) > 1)
    sub = next(p for p in partitions if p["subsystems"])
    trusted, sub_trusted = api.PartitionCheckpoint(**part), api.PartitionCheckpoint(**sub)
    ref = answer_ref(env, "one traced path")
    first = part["paths"][0]

    def view(result):
        checkpoint, paths, systems = result
        return {"remaining_paths": len(checkpoint.remaining_paths), "remaining_subsystems": checkpoint.remaining_subsystems,
                "open_questions": checkpoint.open_questions, "cursor": checkpoint.cursor, "generation": checkpoint.generation,
                "paths": [(p.path == first, p.disposition) for p in paths], "systems": [s.name for s in systems]}
    cases = {
        "all_null": answer_for(part),
        "one_record": answer_for(part, {first: path_body(env, first, ref)}, open_questions=["q"], cursor="1"),
        "an_unreviewed_record_is_not_covered": answer_for(part, {first: path_body(env, first, ref, "unreviewed")}),
        "an_unavailable_record_is_not_covered": answer_for(part, {first: path_body(env, first, ref, "unavailable")}),
        "every_path_covered": answer_for(part, {p: path_body(env, p, ref) for p in part["paths"]}),
        "invalid_cursor": answer_for(part, cursor=""),
        "cursor_not_a_string": answer_for(part, cursor=7),
        "questions_not_a_list": answer_for(part, open_questions="q"),
        "an_empty_question": answer_for(part, open_questions=[""]),
        "a_non_string_question": answer_for(part, open_questions=[7]),
        "missing_cursor": {k: v for k, v in answer_for(part).items() if k != "cursor"},
        "missing_questions": {k: v for k, v in answer_for(part).items() if k != "open_questions"},
        "missing_paths_field": {k: v for k, v in answer_for(part).items() if k != "paths"},
        "a_generated_record_without_a_link": answer_for(part, {first: path_body(env, first, ref, "generated", links=[])}),
    }
    for name, answer in cases.items():
        out[name] = C.outcome(api, A.proposed_checkpoint, trusted, answer, view=view)
    sub_ref = answer_ref(env, "subsystem trace")
    s_cases = {
        "a_subsystem_with_tests_not_run_is_not_covered": answer_for(sub, subsystems={sub["subsystems"][0]: subsystem_body(env, sub_ref)}),
        "a_fully_traced_subsystem_is_covered": answer_for(sub, subsystems={sub["subsystems"][0]: subsystem_body(env, sub_ref, tests=[json.dumps(["fixture-inspection"])], tests_not_run=[])}),
        "a_subsystem_missing_its_trace": answer_for(sub, subsystems={sub["subsystems"][0]: subsystem_body(env, sub_ref, contracts=[])}),
    }
    for name, answer in s_cases.items():
        out[name] = C.outcome(api, A.proposed_checkpoint, sub_trusted, answer, view=view)
    out["the_trusted_partition_is_not_mutated"] = {"paths": len(trusted.remaining_paths) == len(part["remaining_paths"]),
                                                   "same_cursor": trusted.cursor == part["cursor"]}
    return out


# ---- coverage ----------------------------------------------------------------------------------------------------------------
B1, B2, B3, B4, B5, B6 = ("b1_discovery.", "b2_acquire.", "b3_propose.", "b4_partition.", "b5_review.", "b6_static.")
PC = "b6_proposed_checkpoint."
IDENTITY, OUTCOMES, AUDITS = "tests/test_audit_output_identity.py", "tests/test_audit_analysis_outcomes.py", "tests/test_research_audits.py"


def at(prefix, *names):
    return [prefix + n for n in names]


M7_TESTS = {   # test node -> the golden cases that mirror it, or why it is not in the golden
    IDENTITY + "::test_assigned_schema_binds_one_nullable_body_per_identity": at(
        B6, "partition_schema_paths_only", "partition_schema_subsystems_only", "partition_schema_empty"),
    IDENTITY + "::test_empty_assignment_is_an_empty_object": at(B6, "partition_schema_empty"),
    IDENTITY + "::test_assigned_bodies_keep_the_domain_vocabulary_and_conditional_rules": at(B6, "partition_schema_both_assigned_defs", "output_definitions"),
    IDENTITY + "::test_the_old_schema_accepts_two_rows_for_one_identity_and_the_new_shape_cannot": at(B6, "decode_refuses_repeated_rows_as_a_list"),
    IDENTITY + "::test_malformed_assigned_results_are_refused_never_normalized": at(
        B6, "decode_refuses_empty_results", "decode_refuses_one_missing", "decode_refuses_foreign_key", "decode_refuses_a_list", "decode_refuses_none",
        "decode_refuses_a_list_body", "decode_refuses_a_string_body"),
    IDENTITY + "::test_a_body_may_not_carry_its_own_identity_or_a_malformed_field": at(
        B6, "decode_refuses_a_body_carrying_its_identity", "decode_refuses_a_body_carrying_the_same_identity", "decode_refuses_an_unknown_disposition",
        "decode_refuses_a_missing_field", "decode_refuses_a_string_for_a_list"),
    IDENTITY + "::test_decoding_injects_the_trusted_key_and_omits_nulls": at(B6, "decode_injects_the_trusted_key_and_omits_nulls", "decode_empty_subsystems"),
    IDENTITY + "::test_one_partial_record_with_nulls_preserves_the_remaining_scope": at(B4, "one_record_checkpoints_and_binds_partial_progress"),
    IDENTITY + "::test_all_null_results_advance_the_generation_without_any_coverage": at(B4, "all_null_advances_the_generation_without_coverage"),
    IDENTITY + "::test_invalid_assigned_output_is_retained_and_never_reaches_the_checkpoint": at(
        B4, "refused_draft_legacy_array", "refused_draft_foreign_key", "refused_draft_missing_key", "refused_draft_inner_identity"),
    IDENTITY + "::test_the_checkpoint_duplicate_guard_is_still_authoritative": {"other family": "research.audit_core (ResearchAudits.checkpoint, valid_owner_duplicate_paths)"},
    OUTCOMES + "::test_valid_content_checkpoints_and_binds_partial_progress": at(
        B4, "all_null_advances_the_generation_without_coverage", "one_record_checkpoints_and_binds_partial_progress"),
    OUTCOMES + "::test_an_answer_without_executor_evidence_checkpoints_and_stays_unclassified": at(
        B4, "an_answer_without_executor_evidence_checkpoints_and_stays_unclassified"),
    OUTCOMES + "::test_a_refused_draft_is_retained_without_checkpoint_coverage_or_history": at(
        B4, "refused_draft_generated_without_link", "refused_draft_missing_subsystem_trace", "refused_draft_malformed_shape", "refused_draft_invalid_cursor",
        "refused_draft_invalid_questions"),
    OUTCOMES + "::test_no_raw_text_from_a_refused_draft_reaches_the_retained_result": at(B4, "no_raw_text_from_a_refused_draft_reaches_the_result"),
    OUTCOMES + "::test_missing_or_unreadable_rejection_evidence_stays_a_failure": at(
        B4, "rejection_evidence_absent_stays_a_failure", "rejection_evidence_unknown_artifact_stays_a_failure", "rejection_evidence_modified_artifact_stays_a_failure"),
    OUTCOMES + "::test_failures_outside_the_content_boundary_are_never_converted": at(
        B4, "a_model_failure_is_not_converted", "a_runner_failure_is_not_converted", "an_ordinary_checkpoint_refusal_is_not_converted",
        "the_trusted_assignment_failure_trusted_partition", "the_trusted_assignment_failure_stale_assignment"),
    OUTCOMES + "::test_a_returned_inspection_refusal_is_never_a_rejected_draft": at(
        B4, "a_returned_inspection_refusal_planning", "a_returned_inspection_refusal_semantic", "a_returned_inspection_refusal_semantic_carrying_content"),
    OUTCOMES + "::test_a_rejected_partition_is_followed_by_a_valid_one_in_one_serial_run": {"not in the golden": "needs the real service executor and PostgreSQL (`connected`)"},
    OUTCOMES + "::test_status_counts_the_outcomes_and_lists_the_held_partition": {"not in the golden": "needs the real service executor and PostgreSQL (`connected`)"},
    OUTCOMES + "::test_a_repeated_tick_and_a_restart_never_rerun_the_held_generation": {"not in the golden": "needs the real service executor and PostgreSQL (`connected`)"},
    OUTCOMES + "::test_an_execution_failure_still_stops_the_service": {"not in the golden": "needs the real service executor and PostgreSQL (`connected`)"},
    OUTCOMES + "::test_a_returned_inspection_refusal_stops_the_service_after_one_task": {"not in the golden": "needs the real service executor and PostgreSQL (`connected`)"},
    AUDITS + "::test_schema_preflight_failure_cannot_create_audit_success": {"not in the golden": "drives a real AppServer (`server.request`) and its output-schema preflight, not this adapter's own logic"},
    AUDITS + "::test_affected_records_still_validate_and_parse": at(B6, "typed_schema_AdaptationProposal", "typed_schema_IndependentReview"),
    AUDITS + "::test_execution_scopes_output_and_checkpoints_partial_progress": at(B4, "one_record_checkpoints_and_binds_partial_progress", "a_subsystem_partition_checkpoints_partial_progress") + at(B6, "partition_schema_both"),
}


def resolve(result, path):
    node = result
    for part in path.split("."):
        node = node[part]   # a pointer that does not resolve is a driver error, never a silent gap
    return node


def pointers(entry):
    return entry if isinstance(entry, list) else []


def coverage(result) -> dict:
    for entry in M7_TESTS.values():
        for pointer in pointers(entry):
            resolve(result, pointer)
    mirrored = sorted(name for name, entry in M7_TESTS.items() if pointers(entry))
    left_out = {name: entry for name, entry in M7_TESTS.items() if isinstance(entry, dict)}
    return {"m7_tests": M7_TESTS, "mirrored": mirrored, "left_out": left_out,
            "counts": {"m7_test_functions": len(M7_TESTS), "mirrored": len(mirrored), "left_out": len(left_out)}}


GROUPS = (("b1_discovery", b1_discovery), ("b2_acquire", b2_acquire), ("b3_propose", b3_propose), ("b4_partition", b4_partition),
          ("b5_review", b5_review), ("b6_static", b6_static), ("b6_proposed_checkpoint", b6_proposed_checkpoint))


def run(api) -> dict:
    ws = R.Workspace()
    try:
        result, counts_ = {}, {}
        for name, group in GROUPS:
            result[name] = ws.scrub(group(api, ws))
            counts_[name] = len(result[name])
        result["cases_per_group"] = counts_
        result["coverage"] = coverage(result)
        return result
    finally:
        ws.close()
