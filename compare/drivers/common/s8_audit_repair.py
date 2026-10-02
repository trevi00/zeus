"""Shared S8 scenario steps (`research.audit_repair`): M7 `application/audit_repair.py` (`AuditRepair`: `enable`, `disable`, `inspect`,
`_candidates`, `_diagnose`, `admit`, `_commit`, `_control`, `settle`, `_notify`, `_pending_notice`, `tick`, `status`; `repair_view`),
characterized BEFORE the module moves (DESIGN-s8 §2 row `research.audits`, the repair owner, and §13 V18 R-ar1..R-ar4). The golden is
placement-neutral: it observes SOURCE behaviour only; the move is the NEXT commit of the same pilot.

Each case is labelled with the M7 `tests/test_audit_repair.py` test it mirrors (`m7_test`), or `none` (a branch of the module no M7
test names, labelled where it is made).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a
target) driver builds. LABELLED doubles and plantings (nothing here is an actual Codex, Git, Docker, model or production verification):
- the store is a `MemoryStore`; its rows are PLANTED, LABELLED synthetic records in the shape their owners write (M7's helpers run
  `ResearchAudits.checkpoint`, `schedule_audits` and an `AnalysisExecutor` to obtain them; those are other families and need the
  service executor): the audit, the partition, the settled rejected `tasks` row, the original assignment's `outbox` and `schedule`
  rows, the `research_control/activation` row, a successor's settled `tasks` row, its `outbox` publication and its
  `research_evidence_history` rows;
- the artifacts are `Artifacts`, the `AuditArtifacts` port (`inspect`, `document`) over scripted documents, with scripted faults;
- the replay is `Replay`, a scripted function identical on both sides: it returns the refusal M7's recorded rejection carries (the
  `ContractError` type and the digest of `Missing subsystem trace: tests`), or a mismatch or an exception where M7's test uses one;
  the M7 adapter `replay_decode` (an unmoved execution-context adapter) never runs;
- the organization is the packaged one (`api.organization()`); the clock and id source are the harness's, advanced one millisecond
  after every step.
The store digests (whole store, 16 hex) are recorded before and after every call, with a `wrote` flag: a refusal and a
not-admitted result write nothing.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from types import SimpleNamespace

SECRET = "password=hunter2-repair-canary-41ab"
AUDIT = "audit-fixture-001"
PARTITION = "partition-fixture-001"
OPERATOR = "owner-fixture"
PATHS = ["cGF0aC0w", "cGF0aC0x"]
PARTITION_KEY = "audit-partition-key-0"
VALIDATOR = "Missing subsystem trace: tests"


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_digest(store) -> str:
    with store.transaction() as tx:
        return canonical_digest([[r["bucket"], r["id"], canonical_digest(r["body"])] for r in tx.records()])[:16]


# ---- labelled doubles --------------------------------------------------------------------------------------------------------
class Artifacts:
    """LABELLED. The `AuditArtifacts` port (M7 `FileArtifacts.inspect`/`document`) over scripted documents: `add` stores a document under
    the reference its canonical bytes hash to, `faults` maps a reference to the exception `inspect` raises (a missing file, a modified
    one), `calls` records the references read."""

    def __init__(self, api):
        self.api, self.docs, self.faults, self.calls = api, {}, {}, []

    def add(self, document) -> str:
        ref = "sha256:" + hashlib.sha256(self.api.canonical(document).encode()).hexdigest()
        self.docs[ref] = document
        return ref

    def inspect(self, reference):
        self.calls.append(reference)
        if reference in self.faults:
            raise self.faults[reference]
        if reference not in self.docs:
            raise FileNotFoundError(reference)
        return {"ref": reference}

    def document(self, reference):
        if reference not in self.docs:
            raise FileNotFoundError(reference)
        return self.docs[reference]


class Replay:
    """LABELLED. The injected pure content decode (M7 `adapters.audit_repair.replay_decode`, an unmoved adapter): returns `result` (the
    refusal M7's recorded rejection carries, by default), or raises `raises`; `hook` runs inside the call (M7's `moving_replay` and
    `pausing_replay` change the store while the evidence is read). `calls` records what it was given."""

    def __init__(self, result, raises=None, hook=None):
        self.result, self.raises, self.hook, self.calls = result, raises, hook, []

    def __call__(self, partition, answer):
        self.calls.append({"partition_id": partition["partition_id"], "generation": partition["generation"],
                           "subsystems": sorted((answer.get("subsystems") or {}))})
        if self.hook is not None:
            self.hook(partition)
        if self.raises is not None:
            raise self.raises
        return dict(self.result)


class BlindTransaction:
    """LABELLED. M7 `BlindTransaction` (INJECTED FAULT): ONE bucket's `get` (or `scan`) fails; every other read is the real store's."""

    def __init__(self, tx, bucket, op):
        self._tx, self._bucket, self._op = tx, bucket, op

    def __getattr__(self, name):
        return getattr(self._tx, name)

    def get(self, bucket, key):
        if self._op == "get" and bucket == self._bucket:
            raise RuntimeError("injected control read failure")
        return self._tx.get(bucket, key)

    def scan(self, bucket):
        if self._op == "scan" and bucket == self._bucket:
            raise RuntimeError("injected control read failure")
        return self._tx.scan(bucket)


class BlindStore:
    """LABELLED. M7 `BlindStore`: wraps the real store; `op` is the failing read (`get` or `scan`)."""

    def __init__(self, store, bucket, op="get"):
        self.store, self.bucket, self.op = store, bucket, op

    @contextlib.contextmanager
    def transaction(self):
        with self.store.transaction() as tx:
            yield BlindTransaction(tx, self.bucket, self.op)


# ---- the world ---------------------------------------------------------------------------------------------------------------
def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def delete(store, bucket, key):
    with store.transaction() as tx:
        tx.data.pop((bucket, key), None)  # M7 `del tx.data[...]`: the store has no delete


def reproducing(api):
    return {"refused": True, "error_type": "ContractError", "error_digest": api.digest(VALIDATOR)}


def build(api, *, subsystems=("core",), flagged=None, partition=True, replay=None):
    """The world one case runs in (M7 `repairable` / `two_targets` and `rejected_execution`, planted): an audit, ONE subsystem
    partition (generation 0), an active research control row, the original assignment (outbox, published, and schedule rows) and
    its settled rejected execution whose retained draft carries `flagged` subsystem records with empty `tests`/`tests_not_run`
    (every other assigned identity is null: unanalyzed work)."""
    flagged = list(subsystems[:1] if flagged is None else flagged)
    store = api.MemoryStore()
    artifacts = Artifacts(api)
    env = SimpleNamespace(api=api, store=store, org=api.organization(), artifacts=artifacts, audit_id=AUDIT, partition_id=PARTITION,
                          subsystems=list(subsystems), flagged=flagged, replay=Replay(reproducing(api)) if replay is None else replay)
    put(store, "research_audits", AUDIT, {"id": AUDIT, "status": "imported", "subsystems": list(subsystems)})
    put(store, "research_control", "activation", {"status": "active", "release_id": "rel-1", "revision": "audit"})
    if partition:
        put(store, "research_partitions", PARTITION,
            {"partition_id": PARTITION, "audit_id": AUDIT, "generation": 0, "paths": list(PATHS), "subsystems": list(subsystems),
             "remaining_paths": [], "remaining_subsystems": list(subsystems), "open_questions": []})
    answer = {"subsystems": {name: ({"name": name, "tests": [], "tests_not_run": []} if name in flagged else None) for name in subsystems},
              "paths": {}}
    env.answer = answer
    env.ref = artifacts.add({"answer": answer, "transport": "fixture", "model_answer_text": "the refused draft with " + SECRET})
    message = api.envelope("task.assign", "lead:research", "worker:github", "audit_partition",
                           {"audit_id": AUDIT, "partition_id": PARTITION, "generation": 0}, PARTITION_KEY)
    env.message, env.task_id = message, message["message_id"]
    now = message["when"]["created_at"]
    put(store, "outbox", message["message_id"], {"message": message, "sent": True})
    put(store, "schedule", PARTITION_KEY, {"id": PARTITION_KEY, "task_id": message["message_id"], "partition_id": PARTITION, "at": now})
    env.task = {"id": message["message_id"], "status": "succeeded", "generation": 0, "attempt": 1, "agent": "worker:github",
                "message": message, "created_at": now, "completed_at": now,
                "result": {"analysis": {"outcome": api.ANALYSIS_REJECTED, "reason_code": api.ANALYSIS_CONTENT_REJECTED,
                                        "execution_ref": env.ref, "partition_generation": 0, "error_type": "ContractError",
                                        "error_digest": api.digest(VALIDATOR)}}}
    put(store, "tasks", env.task_id, env.task)
    return env


def repair(env, replay=None, store=None):
    """A fresh `AuditRepair` over the world (a restarted service or a concurrent caller is another call of this)."""
    return env.api.audit_repair(store if store is not None else env.store, env.org, env.artifacts,
                                replay=env.replay if replay is None else replay)


def enabled(env, replay=None):
    owner = repair(env, replay)
    owner.enable(env.audit_id, env.task_id, operator=OPERATOR)
    env.api.advance(0.001)
    return owner


def outcome(fn, *args, **kwargs):
    """The characterized outcome of one call: its value, or the refusal (type, fixed reason code, text)."""
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        out = {"refused": type(exc).__name__, "message": str(exc)[:200]}
        if hasattr(exc, "reason_code"):
            out["reason_code"] = exc.reason_code
        return out
    return {"value": value}


def step(env, fn, *args, **kwargs):
    """One call with the whole-store digest before and after and a `wrote` flag, then one tick of the fake clock."""
    before = store_digest(env.store)
    out = outcome(fn, *args, **kwargs)
    after = store_digest(env.store)
    env.api.advance(0.001)
    return {**out, "store_before": before, "store_after": after, "wrote": before != after}


def admitted_state(env):
    """What an admission leaves (M7 `corrections_of`, the `repair:` schedule rows, the `repair:` outbox records, the events)."""
    return {"corrections": [r["id"] for r in scan(env.store, "audit_repair_corrections")],
            "schedule": [r["id"] for r in scan(env.store, "schedule") if r["id"].startswith("repair:")],
            "outbox": [r["message"]["correlation_id"] for r in scan(env.store, "outbox")
                       if r["message"]["correlation_id"].startswith("repair:")],
            "events": [r["type"] for r in scan(env.store, "events")]}


def nothing_was_queued(env):
    """M7 `nothing_was_queued`."""
    state = admitted_state(env)
    return not (state["corrections"] or state["schedule"] or state["outbox"])


def successor_message(env, correction_id):
    key = env.api.schedule_key(correction_id)
    return next(r["message"] for r in scan(env.store, "outbox") if r["message"]["correlation_id"] == key)


def publish(env, correlation):
    """M7 `publish_outbox`: the correlation-scoped relay marks that correlation's own records sent."""
    for row in scan(env.store, "outbox"):
        if not row["sent"] and row["message"]["correlation_id"] == correlation:
            put(env.store, "outbox", row["message"]["message_id"], {**row, "sent": True})


def history_row(env, task_id, name, *, generation=1):
    record = {"name": name, "tests": [], "tests_not_run": [{"test": "t", "reason": "r", "follow_up": "f"}]}
    put(env.store, "research_evidence_history", "history-%s-%s" % (task_id[-6:], name),
        {"audit_id": env.audit_id, "task_id": task_id, "generation": generation, "record": record})


def plant_successor(env, admitted, *, status="succeeded", outcome_name=None, corrected=(), bump=True, agent="worker:github",
                    correlation=None):
    """LABELLED. The successor the existing Workflow would settle: its `tasks` row (the admitted assignment, executed), the analysis
    marker the checkpoint or the rejection boundary leaves, the publication of its outbox record, the immutable evidence-history rows of
    the `corrected` subsystems and (for a checkpoint) the partition's next generation. M7 runs `AnalysisExecutor` for these."""
    api = env.api
    message = successor_message(env, admitted["correction_id"])
    ref = env.artifacts.add({"answer": {"subsystems": {}}, "transport": "fixture", "model_answer_text": "the successor draft " + SECRET})
    outcome_name = outcome_name or api.ANALYSIS_CHECKPOINTED
    result = None
    if status == "succeeded":
        analysis = {"outcome": outcome_name, "execution_ref": ref, "partition_generation": 1 if bump else 0}
        if outcome_name == api.ANALYSIS_REJECTED:
            analysis.update(reason_code=api.ANALYSIS_CONTENT_REJECTED, error_type="ContractError", error_digest=api.digest(VALIDATOR),
                            partition_generation=0)
        result = {"analysis": analysis}
    tid = message["message_id"]
    row = {"id": tid, "status": status, "generation": 0, "attempt": 1, "agent": agent,
           "message": {**message, "correlation_id": correlation or message["correlation_id"]}, "result": result,
           "created_at": message["when"]["created_at"], "completed_at": message["when"]["created_at"]}
    put(env.store, "tasks", tid, row)
    publish(env, message["correlation_id"])
    for name in corrected:
        history_row(env, tid, name)
    if status == "succeeded" and outcome_name == api.ANALYSIS_CHECKPOINTED and bump:
        part = get(env.store, "research_partitions", env.partition_id)
        put(env.store, "research_partitions", env.partition_id, {**part, "generation": 1})
    return {"task_id": tid, "ref": ref}


def secret_free(*values) -> bool:
    return SECRET not in json.dumps(values, sort_keys=True, default=str)


# ---- the cases ---------------------------------------------------------------------------------------------------------------
def case_inspection(api):
    """M7 `test_inspection_diagnoses_without_creating_anything`."""
    env = build(api)
    before = {b: scan(env.store, b) for b in ("tasks", "research_partitions", "outbox", "schedule")}
    report = step(env, repair(env).inspect, env.audit_id)
    one_task = step(env, repair(env).inspect, env.audit_id, env.task_id)
    absent_task = step(env, repair(env).inspect, env.audit_id, "absent-task")
    after = {b: scan(env.store, b) for b in before}
    return {"m7_test": "test_inspection_diagnoses_without_creating_anything", "inspect": report, "inspect_one_task": one_task,
            "inspect_absent_task": absent_task, "buckets_unchanged": before == after,
            "activation_row": get(env.store, "audit_repair_activation", env.audit_id), "state": admitted_state(env),
            "secret_free": secret_free(report), "replay_calls": env.replay.calls}


def case_unsupported_diagnosis(api):
    """M7 `test_another_refusal_shape_is_read_but_never_diagnosed` (the stored digest is that of another validator message)."""
    env = build(api)
    task = {**env.task, "result": {"analysis": {**env.task["result"]["analysis"], "error_digest": api.digest("Missing subsystem trace: contracts")}}}
    put(env.store, "tasks", env.task_id, task)
    owner = enabled(env)
    return {"m7_test": "test_another_refusal_shape_is_read_but_never_diagnosed",
            "admit": step(env, owner.admit, env.audit_id), "state": admitted_state(env), "replay_calls": env.replay.calls}


def case_not_a_candidate(api):
    """M7 `test_only_a_settled_rejected_execution_is_a_candidate` observed through `enable` and `inspect` (the M7 test calls the
    domain's `rejection_facts` directly: three tasks of the audit that are not a settled rejected execution)."""
    env = build(api)
    out = {"m7_test": "test_only_a_settled_rejected_execution_is_a_candidate"}
    for name, result, status in (("unclassified", {"generation": 1}, "succeeded"),
                                 ("checkpointed", {"analysis": {"outcome": api.ANALYSIS_CHECKPOINTED}}, "succeeded"),
                                 ("failed", None, "failed")):
        task_id = "task-not-a-candidate-" + name
        put(env.store, "tasks", task_id, {"id": task_id, "status": status, "generation": 0, "attempt": 1, "result": result,
                                           "message": {"what": {"action": "audit_partition",
                                                                "details": {"audit_id": AUDIT, "partition_id": PARTITION}}}})
        out["enable_" + name] = step(env, repair(env).enable, AUDIT, task_id, operator=OPERATOR)
    out["inspect"] = step(env, repair(env).inspect, AUDIT)
    return out


def case_one_admission(api):
    """M7 `test_one_admission_creates_exactly_one_ordinary_successor_and_rewrites_nothing`."""
    env = build(api)
    watched = ("tasks", "research_partitions", "research_paths", "research_subsystems", "research_checkpoints", "research_evidence_history")
    before = {b: scan(env.store, b) for b in watched}
    artifact_before = env.artifacts.document(env.ref)
    owner = enabled(env)
    admit = step(env, owner.admit, env.audit_id)
    value = admit.get("value") or {}
    out = {"m7_test": "test_one_admission_creates_exactly_one_ordinary_successor_and_rewrites_nothing", "admit": admit,
           "state": admitted_state(env)}
    if value.get("admitted"):
        correction_id = value["correction_id"]
        key = api.schedule_key(correction_id)
        message = successor_message(env, correction_id)
        correction = get(env.store, api.BUCKET_CORRECTIONS, correction_id)
        out.update(message=message, outbox_record=get(env.store, "outbox", message["message_id"]),
                   schedule=get(env.store, "schedule", key), event=get(env.store, "events", correction_id), correction=correction,
                   activation=get(env.store, api.BUCKET_ACTIVATION, env.audit_id),
                   sender_agent_action=[api.SENDER, api.AGENT, api.ACTION], key_is_repair_prefixed=key.startswith("repair:"),
                   secret_free=secret_free(message, correction))
    out["rewrote_nothing"] = {b: scan(env.store, b) == before[b] for b in watched}
    out["artifact_unchanged"] = env.artifacts.document(env.ref) == artifact_before
    out["original_task_unchanged"] = get(env.store, "tasks", env.task_id) == env.task
    return out


def case_one_lineage(api):
    """M7 `test_a_repeated_tick_a_restart_and_a_concurrent_caller_share_one_lineage`."""
    env = build(api)
    first = step(env, enabled(env).admit, env.audit_id)
    again = step(env, repair(env).admit, env.audit_id)
    third = step(env, repair(env).tick, env.audit_id)
    assignments = [r["message"]["correlation_id"] for r in scan(env.store, "outbox") if r["message"]["what"]["action"] == "audit_partition"]
    return {"m7_test": "test_a_repeated_tick_a_restart_and_a_concurrent_caller_share_one_lineage", "first": first, "again": again,
            "tick": third, "assignments": assignments, "state": admitted_state(env)}


def case_disabling(api):
    """M7 `test_disabling_prevents_new_admission_and_keeps_the_recorded_lineage`."""
    env = build(api)
    owner = repair(env)
    out = {"m7_test": "test_disabling_prevents_new_admission_and_keeps_the_recorded_lineage",
           "before_enable": step(env, owner.admit, env.audit_id), "state_before": admitted_state(env)}
    out["enable"] = step(env, owner.enable, env.audit_id, env.task_id, operator=OPERATOR)
    out["admit"] = step(env, owner.admit, env.audit_id)
    out["disable"] = step(env, owner.disable, env.audit_id, operator=OPERATOR)
    out["after_disable"] = step(env, owner.admit, env.audit_id)
    out["status"] = step(env, owner.status, env.audit_id)
    out["disable_unknown_audit"] = step(env, owner.disable, "absent-audit", operator=OPERATOR)
    out["disable_bad_operator"] = step(env, owner.disable, env.audit_id, operator="  ")
    out["repair_view"] = api.repair_view(get(env.store, api.BUCKET_ACTIVATION, env.audit_id), scan(env.store, api.BUCKET_CORRECTIONS))
    return out


def case_enable_refusals(api):
    """M7 `test_enabling_requires_an_existing_rejected_task_of_this_audit`, and (no M7 test) the rest of the enable refusals."""
    env = build(api)
    owner = repair(env)
    out = {"m7_test": "test_enabling_requires_an_existing_rejected_task_of_this_audit"}
    for name, audit_id, task_id, operator in (("unknown_audit", "absent-audit", env.task_id, OPERATOR),
                                              ("unknown_task", AUDIT, "absent-task", OPERATOR),
                                              ("task_id_invalid", AUDIT, "   ", OPERATOR),
                                              ("audit_id_invalid", "", env.task_id, OPERATOR),
                                              ("operator_invalid", AUDIT, env.task_id, "  "),
                                              ("operator_not_text", AUDIT, env.task_id, None)):
        out[name] = step(env, owner.enable, audit_id, task_id, operator=operator)
    other = {**env.task, "id": "task-other-audit",
             "message": {**env.task["message"], "what": {"action": "audit_partition",
                                                         "details": {"audit_id": "another-audit", "partition_id": PARTITION}}}}
    put(env.store, "tasks", "task-other-audit", other)
    out["task_of_another_audit"] = step(env, owner.enable, AUDIT, "task-other-audit", operator=OPERATOR)
    return out


def case_out_of_scope(api):
    """M7 `test_an_out_of_scope_rejection_is_never_admitted`; and (no M7 test) an enabled audit with an empty scope."""
    env = build(api)
    owner = repair(env)
    put(env.store, api.BUCKET_ACTIVATION, AUDIT, {"id": AUDIT, "audit_id": AUDIT, "status": "enabled", "task_ids": ["other-task"],
                                                  "operator": OPERATOR, "created_at": "t", "updated_at": "t"})
    out = {"m7_test": "test_an_out_of_scope_rejection_is_never_admitted", "admit": step(env, owner.admit, AUDIT),
           "state": admitted_state(env), "task_status": env.task["status"]}
    put(env.store, api.BUCKET_ACTIVATION, AUDIT, {"id": AUDIT, "audit_id": AUDIT, "status": "enabled", "task_ids": [],
                                                  "operator": OPERATOR, "created_at": "t", "updated_at": "t"})
    out["empty_scope_no_m7_test"] = step(env, owner.admit, AUDIT)
    return out


def case_corrupt_moved_unpublished(api):
    """M7 `test_corrupt_moved_or_unpublished_evidence_admits_nothing` (seven parameters), and (no M7 test) the schedule row of the
    lineage's own key already present."""
    out = {"m7_test": "test_corrupt_moved_or_unpublished_evidence_admits_nothing"}
    for name in ("generation", "partition", "foreign", "evidence", "modified", "document", "unpublished", "schedule_row_present"):
        env = build(api, partition=(name != "partition"))
        owner = enabled(env)
        if name == "generation":
            part = get(env.store, "research_partitions", PARTITION)
            put(env.store, "research_partitions", PARTITION, {**part, "generation": 1})
        if name == "foreign":
            part = get(env.store, "research_partitions", PARTITION)
            put(env.store, "research_partitions", PARTITION, {**part, "audit_id": "another-audit"})
        if name == "unpublished":
            message = api.envelope("task.assign", "lead:research", "worker:github", "audit_partition",
                                   {"audit_id": AUDIT, "partition_id": PARTITION, "generation": 0}, PARTITION_KEY)
            put(env.store, "outbox", message["message_id"], {"message": message, "sent": False})
        if name == "document":
            # a readable artifact that is NOT the execution result this rejection recorded
            other = env.artifacts.add({"no_answer": True})
            row = get(env.store, "tasks", env.task_id)
            row["result"]["analysis"]["execution_ref"] = other
            put(env.store, "tasks", env.task_id, row)
        if name == "evidence":
            env.artifacts.docs.pop(env.ref)
        if name == "modified":
            env.artifacts.faults[env.ref] = api.ContractError("artifact bytes do not match their reference")
        if name == "schedule_row_present":
            # LABELLED: the deterministic key of the lineage a first admission would write is already scheduled
            facts = api.rejection_facts(get(env.store, "tasks", env.task_id))
            key = api.schedule_key(api.correction_identity(api.family_identity(facts, api.MISSING_TEST_DISPOSITION)))
            put(env.store, "schedule", key, {"id": key, "task_id": "x", "partition_id": PARTITION, "at": "t"})
        out[name] = {"admit": step(env, owner.admit, AUDIT), "state": admitted_state(env), "replay_calls": env.replay.calls,
                     "artifact_reads": len(env.artifacts.calls)}
    return out


def case_replay_unknown(api):
    """M7 `test_an_unavailable_or_disagreeing_replay_is_unknown_not_permission`, and (no M7 test) a replay that reproduces the digest
    with another error type, and a draft with no correctable identity."""
    env = build(api)
    out = {"m7_test": "test_an_unavailable_or_disagreeing_replay_is_unknown_not_permission"}
    enabled(env)
    absent = repair(env)
    absent.replay = None
    out["replay_absent"] = step(env, absent.admit, AUDIT)
    out["replay_raises"] = step(env, repair(env, Replay(None, raises=RuntimeError("replay unavailable"))).admit, AUDIT)
    out["replay_not_refused"] = step(env, repair(env, Replay({"refused": False, "error_type": None, "error_digest": None})).admit, AUDIT)
    out["replay_other_digest"] = step(env, repair(env, Replay({"refused": True, "error_type": "ContractError", "error_digest": "0" * 64})).admit, AUDIT)
    out["replay_other_type"] = step(env, repair(env, Replay({"refused": True, "error_type": "ValueError", "error_digest": api.digest(VALIDATOR)})).admit, AUDIT)
    out["state"] = admitted_state(env)
    justified = build(api)
    justified.answer["subsystems"]["core"] = {"name": "core", "tests": ["[\"pytest\"]"], "tests_not_run": []}
    justified.artifacts.docs[justified.ref] = {"answer": justified.answer}
    out["no_correctable_identity"] = {"admit": step(justified, enabled(justified).admit, AUDIT), "state": admitted_state(justified)}
    return out


def case_state_change(api):
    """M7 `test_a_state_change_between_the_diagnosis_and_the_commit_admits_nothing` (the scope moves while the evidence is read), and
    (no M7 test) the task row, or the opt-in, changing while the evidence is read."""
    env = build(api)

    def moving(partition):
        row = get(env.store, "research_partitions", partition["partition_id"])
        put(env.store, "research_partitions", row["partition_id"], {**row, "generation": row["generation"] + 1})

    env.replay = Replay(reproducing(api), hook=moving)
    out = {"m7_test": "test_a_state_change_between_the_diagnosis_and_the_commit_admits_nothing"}
    out["admit"] = step(env, enabled(env).admit, AUDIT)
    out["state"] = admitted_state(env)
    out["replay_calls"] = env.replay.calls
    env2 = build(api)

    def retried(partition):
        row = get(env2.store, "tasks", env2.task_id)
        put(env2.store, "tasks", env2.task_id, {**row, "attempt": 2})

    env2.replay = Replay(reproducing(api), hook=retried)
    out["task_changed"] = {"admit": step(env2, enabled(env2).admit, AUDIT), "state": admitted_state(env2)}
    env3 = build(api)

    def closing(partition):
        repair(env3).disable(AUDIT, operator=OPERATOR)

    env3.replay = Replay(reproducing(api), hook=closing)
    out["disabled_meanwhile"] = {"admit": step(env3, enabled(env3).admit, AUDIT), "state": admitted_state(env3)}
    return out


def case_pause(api):
    """M7 `test_a_pause_observed_while_the_evidence_is_read_queues_no_successor`, and (no M7 test) a control row that is absent or
    not an object."""
    env = build(api)

    def pausing(partition):
        control = get(env.store, "research_control", "activation")
        put(env.store, "research_control", "activation", {**control, "status": "paused"})

    env.replay = Replay(reproducing(api), hook=pausing)
    admit = step(env, enabled(env).admit, AUDIT)
    out = {"m7_test": "test_a_pause_observed_while_the_evidence_is_read_queues_no_successor", "admit": admit,
           "nothing_was_queued": nothing_was_queued(env), "state": admitted_state(env)}
    for name, body in (("control_absent", None), ("control_not_object", "paused")):
        other = build(api)
        delete(other.store, "research_control", "activation")
        if body is not None:
            put(other.store, "research_control", "activation", body)
        out[name] = {"admit": step(other, enabled(other).admit, AUDIT), "nothing_was_queued": nothing_was_queued(other)}
    return out


def case_termination_markers(api):
    """M7 `test_an_unresolved_termination_marker_of_the_source_execution_admits_nothing` (both markers), and (no M7 test) a marker
    of another bucket."""
    out = {"m7_test": "test_an_unresolved_termination_marker_of_the_source_execution_admits_nothing"}
    for marker in ("unconfirmed", "pending_reconciliation"):
        env = build(api)
        owner = enabled(env)
        record = {"id": "termination-" + marker, "task_id": env.task_id, "bucket": "tasks", "status": marker, "reservation_id": "fixture"}
        put(env.store, "observation_terminations", record["id"], record)
        blocked = step(env, owner.admit, AUDIT)
        queued = nothing_was_queued(env)
        put(env.store, "observation_terminations", record["id"], {**record, "status": "resolved"})
        put(env.store, "observation_terminations", "other", {**record, "id": "other", "task_id": "another-task"})
        put(env.store, "observation_terminations", "other-bucket", {**record, "id": "other-bucket", "bucket": "decisions_pending"})
        out[marker] = {"blocked": blocked, "nothing_was_queued": queued, "after_resolved_and_other": step(env, owner.admit, AUDIT),
                       "state": admitted_state(env)}
    return out


def case_unreadable_control(api):
    """M7 `test_an_unreadable_control_row_is_unknown_and_never_permission` (INJECTED FAULT: the control read fails), and (no M7 test)
    a failing termination scan."""
    env = build(api)
    owner = enabled(env)
    blind = repair(env, store=BlindStore(env.store, "research_control"))
    out = {"m7_test": "test_an_unreadable_control_row_is_unknown_and_never_permission", "blind": step(env, blind.admit, AUDIT),
           "nothing_was_queued": nothing_was_queued(env), "then_ordinary": step(env, owner.admit, AUDIT), "state": admitted_state(env)}
    env2 = build(api)
    enabled(env2)
    out["blind_terminations"] = {
        "admit": step(env2, repair(env2, store=BlindStore(env2.store, "observation_terminations", op="scan")).admit, AUDIT),
        "nothing_was_queued": nothing_was_queued(env2)}
    return out


def settle_of(env, owner):
    return step(env, owner.settle, env.audit_id)


def case_repaired(api):
    """M7 `test_a_justified_not_run_disposition_repairs_and_resumes_the_partition`."""
    env = build(api)
    owner = enabled(env)
    admitted = owner.admit(AUDIT)
    api.advance(0.001)
    successor = plant_successor(env, admitted, corrected=["core"])
    settle = settle_of(env, owner)
    partition = get(env.store, "research_partitions", PARTITION)
    status = step(env, owner.status, AUDIT)
    again = settle_of(env, owner)
    return {"m7_test": "test_a_justified_not_run_disposition_repairs_and_resumes_the_partition",
            "successor_is_the_admitted_one": successor["task_id"] == admitted["successor_task_id"],
            "settle": settle, "partition_generation": partition["generation"],
            "remaining_subsystems": partition["remaining_subsystems"],
            "original_analysis_outcome": get(env.store, "tasks", env.task_id)["result"]["analysis"]["outcome"],
            "status": status, "settle_again": again,
            "secret_free": secret_free(settle, status, get(env.store, api.BUCKET_CORRECTIONS, admitted["correction_id"]))}


def case_deferred_empty(api):
    """M7 `test_a_checkpoint_without_a_corrected_subsystem_is_deferred_not_repaired`."""
    env = build(api)
    owner = enabled(env)
    admitted = owner.admit(AUDIT)
    plant_successor(env, admitted, corrected=[])
    settle = settle_of(env, owner)
    return {"m7_test": "test_a_checkpoint_without_a_corrected_subsystem_is_deferred_not_repaired", "settle": settle,
            "status": step(env, owner.status, AUDIT)}


def two_target_case(api, diagnosed, corrected, test):
    env = build(api, subsystems=("core", "other"), flagged=diagnosed)
    owner = enabled(env)
    admitted = owner.admit(AUDIT)
    api.advance(0.001)
    plant_successor(env, admitted, corrected=corrected)
    settle = settle_of(env, owner)
    rows = {r["record"]["name"]: r["task_id"] == admitted["successor_task_id"] for r in scan(env.store, "research_evidence_history")}
    status = step(env, owner.status, AUDIT)
    partition = get(env.store, "research_partitions", PARTITION)
    return {"m7_test": test, "admitted_total": (admitted.get("correction") or {}).get("subsystems_total"), "settle": settle,
            "history_rows_of_successor": rows, "status": status, "partition_generation": partition["generation"],
            "remaining_subsystems": partition["remaining_subsystems"]}


def case_unrelated_corrected(api):
    """M7 `test_valid_work_outside_the_diagnosed_targets_is_deferred_not_a_repair` (core diagnosed; only `other` corrected)."""
    return two_target_case(api, ["core"], ["other"], "test_valid_work_outside_the_diagnosed_targets_is_deferred_not_a_repair")


def case_partially_corrected(api):
    """M7 `test_a_partially_corrected_target_set_is_deferred_with_target_and_remaining_counts`."""
    return two_target_case(api, ["core", "other"], ["core"], "test_a_partially_corrected_target_set_is_deferred_with_target_and_remaining_counts")


def case_all_corrected(api):
    """M7 `test_every_diagnosed_target_corrected_is_repaired_and_resumes_without_acceptance`."""
    return two_target_case(api, ["core", "other"], ["core", "other"], "test_every_diagnosed_target_corrected_is_repaired_and_resumes_without_acceptance")


def case_later_ordinary(api):
    """M7 `test_a_later_ordinary_checkpoint_neither_erases_nor_lends_a_corrected_target` and
    `test_an_uncorrected_target_is_not_credited_to_a_later_ordinary_execution` (the later ordinary execution is a planted
    `research_evidence_history` row of another task: the immutable history keeps both)."""
    out = {"m7_test": "test_a_later_ordinary_checkpoint_neither_erases_nor_lends_a_corrected_target; "
                      "test_an_uncorrected_target_is_not_credited_to_a_later_ordinary_execution"}
    for name, corrected in (("corrected_then_overwritten", ["core"]), ("uncorrected_later_credit", [])):
        env = build(api)
        owner = enabled(env)
        admitted = owner.admit(AUDIT)
        plant_successor(env, admitted, corrected=corrected)
        history_row(env, "ordinary-task-0000001", "core", generation=2)
        out[name] = {"settle": settle_of(env, owner),
                     "history_tasks": sorted(r["task_id"][-6:] for r in scan(env.store, "research_evidence_history"))}
    return out


def strike(env, successor_agent="worker:github"):
    """M7 `two_strikes`: the second content rejection of one lineage (the successor's settled row is planted)."""
    owner = enabled(env)
    admitted = owner.admit(AUDIT)
    env.api.advance(0.001)
    planted = plant_successor(env, admitted, outcome_name=env.api.ANALYSIS_REJECTED, agent=successor_agent, bump=False)
    return owner, admitted, planted


def case_second_refusal(api):
    """M7 `test_a_second_refused_draft_records_research_required_and_starts_no_third_call` and
    `test_a_second_rejection_atomically_records_one_proof_bound_lead_notice`."""
    env = build(api)
    owner, admitted, planted = strike(env)
    settle = settle_of(env, owner)
    row = get(env.store, api.BUCKET_CORRECTIONS, admitted["correction_id"])
    notices = scan(env.store, "execution_notices")
    notice = notices[0] if notices else None
    changed = (settle.get("value") or {}).get("changed") or [{}]
    return {"m7_test": "test_a_second_refused_draft_records_research_required_and_starts_no_third_call; "
                       "test_a_second_rejection_atomically_records_one_proof_bound_lead_notice",
            "settle": settle, "correction": row, "notices": notices,
            "notice_outbox_record": get(env.store, "outbox", notice["id"]) if notice else None,
            "notice_id_is_digest_of_transition": bool(notice) and notice["id"] == api.digest(notice["transition"]),
            "transition_ref_is_digest_of_proof": bool(notice) and notice["transition"]["transition_ref"] == api.digest(api.notice_proof(row, changed[0])),
            "evidence_refs_in_order": bool(notice) and notice["message"]["why"]["evidence_refs"] == [env.ref, planted["ref"]],
            "family_closed": step(env, owner.admit, AUDIT), "tick": step(env, repair(env).tick, AUDIT),
            "partition_tasks": len([t for t in scan(env.store, "tasks") if t["message"]["what"]["details"].get("partition_id") == PARTITION]),
            "partition_generation": get(env.store, "research_partitions", PARTITION)["generation"],
            "corrections": len(scan(env.store, api.BUCKET_CORRECTIONS)), "status": step(env, owner.status, AUDIT),
            "secret_free": secret_free(notices, settle, row)}


def case_repeated_notice(api):
    """M7 `test_a_repeated_settlement_or_restart_returns_the_same_notice_and_no_third_call`, with the publication state read from the
    notice's own outbox record (the relay of `test_a_failed_notice_publication_is_retried...` is the service's, not this module's)."""
    env = build(api)
    owner, admitted, _ = strike(env)
    first = settle_of(env, owner)
    notice_id = scan(env.store, "execution_notices")[0]["id"]
    again = settle_of(env, owner)
    restarted = step(env, repair(env).tick, AUDIT)
    out = {"m7_test": "test_a_repeated_settlement_or_restart_returns_the_same_notice_and_no_third_call (and the owner's own refresh of "
                      "the publication state that test_a_failed_notice_publication_is_retried_and_a_duplicate_receive_adds_no_execution reads)",
           "first": first, "again": again, "restarted": restarted, "notice_rows": len(scan(env.store, "execution_notices")),
           "notice_outbox_rows": len([r for r in scan(env.store, "outbox") if r["message"]["type"] == "execution.notice"]),
           "repair_schedule_rows": len([r for r in scan(env.store, "schedule") if r["id"].startswith("repair:")]),
           "status": step(env, owner.status, AUDIT)}
    record = get(env.store, "outbox", notice_id)
    put(env.store, "outbox", notice_id, {**record, "sent": True})
    out["published_refresh"] = settle_of(env, owner)
    out["published_status"] = step(env, owner.status, AUDIT)
    put(env.store, "outbox", notice_id, {**record, "sent": False})
    out["unpublished_again"] = settle_of(env, owner)
    delete(env.store, "outbox", notice_id)
    out["notice_record_missing"] = settle_of(env, owner)
    return out


def case_notice_quarantined(api):
    """No M7 test: `_notify` when the notice builder cannot turn the successor row into a notice (an unknown actor): the owner
    quarantines it and the lineage says so (`published` null, an `error_id`), claiming no delivery."""
    env = build(api)
    owner, admitted, _ = strike(env, successor_agent="worker:unknown")
    settle = settle_of(env, owner)
    row = get(env.store, api.BUCKET_CORRECTIONS, admitted["correction_id"])
    return {"m7_test": "none", "settle": settle, "notice": row["notice"], "notice_rows": len(scan(env.store, "execution_notices")),
            "errors": scan(env.store, "execution_notice_errors"), "events": [r["type"] for r in scan(env.store, "events")],
            "again": settle_of(env, owner), "tick": step(env, repair(env).tick, AUDIT)}


def case_failed_successor(api):
    """M7 `test_a_failed_successor_is_reconciliation_required_and_never_a_strike` (the Workflow's claim and fail is a planted
    `failed` `tasks` row)."""
    env = build(api)
    owner = enabled(env)
    admitted = owner.admit(AUDIT)
    plant_successor(env, admitted, status="failed")
    settle = settle_of(env, owner)
    return {"m7_test": "test_a_failed_successor_is_reconciliation_required_and_never_a_strike", "settle": settle,
            "family_closed": step(env, owner.admit, AUDIT), "notices": len(scan(env.store, "execution_notices"))}


def case_idempotent_settlement(api):
    """M7 `test_settlement_is_idempotent_and_a_live_successor_stays_admitted` (the Workflow's submit is a planted queued `tasks` row)."""
    env = build(api)
    owner = enabled(env)
    admitted = owner.admit(AUDIT)
    api.advance(0.001)
    out = {"m7_test": "test_settlement_is_idempotent_and_a_live_successor_stays_admitted"}
    out["pending"] = settle_of(env, owner)
    plant_successor(env, admitted, status="queued")
    out["queued"] = settle_of(env, owner)
    out["queued_again"] = settle_of(env, owner)
    plant_successor(env, admitted, corrected=["core"])
    out["repaired"] = settle_of(env, owner)
    out["twice"] = settle_of(env, owner)
    return out


def case_settlement_branches(api):
    """No M7 test (domain `settlement` branches through the owner): a successor row of another correlation is unbound; an analysis
    outcome the checkpoint vocabulary does not name is deferred as unclassified; a lineage-less audit and an unknown audit."""
    out = {"m7_test": "none"}
    env = build(api)
    owner = enabled(env)
    admitted = owner.admit(AUDIT)
    plant_successor(env, admitted, correlation="repair:another-lineage")
    out["unbound"] = settle_of(env, owner)
    env = build(api)
    owner = enabled(env)
    admitted = owner.admit(AUDIT)
    plant_successor(env, admitted, outcome_name="analysis_unclassified")
    out["unclassified"] = settle_of(env, owner)
    env = build(api)
    owner = enabled(env)
    out["settle_without_lineage"] = settle_of(env, owner)
    out["status_without_lineage"] = step(env, owner.status, AUDIT)
    out["status_unknown_audit"] = step(env, owner.status, "absent-audit")
    out["settle_unknown_audit"] = step(env, owner.settle, "absent-audit")
    return out


CASES = (case_inspection, case_unsupported_diagnosis, case_not_a_candidate, case_one_admission, case_one_lineage, case_disabling,
         case_enable_refusals, case_out_of_scope, case_corrupt_moved_unpublished, case_replay_unknown, case_state_change, case_pause,
         case_termination_markers, case_unreadable_control, case_repaired, case_deferred_empty, case_unrelated_corrected,
         case_partially_corrected, case_all_corrected, case_later_ordinary, case_second_refusal, case_repeated_notice,
         case_notice_quarantined, case_failed_successor, case_idempotent_settlement, case_settlement_branches)


def run(api) -> dict:
    return {fn.__name__[len("case_"):]: fn(api) for fn in CASES}
