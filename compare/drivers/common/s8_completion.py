"""Shared S8 scenario steps (`evidence.completion`): M7 `application/completion.py` (`CompletionAuthority`: `record`, `inspect`,
`_provenance`, `require_authority`; `_excerpt`, `_task_of`), characterized BEFORE the module moves (DESIGN-s8 §6 V11; the branch table
`branch-table-evidence.txt` section `application/completion.py`: every raise, every except and every `require` of this module is
covered, see `BRANCH_COVERAGE`).

Every case mirrors a test of M7 `tests/test_completion_authority.py` (the test name is the group label), plus LABELLED additions that
reach the branches of the module the tests do not (the non-dict records, the excerpt bound, the `now` skew, the document faults, the
review-run variants, the store failure inside the provenance check):

- **c1_test_malformed_records_are_rejected_and_logged**: the 24 malformed records twice each (the replay lands on the same notice), the
  cross-target receipt, the notices (`_task_of`, `_excerpt`), the empty verdict ledger, `rejected_only`; non-dict records and the bound.
- **c2_test_worker_success_is_not_completion_authority**: `not_evaluated`, `no_ledger`, `require_authority` refusing, the task identity.
- **c3_test_verdict_binds_execution_spec_artifact_and_receipt**: the execution binding, `not_succeeded`, `authoritative`, `stale`, the
  second verdict's sequence; the unknown task; the types of the task's generation and attempt.
- **c4_test_reclaimed_execution_makes_old_verdicts_stale**, **c5_test_recording_order_not_observed_time_selects_the_verdict**,
  **c6_test_scenario_denominator_is_explicit**, **c7_test_duplicate_and_concurrent_records_do_not_inflate** (eight sequential
  deliveries: the threads of M7 are not a scenario step), the reused identity.
- **c8_test_authority_needs_real_evidence_an_independent_reviewer_and_the_approved_denominator**: every provenance state in order.
- **c9_test_memory_corruption_is_a_named_state**, **c10_test_postgres_corruption_and_unreachable_store_are_distinct** (the part the
  application decides: a store that fails is `unreadable`; PostgreSQL itself is not a step), **c11_test_every_named_state_is_reachable**.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api` (`MemoryStore`, `CompletionAuthority`,
`BUCKET`, `REJECTIONS`, `STATES`, `EVALUATION_KIND`, `RECORD_ONLY`, `ContractError`, `digest`, `canonical`). The `artifacts` store is a
LABELLED fake of `FileArtifacts` (`inspect(ref)`, `document(ref)`; M7's tests write real files, whose faults are scripted here by type);
the organization is a LABELLED fake with the `agents` mapping `CompletionAuthority` reads; the task rows are written the way the
Workflow writes the fields the module reads (`generation`, `attempt`, `status`, `agent`, `result.execution_ref`). Observed times lie in the
past (2026-09-10) or far in the future (2099): `record` reads the real clock when no `now` is passed, in the reference through a patched
`datetime` and in the target not, so no step depends on it. For every refusal the digest of each of the two owned buckets and of the
whole store before and after is recorded."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import s8_research_program as R

SPEC = "a" * 40
OTHER_SPEC = "d" * 40
REVIEWER = "lead:research"
OTHER_REVIEWER = "lead:improvement"
WORKER = "worker:implementation"
SCENARIOS = ["login", "checkout"]
OBSERVED = "2026-09-10T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"
UNSET = object()
OWNED = ("completion_verdicts", "completion_rejections")


def ref_of(document):
    return "sha256:" + hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Artifacts:
    """LABELLED fake of `FileArtifacts`: `put` stores a document under its content digest; `inspect(ref)` and `document(ref)` raise
    `FileNotFoundError` for an absent reference, or the scripted fault of that reference."""

    def __init__(self):
        self.docs, self.inspect_faults, self.document_faults, self.calls = {}, {}, {}, []

    def put(self, document):
        ref = ref_of(document)
        self.docs[ref] = deepcopy(document)
        return ref

    def inspect(self, ref):
        self.calls.append(["inspect", ref])
        if ref in self.inspect_faults:
            raise self.inspect_faults[ref]
        if ref not in self.docs:
            raise FileNotFoundError(ref)
        return {"ref": ref}

    def document(self, ref):
        self.calls.append(["document", ref])
        if ref in self.document_faults:
            raise self.document_faults[ref]
        if ref not in self.docs:
            raise FileNotFoundError(ref)
        return deepcopy(self.docs[ref])


def organization(agents=(REVIEWER, OTHER_REVIEWER, WORKER)):
    """LABELLED. The organization as the module reads it: `agents` (a mapping of actor names)."""
    return SimpleNamespace(agents={name: {} for name in agents})


class Counting:
    """LABELLED. A store wrapper counting the transactions and raising `error` instead of opening the n-th one."""

    def __init__(self, inner, fail_on=(), error=None):
        self.inner, self.fail_on, self.error, self.count = inner, set(fail_on), error, 0

    def transaction(self, *args, **kwargs):
        self.count += 1
        if self.count in self.fail_on:
            raise self.error
        return self.inner.transaction(*args, **kwargs)


class Down:
    """LABELLED. A store that is unreachable (M7's `PostgresStore` on a closed port): every transaction raises."""

    def __init__(self, error):
        self.error = error

    def transaction(self, *args, **kwargs):
        raise self.error


# ---- the fixture (M7 tests/test_completion_authority.py `Case`) ---------------------------------------------------------
class Case:
    """One task under evaluation with evidence in the LABELLED artifacts store: the way the Workflow records the task row and
    the way a worker turn records its execution artifact."""

    def __init__(self, api, store=None, artifacts=None, tag="1", with_artifacts=True, org=UNSET, fail_on=(), error=None):
        self.api, self.tag = api, tag
        self.base = api.MemoryStore() if store is None else store
        self.artifacts = Artifacts() if artifacts is None else artifacts
        self.org = organization() if org is UNSET else org
        self.store = Counting(self.base, fail_on, error)
        self.authority = api.CompletionAuthority(self.store, artifacts=self.artifacts if with_artifacts else None, org=self.org)
        self.runs = 0
        self.last_artifact = None
        self.task = self.add_task("task-" + tag)

    # tasks
    def put(self, bucket, row_id, body):
        with self.base.transaction() as tx:
            tx.put(bucket, row_id, body)

    def get(self, bucket, row_id):
        with self.base.transaction() as tx:
            return tx.get(bucket, row_id)

    def add_task(self, task_id, generation=1, attempt=1, status="running", agent=WORKER, **extra):
        row = {"id": task_id, "generation": generation, "attempt": attempt, "status": status, "agent": agent, **extra}
        self.put("tasks", task_id, row)
        return row

    def execution_for(self, task):
        """What a worker turn records: the execution artifact names its task and attempt."""
        return self.artifacts.put({"task_id": task["id"], "attempt": task["attempt"], "answer": {"summary": "fixture"}})

    def finish(self, task=None, summary="done", execution_ref=None):
        task = task or self.task
        ref = execution_ref or self.execution_for(task)
        row = {**self.get("tasks", task["id"]), "status": "succeeded", "result": {"summary": summary, "execution_ref": ref}}
        self.put("tasks", task["id"], row)
        return ref

    @staticmethod
    def evaluated(task, *, spec=SPEC, scenarios=None, verdict="approved"):
        """What a reviewer execution's own output states: which execution it judged, and what it found."""
        return {"target": {"task_id": task["id"], "generation": task["generation"], "attempt": task["attempt"]},
                "spec_revision": spec, "verdict": verdict,
                "scenarios": scenarios or {"expected": list(SCENARIOS), "passed": list(SCENARIOS), "excluded": []}}

    def reviewer_run(self, reviewer, task, *, succeed=True, evaluated=None, document=None, row=None):
        """A reviewer execution is the reviewer's own task row with its own execution artifact; `document` replaces the artifact's
        content (a function of the review task id), `row` the task row's fields."""
        self.runs += 1
        review_id = f"review-{self.tag}-{self.runs}"
        doc = {"task_id": review_id, "attempt": 1, "answer": {"evaluated": evaluated or self.evaluated(task)}}
        if document is not None:
            doc = document(review_id)
        ref = self.artifacts.put(doc)
        fields = {"id": review_id, "generation": 1, "attempt": 1, "agent": reviewer,
                  "status": "succeeded" if succeed else "cancelled"}
        if succeed:
            fields["result"] = {"summary": "evaluated", "execution_ref": ref}
        self.put("tasks", review_id, {**fields, **(row or {})})
        return ref

    def evaluation(self, task=None, *, reviewer=REVIEWER, kind="model", spec=SPEC, scenarios=SCENARIOS, reviewer_ran=True,
                   evaluated=None, execution_ref=None, scenarios_raw=UNSET, **over):
        task = task or self.task
        if execution_ref is None and reviewer_ran:
            execution_ref = self.reviewer_run(reviewer, task, evaluated=evaluated or self.evaluated(task, spec=spec))
        document = {"kind": self.api.EVALUATION_KIND, "task_id": task["id"], "attempt": task["attempt"], "spec_revision": spec,
                    "scenarios": list(scenarios), "reviewer": {"actor": reviewer, "kind": kind}, "execution_ref": execution_ref, **over}
        if scenarios_raw is not UNSET:
            document["scenarios"] = scenarios_raw
        return self.artifacts.put(document)

    def verdict(self, task=None, *, execution_ref=None, evaluation=None, reviewer=REVIEWER, kind="model", spec=SPEC, **over):
        task = task or self.task
        target = {"task_id": task["id"], "generation": task["generation"], "attempt": task["attempt"]}
        execution_ref = execution_ref or self.execution_for(task)
        reviewer = reviewer if isinstance(reviewer, dict) else {"actor": reviewer, "kind": kind}
        if evaluation is None:
            produced = self.evaluated(task, spec=spec, scenarios=over.get("scenarios"), verdict=over.get("verdict", "approved"))
            evaluation = self.evaluation(task, reviewer=reviewer["actor"], kind=reviewer["kind"], spec=spec, evaluated=produced)
        base = {"schema_version": 1, "event": "completion.verdict", "verdict": "approved", "target": target, "spec_revision": spec,
                "evaluation_artifact": evaluation, "runner_receipt": {"id": execution_ref, "digest": execution_ref[7:], **target},
                "reviewer": reviewer, "scenarios": {"expected": list(SCENARIOS), "passed": list(SCENARIOS), "excluded": []},
                "observed_at": OBSERVED}
        return {**base, **over}

    # the authority, observed
    def state(self):
        rows = {bucket: len(self.rows(bucket)) for bucket in OWNED}
        return {"buckets": R.snapshot(self.base, OWNED), "store": R.store_digest(self.base), "rows": rows}

    def rows(self, bucket):
        with self.base.transaction() as tx:
            return tx.scan(bucket)

    def obs(self, fn, *args, **kwargs):
        """One call: its value or refusal (type, text), and for a refusal the owned-bucket and whole-store digests before and after."""
        before = self.state()
        try:
            out = {"value": fn(*args, **kwargs)}
        except Exception as exc:  # noqa: BLE001 - every refusal and propagated fault is part of the observation
            out = {"raised": type(exc).__name__, "message": str(exc)[:400]}
        after = self.state()
        out["nothing_written"] = before["store"] == after["store"]
        if "raised" in out:
            out.update(before=before, after=after)
        else:
            out["store_after"] = after["store"]
        return out

    def record(self, record, **kwargs):
        self.last_artifact = record["evaluation_artifact"] if isinstance(record, dict) and "evaluation_artifact" in record else None
        return self.obs(self.authority.record, record, **kwargs)

    def inspect(self, task=None, spec=SPEC, artifact=None, **kwargs):
        task = task or self.task
        return self.authority.inspect(task["id"], spec_revision=spec,
                                      evaluation_artifact=self.last_artifact if artifact is None else artifact, **kwargs)

    def inspected(self, **kwargs):
        return self.obs(self.inspect, **kwargs)

    def require(self, task=None, spec=SPEC, artifact=None, **kwargs):
        task = task or self.task
        return self.obs(self.authority.require_authority, task["id"], spec_revision=spec,
                        evaluation_artifact=self.last_artifact if artifact is None else artifact, **kwargs)

    def verdict_state(self, **kwargs):
        """The state and reason of an inspection (the shape most cases assert)."""
        report = self.inspect(**kwargs)
        return {k: report.get(k) for k in ("state", "authority", "reason")}

    def notices(self):
        return sorted(self.rows(OWNED[1]), key=lambda r: r["id"])


def summary(report):
    return {k: report.get(k) for k in ("state", "authority", "verdicts", "corrupt", "rejections", "reason")}


# ---- c1 -----------------------------------------------------------------------------------------------------------------
MALFORMED = [
    ("schema null", {"schema_version": None}, "schema_version"),
    ("schema unknown", {"schema_version": 2}, "schema_version"),
    ("schema text", {"schema_version": "1"}, "schema_version"),
    ("unrelated event", {"event": "unrelated"}, "event"),
    ("verdict list", {"verdict": ["approved"]}, "verdict"),
    ("verdict false text", {"verdict": "false"}, "verdict"),
    ("completeness false text", {"completeness": "false"}, "exactly"),
    ("caller cross_target flag", {"cross_target": True}, "exactly"),
    ("nan timestamp", {"observed_at": float("nan")}, "observed_at"),
    ("numeric timestamp", {"observed_at": 200}, "observed_at"),
    ("naive timestamp", {"observed_at": "2026-09-10T00:00:00"}, "timezone"),
    ("future timestamp", {"observed_at": FUTURE}, "future"),
    ("generation text", {"target": {"task_id": "x", "generation": "1", "attempt": 1}}, "generation"),
    ("generation bool", {"target": {"task_id": "x", "generation": True, "attempt": 1}}, "generation"),
    ("spec short", {"spec_revision": "abc"}, "spec_revision"),
    ("artifact bare", {"evaluation_artifact": "b" * 64}, "evaluation_artifact"),
    ("reviewer empty", {"reviewer": {"actor": " ", "kind": "model"}}, "reviewer.actor"),
    ("reviewer kind", {"reviewer": {"actor": "lead:qa", "kind": "caller"}}, "reviewer.kind"),
    ("duplicate scenario", {"scenarios": {"expected": ["a", "a"], "passed": ["a"], "excluded": []}}, "repeat"),
    ("passed outside expected", {"scenarios": {"expected": ["a"], "passed": ["b"], "excluded": []}}, "subset"),
    ("exclusion unapproved", {"scenarios": {"expected": ["a"], "passed": [], "excluded": [{"id": "a"}]}}, "exactly"),
]


def c1_malformed(api):
    case = Case(api)
    task = case.task
    execution, evaluation = case.execution_for(task), case.evaluation()
    out = {"records": {}}
    for name, mutation, needle in MALFORMED:
        record = case.verdict(execution_ref=execution, evaluation=evaluation, **mutation)
        first, replay = case.record(record), case.record(record)
        out["records"][name] = {"first": first, "replay": replay, "mentions": needle in first.get("message", ""),
                                "replay_adds_nothing": first["after"]["store"] == replay["after"]["store"]}
    cross = case.verdict(execution_ref=execution, evaluation=evaluation)
    cross["runner_receipt"] = {**cross["runner_receipt"], "task_id": "someone-else"}
    out["cross_target_receipt"] = case.record(cross)
    out["verdict_ledger_is_empty"] = case.rows(api.BUCKET) == []
    notices = case.notices()
    out["notice_count_is_one_per_distinct_refusal"] = [len(notices), len(MALFORMED) + 1]
    out["notice_task_ids"] = sorted({str(n["task_id"]) for n in notices})
    out["notice_reasons_start_with_the_prefix"] = all(n["reason"].startswith("Completion verdict rejected") for n in notices)
    out["notices"] = [{"id": n["id"], "task_id": n["task_id"], "reason": n["reason"], "at": n["at"], "excerpt_length": len(n["excerpt"]),
                       "excerpt_digest": api.digest(n["excerpt"]), "keys": sorted(n)} for n in notices]
    out["notice_id_is_the_digest_of_task_reason_excerpt"] = all(
        n["id"] == api.digest([n["task_id"], n["reason"], n["excerpt"]]) for n in notices)
    out["inspect_is_rejected_only"] = summary(case.inspect(artifact=evaluation))
    # LABELLED additions: `_task_of` (non-dict record, target not a dict, task_id not a str) and `_excerpt` (the bound).
    odd = Case(api, tag="odd")
    out["task_of"] = {}
    for label, record in (("none", None), ("list", ["a"]), ("text", "text"), ("int", 42), ("empty_dict", {}),
                          ("target_not_a_dict", {"target": "task-1"}), ("task_id_int", {"target": {"task_id": 7}}),
                          ("task_id_str_subclass", {"target": {"task_id": StrSub("sub")}}), ("task_id_str", {"target": {"task_id": "t-9"}})):
        out["task_of"][label] = odd.record(record)
    out["task_of_notice_task_ids"] = sorted(str(n["task_id"]) for n in odd.notices())
    long_record = odd.verdict(reviewer={"actor": " " * 3, "kind": "model"}, evaluation="sha256:" + "0" * 64, execution_ref="sha256:" + "1" * 64,
                              extra="x" * 3000)
    first, again = odd.record(long_record), odd.record(long_record)
    notice = [n for n in odd.notices() if len(n["excerpt"]) > 1000][0]
    out["long_excerpt"] = {"first": first, "again": again, "length": len(notice["excerpt"]), "ends_with_ellipsis": notice["excerpt"].endswith("…"),
                           "head_digest": api.digest(notice["excerpt"][:2000])}
    exact = {"x": "y" * (2000 - len(repr({"x": ""})))}
    out["excerpt_exactly_at_the_bound_is_kept_whole"] = [len(repr(exact)), odd.record(exact)["raised"]]
    exact_notice = [n for n in odd.notices() if n["excerpt"] == repr(exact)]
    out["excerpt_exactly_at_the_bound_notice_count"] = len(exact_notice)
    return out


class StrSub(str):
    """A `str` subclass: `_task_of` accepts only `type(task_id) is str`."""


# ---- c2 -----------------------------------------------------------------------------------------------------------------
def c2_worker_success(api):
    case = Case(api)
    evaluation = case.evaluation()
    out = {"before_any_verdict": summary(case.inspect(artifact=evaluation))}
    case.finish(summary="self-reported")
    out["task_status"] = case.get("tasks", case.task["id"])["status"]
    out["after_the_worker_succeeded"] = summary(case.inspect(artifact=evaluation))
    out["require_authority_refuses"] = case.require(artifact=evaluation)
    out["no_such_task"] = summary(case.authority.inspect("no-such-task", spec_revision=SPEC, evaluation_artifact=evaluation))
    out["no_such_task_require"] = case.obs(case.authority.require_authority, "no-such-task", spec_revision=SPEC, evaluation_artifact=evaluation)
    out["task_identity_required"] = {label: case.obs(case.authority.inspect, value, spec_revision=SPEC, evaluation_artifact=evaluation)
                                     for label, value in (("empty", ""), ("none", None), ("int", 5), ("list", ["task-1"]),
                                                          ("str_subclass", StrSub("task-1")), ("whitespace", " "))}
    return out


# ---- c3 -----------------------------------------------------------------------------------------------------------------
def c3_binding(api):
    case = Case(api)
    task = case.task
    execution = case.execution_for(task)
    behind = case.verdict(execution_ref=execution,
                          target={"task_id": task["id"], "generation": task["generation"] + 1, "attempt": task["attempt"]})
    behind["runner_receipt"] = {**behind["runner_receipt"], "generation": task["generation"] + 1}
    out = {"generation_ahead": case.record(behind)}
    attempt_ahead = case.verdict(execution_ref=execution,
                                 target={"task_id": task["id"], "generation": task["generation"], "attempt": task["attempt"] + 1})
    attempt_ahead["runner_receipt"] = {**attempt_ahead["runner_receipt"], "attempt": task["attempt"] + 1}
    out["attempt_ahead"] = case.record(attempt_ahead)
    ghost_target = {"task_id": "ghost-task", "generation": 1, "attempt": 1}
    ghost = case.verdict(execution_ref=execution, target=ghost_target)
    ghost["runner_receipt"] = {**ghost["runner_receipt"], **ghost_target}
    out["unknown_task"] = case.record(ghost)
    approved = case.verdict(execution_ref=execution)
    recorded = case.record(approved)
    out["recorded"] = recorded
    out["stored_row_keys"] = sorted(case.get(api.BUCKET, recorded["value"]["id"]))
    out["stored_row_equals_the_verdict_plus_sequence"] = {
        k: v for k, v in case.get(api.BUCKET, recorded["value"]["id"]).items() if k not in api.RECORD_ONLY and k not in ("id", "complete")
        } == {**approved, "observed_at": approved["observed_at"]}
    out["approved_before_the_worker_finished"] = summary(case.inspect())
    case.finish(execution_ref=execution)
    report = case.inspect()
    out["authoritative"] = {**summary(report), "latest": report["latest"], "generation": report["generation"], "attempt": report["attempt"],
                            "status": report["status"]}
    out["require_authority"] = case.require(artifact=approved["evaluation_artifact"])
    out["another_spec_is_stale"] = summary(case.inspect(spec=OTHER_SPEC))
    out["another_artifact_is_stale"] = summary(case.inspect(artifact=case.evaluation()))
    other = case.record(case.verdict(execution_ref=execution, spec=OTHER_SPEC))
    out["same_scenarios_other_spec"] = other
    out["other_is_a_new_identity_and_sequence"] = [other["value"]["changed"], other["value"]["id"] != recorded["value"]["id"], other["value"]["sequence"]]
    out["latest_for_the_first_artifact"] = case.inspect(artifact=approved["evaluation_artifact"])["latest"]
    # LABELLED: the row's generation and attempt must be integers (`type(...) is int`), bool is not.
    boolean = Case(api, tag="bool")
    boolean.add_task("task-bool", generation=True, attempt=True)
    target = {"task_id": "task-bool", "generation": 1, "attempt": 1}
    record = boolean.verdict(task={"id": "task-bool", "generation": 1, "attempt": 1})
    out["bool_generation_and_attempt_on_the_row"] = boolean.record(record)
    float_row = Case(api, tag="float")
    float_row.add_task("task-float", generation=1.0, attempt=1)
    out["float_generation_on_the_row"] = float_row.record(float_row.verdict(task={"id": "task-float", "generation": 1, "attempt": 1}))
    missing_row = Case(api, tag="nogen")
    with missing_row.base.transaction() as tx:
        tx.put("tasks", "task-nogen", {"id": "task-nogen"})
    out["row_without_generation"] = missing_row.record(missing_row.verdict(task={"id": "task-nogen", "generation": 1, "attempt": 1}))
    out["target_used_by_the_bool_case"] = target
    return out


# ---- c4 -----------------------------------------------------------------------------------------------------------------
def c4_reclaimed(api):
    case = Case(api, tag="r")
    first = case.task
    out = {"first_verdict": case.record(case.verdict(first))}
    second = case.add_task(first["id"], generation=2, attempt=2)   # the claim after the lease lapsed
    execution = case.execution_for(second)
    case.finish(second, summary="second attempt", execution_ref=execution)
    out["old_verdict_is_stale"] = summary(case.inspect(second))
    out["old_target_refused"] = case.record(case.verdict(first, reviewer=OTHER_REVIEWER))
    case.record(case.verdict(second, execution_ref=execution))
    out["new_verdict_is_authoritative"] = summary(case.inspect(second))
    out["two_rows_one_per_attempt"] = sorted((r["target"]["generation"], r["target"]["attempt"], r["sequence"]) for r in case.rows(api.BUCKET))
    # LABELLED: only the attempt moved (the same generation).
    same_generation = Case(api, tag="g")
    task = same_generation.task
    execution = same_generation.finish()
    same_generation.record(same_generation.verdict(execution_ref=execution))
    same_generation.add_task(task["id"], generation=1, attempt=2, status="succeeded",
                             result={"summary": "x", "execution_ref": execution})
    out["attempt_moved_only"] = summary(same_generation.inspect())
    return out


# ---- c5 -----------------------------------------------------------------------------------------------------------------
def c5_recording_order(api):
    case = Case(api, tag="o")
    execution = case.finish()
    approved = case.verdict(execution_ref=execution, observed_at="2026-09-10T00:00:10+00:00")
    rejected = case.verdict(execution_ref=execution, verdict="iterate", observed_at="2026-09-10T00:00:00+00:00", reviewer=OTHER_REVIEWER,
                            kind="human", evaluation=approved["evaluation_artifact"])
    rejected["reviewer"] = {"actor": OTHER_REVIEWER, "kind": "human"}
    out = {"approved": case.record(approved)}
    out["approved_state"] = summary(case.inspect())
    out["rejected_observed_earlier"] = case.record(rejected)
    after = case.inspect()
    out["rejection_is_current"] = {**summary(after), "latest": after["latest"]}
    replay = case.record({**approved, "observed_at": "2026-09-10T00:00:30+00:00"})
    out["replay_with_a_later_observed_at"] = replay
    out["replay_is_the_original_row"] = replay["value"] == {"id": replay["value"]["id"], "changed": False, "sequence": 1}
    out["old_acceptance_never_outranks"] = summary(case.inspect())
    same_second = case.verdict(execution_ref=execution, observed_at="2026-09-10T00:00:00+00:00", reviewer=OTHER_REVIEWER)
    out["same_second"] = case.record(same_second)
    last = case.inspect()
    out["third_is_latest"] = {**summary(last), "latest": last["latest"]}
    out["observed_at_is_normalized_to_utc"] = case.record(case.verdict(
        execution_ref=execution, observed_at="2026-09-10T09:00:00+09:00", spec=OTHER_SPEC))
    out["stored_observed_at"] = sorted(r["observed_at"] for r in case.rows(api.BUCKET))
    # LABELLED: a second task's rows share the bucket and sequence independently; its rejections are not this task's.
    other = Case(api, store=case.base, artifacts=case.artifacts, tag="p")
    other_execution = other.finish()
    out["other_task_first_sequence"] = other.record(other.verdict(execution_ref=other_execution))
    out["other_task_rejection"] = other.record(other.verdict(execution_ref=other_execution, schema_version=9))
    out["rejections_by_task"] = [summary(case.inspect())["rejections"], summary(other.inspect())["rejections"]]
    out["verdicts_by_task"] = [summary(case.inspect())["verdicts"], summary(other.inspect())["verdicts"]]
    return out


# ---- c6 -----------------------------------------------------------------------------------------------------------------
def c6_denominator(api):
    case = Case(api, tag="d")
    execution = case.finish()
    evaluation = case.evaluation()
    out = {}
    empty = {"expected": [], "passed": [], "excluded": []}
    out["empty"] = case.record(case.verdict(execution_ref=execution, evaluation=evaluation, scenarios=empty))
    out["empty_state"] = summary(case.inspect())
    partial = {"expected": SCENARIOS, "passed": ["login"], "excluded": []}
    out["partial"] = case.record(case.verdict(execution_ref=execution, evaluation=evaluation, scenarios=partial))
    out["partial_state"] = summary(case.inspect())
    excluded = {"expected": SCENARIOS, "passed": ["login"],
                "excluded": [{"id": "checkout", "approved_by": "human:owner", "revision": OTHER_SPEC, "reason": "payment sandbox unavailable"}]}
    out["excluded"] = case.record(case.verdict(execution_ref=execution, scenarios=excluded))
    report = case.inspect()
    out["excluded_state"] = {**summary(report), "latest": report["latest"]}
    bad = {}
    for label, scenarios in (
            ("excluded_not_expected", {"expected": ["a"], "passed": [], "excluded": [{"id": "z", "approved_by": "o", "revision": SPEC, "reason": "r"}]}),
            ("excluded_but_passed", {"expected": ["a"], "passed": ["a"], "excluded": [{"id": "a", "approved_by": "o", "revision": SPEC, "reason": "r"}]}),
            ("excluded_repeated", {"expected": ["a"], "passed": [], "excluded": [{"id": "a", "approved_by": "o", "revision": SPEC, "reason": "r"}] * 2}),
            ("excluded_not_a_list", {"expected": ["a"], "passed": [], "excluded": "none"}),
            ("excluded_bad_revision", {"expected": ["a"], "passed": [], "excluded": [{"id": "a", "approved_by": "o", "revision": "x", "reason": "r"}]}),
            ("excluded_blank_reason", {"expected": ["a"], "passed": [], "excluded": [{"id": "a", "approved_by": "o", "revision": SPEC, "reason": " "}]}),
            ("excluded_blank_approver", {"expected": ["a"], "passed": [], "excluded": [{"id": "a", "approved_by": "", "revision": SPEC, "reason": "r"}]}),
            ("scenarios_not_a_dict", ["a"]), ("scenarios_extra_key", {"expected": [], "passed": [], "excluded": [], "x": 1}),
            ("expected_not_a_list", {"expected": "a", "passed": [], "excluded": []}),
            ("expected_blank_name", {"expected": [" "], "passed": [], "excluded": []}),
            ("expected_non_str", {"expected": [1], "passed": [], "excluded": []})):
        bad[label] = case.record(case.verdict(execution_ref=execution, evaluation=evaluation, scenarios=scenarios))
    out["malformed_denominators"] = bad
    receipt = {}
    for label, edit in (("task_id_other", {"task_id": "x"}), ("generation_text", {"generation": "1"}), ("attempt_other", {"attempt": 5}),
                        ("digest_short", {"digest": "ab"}), ("digest_uppercase", {"digest": "AB" * 32}), ("id_blank", {"id": " "})):
        record = case.verdict(execution_ref=execution, evaluation=evaluation)
        record["runner_receipt"] = {**record["runner_receipt"], **edit}
        receipt[label] = case.record(record)
    extra = case.verdict(execution_ref=execution, evaluation=evaluation)
    extra["runner_receipt"] = {**extra["runner_receipt"], "extra": 1}
    receipt["extra_key"] = case.record(extra)
    out["receipt_refusals"] = receipt
    oversize = case.verdict(execution_ref=execution, evaluation=evaluation, scenarios={"expected": [f"s{i}" * 40 for i in range(2000)], "passed": [],
                                                                                     "excluded": []})
    out["oversize_record"] = case.record(oversize)
    return out


# ---- c7 -----------------------------------------------------------------------------------------------------------------
def c7_duplicates(api):
    case = Case(api, tag="u")
    execution = case.finish()
    record = case.verdict(execution_ref=execution)
    case.last_artifact = record["evaluation_artifact"]
    results = [case.record(record) for _ in range(8)]
    out = {"results": [r["value"] for r in results], "changed_count": sum(r["value"]["changed"] for r in results),
           "sequences": sorted({r["value"]["sequence"] for r in results}), "repeat_writes_nothing": [r["nothing_written"] for r in results[1:]]}
    report = case.inspect()
    out["after"] = summary(report)
    row_id = results[0]["value"]["id"]
    row = case.get(api.BUCKET, row_id)
    case.put(api.BUCKET, row_id, {**row, "verdict": "iterate"})
    out["identity_reused_with_different_content"] = case.record(record)
    case.put(api.BUCKET, row_id, row)
    case.put(api.BUCKET, row_id, {**row, "observed_at": "2020-01-01T00:00:00+00:00"})
    out["observed_at_differs_only"] = case.record(record)
    case.put(api.BUCKET, row_id, {key: value for key, value in row.items() if key != "reviewer"})
    out["stored_row_lacks_a_key"] = case.record(record)
    case.put(api.BUCKET, row_id, {**row, "sequence": 41, "recorded_at": "1999-01-01T00:00:00+00:00"})
    out["record_only_fields_differ"] = case.record(record)
    case.put(api.BUCKET, row_id, row)
    # `record(..., now=)`: the skew is 60 seconds and strict.
    skew = Case(api, tag="s")
    skew_exec = skew.finish()
    boundary = {}
    for label, observed in (("equal", "2026-09-22T00:00:00+00:00"), ("plus_60s", "2026-09-22T00:01:00+00:00"),
                            ("plus_61s", "2026-09-22T00:01:01+00:00"), ("plus_60s_other_offset", "2026-09-22T09:01:00+09:00")):
        boundary[label] = skew.record(skew.verdict(execution_ref=skew_exec, observed_at=observed, spec=OTHER_SPEC if label == "equal" else SPEC),
                                      now=SkewNow.AT)
    out["now_boundary"] = boundary
    out["observed_at_in_the_future_without_now"] = skew.record(skew.verdict(execution_ref=skew_exec, observed_at=FUTURE, reviewer=OTHER_REVIEWER))
    out["observed_in_the_past_without_now"] = skew.record(skew.verdict(execution_ref=skew_exec, observed_at=OBSERVED, reviewer=OTHER_REVIEWER, spec=OTHER_SPEC,
                                                                      kind="human"))
    return out


class SkewNow:
    """The `now` handed to `record` where the 60 second skew is the observation."""
    AT = datetime(2026, 9, 22, tzinfo=timezone.utc)


# ---- c8 -----------------------------------------------------------------------------------------------------------------
def c8_provenance(api):
    out = {}
    store = api.MemoryStore()
    artifacts = Artifacts()
    # the fabricated execution reference
    first = Case(api, store=store, artifacts=artifacts, tag="1")
    fabricated = "sha256:" + "f" * 64
    first.finish(execution_ref=fabricated)
    first.record(first.verdict())
    out["fabricated_receipt"] = summary(first.inspect())
    out["fabricated_receipt_require"] = first.require()
    # a second task with real evidence; no artifact store / an empty one
    second = Case(api, store=store, artifacts=artifacts, tag="2")
    execution = second.finish()
    good = second.verdict(execution_ref=execution)
    bare = api.CompletionAuthority(second.base)
    bare.record(good)
    out["no_artifact_store"] = summary(bare.inspect(second.task["id"], spec_revision=SPEC, evaluation_artifact=good["evaluation_artifact"]))
    empty = api.CompletionAuthority(second.base, artifacts=Artifacts(), org=organization())
    missing = empty.inspect(second.task["id"], spec_revision=SPEC, evaluation_artifact=good["evaluation_artifact"])
    out["empty_artifact_store"] = {**summary(missing), "names_the_execution": execution in missing["reason"]}
    out["real_evidence"] = summary(second.inspect(artifact=good["evaluation_artifact"]))
    # faults of the store while reading the two artifacts
    for label, faults, where in (
            ("inspect_fault_on_the_execution", artifacts.inspect_faults, execution),
            ("document_fault_on_the_execution", artifacts.document_faults, execution),
            ("inspect_fault_on_the_evaluation", artifacts.inspect_faults, good["evaluation_artifact"]),
            ("document_fault_on_the_evaluation", artifacts.document_faults, good["evaluation_artifact"])):
        faults[where] = PermissionError(13, "denied")
        out[label] = summary(second.inspect(artifact=good["evaluation_artifact"]))
        del faults[where]
    out["after_the_faults"] = summary(second.inspect(artifact=good["evaluation_artifact"]))
    # artifacts that exist but whose content binds nothing (fixture labels)
    third = Case(api, store=store, artifacts=artifacts, tag="3")
    label_execution = artifacts.put({"fixture": "execution evidence"})
    label_evaluation = artifacts.put({"fixture": "evaluation artifact"})
    third.finish(execution_ref=label_execution)
    third.record(third.verdict(execution_ref=label_execution, evaluation=label_evaluation))
    out["label_execution"] = summary(third.inspect())
    fourth = Case(api, store=store, artifacts=artifacts, tag="4")
    fourth_execution = fourth.finish()
    out["label_evaluation"] = _label(fourth, fourth_execution)
    # the receipt variants of the task row and the record
    receipts = {}
    for label, result in (("result_none", UNSET), ("result_not_a_dict", "text"), ("execution_ref_missing", {"summary": "x"}),
                          ("execution_ref_int", {"execution_ref": 5}), ("execution_ref_other", {"execution_ref": "sha256:" + "9" * 64})):
        case = Case(api, store=store, artifacts=artifacts, tag="rc-" + label)
        ref = case.execution_for(case.task)
        fields = {"status": "succeeded"} if result is UNSET else {"status": "succeeded", "result": result}
        case.put("tasks", case.task["id"], {**case.task, **fields})
        case.record(case.verdict(execution_ref=ref))
        receipts[label] = case.verdict_state()
    case = Case(api, store=store, artifacts=artifacts, tag="rc-digest")
    ref = case.finish()
    record = case.verdict(execution_ref=ref)
    record["runner_receipt"] = {**record["runner_receipt"], "digest": "0" * 64}
    case.record(record)
    receipts["digest_other"] = case.verdict_state()
    record = case.verdict(execution_ref=ref, spec=OTHER_SPEC)
    record["runner_receipt"] = {**record["runner_receipt"], "id": "someone-elses-receipt"}
    case.record(record)
    receipts["id_other"] = case.verdict_state(spec=OTHER_SPEC)
    other_doc = Case(api, store=store, artifacts=artifacts, tag="rc-doc")
    for label, doc in (("execution_document_other_task", {"task_id": "elsewhere", "attempt": 1}),
                       ("execution_document_other_attempt", {"task_id": other_doc.task["id"], "attempt": 4})):
        ref = artifacts.put({**doc, "label": label})
        task = other_doc.add_task("task-rcd-" + label, status="succeeded", result={"execution_ref": ref})
        doc_record = other_doc.verdict(task=task, execution_ref=ref)
        other_doc.record(doc_record)
        receipts[label] = summary(other_doc.authority.inspect(task["id"], spec_revision=SPEC, evaluation_artifact=doc_record["evaluation_artifact"]))
    out["receipt_variants"] = receipts
    # the evaluation artifact binds task, attempt, spec, scenarios and reviewer
    wrongs = {}
    for label, wrong, state in (("task", {"task_id": "other-task"}, "artifact_unbound"), ("attempt", {"attempt": 9}, "artifact_unbound"),
                                ("spec", {"spec": OTHER_SPEC}, "artifact_unbound"), ("scenarios", {"scenarios": ["login"]}, "scenario_mismatch"),
                                ("scenarios_empty", {"scenarios": []}, "artifact_unbound"), ("reviewer", {"reviewer": OTHER_REVIEWER}, "reviewer_unbound"),
                                ("kind", {"kind": "other-kind"}, "artifact_unbound"), ("scenarios_not_a_list", {"scenarios_raw": "login"}, "artifact_unbound"),
                                ("scenarios_blank_name", {"scenarios_raw": [" ", "login"]}, "artifact_unbound"),
                                ("scenarios_blank_str", {"scenarios_raw": ["", "login"]}, "artifact_unbound"),
                                ("scenarios_non_str", {"scenarios_raw": [1, 2]}, "artifact_unbound"),
                                ("scenarios_none", {"scenarios_raw": None}, "artifact_unbound")):
        wrong = dict(wrong)
        spec = wrong.pop("spec", SPEC)
        scenarios = wrong.pop("scenarios", SCENARIOS)
        reviewer_named = wrong.pop("reviewer", REVIEWER)
        raw = wrong.pop("scenarios_raw", UNSET)
        evaluation = fourth.evaluation(spec=spec, scenarios=scenarios, reviewer=reviewer_named, scenarios_raw=raw, **wrong)
        fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=evaluation))
        wrongs[label] = fourth.verdict_state()
    out["evaluation_artifact_bindings"] = wrongs
    out["evaluation_without_the_kind_key"] = _evaluation_without(fourth, fourth_execution, "kind")
    out["evaluation_without_the_scenarios_key"] = _evaluation_without(fourth, fourth_execution, "scenarios")
    # the reviewer must be an independent organization actor
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=fourth.evaluation(reviewer=WORKER), reviewer=WORKER))
    out["worker_reviews_itself"] = fourth.verdict_state()
    ghost = artifacts.put({"kind": api.EVALUATION_KIND, "task_id": fourth.task["id"], "attempt": fourth.task["attempt"], "spec_revision": SPEC,
                           "scenarios": SCENARIOS, "reviewer": {"actor": "ghost:reviewer", "kind": "human"}, "execution_ref": None})
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=ghost, reviewer="ghost:reviewer", kind="human"))
    out["reviewer_outside_the_organization"] = fourth.verdict_state()
    no_org = Case(api, store=store, artifacts=artifacts, tag="noorg", org=None)
    no_org_ref = no_org.finish()
    no_org.record(no_org.verdict(execution_ref=no_org_ref))
    out["no_organization"] = no_org.verdict_state()
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=fourth.evaluation(reviewer_ran=False)))
    out["no_reviewer_execution"] = fourth.verdict_state()
    unfinished = artifacts.put({"kind": api.EVALUATION_KIND, "task_id": fourth.task["id"], "attempt": fourth.task["attempt"], "spec_revision": SPEC,
                                "scenarios": SCENARIOS, "reviewer": {"actor": REVIEWER, "kind": "model"},
                                "execution_ref": fourth.reviewer_run(REVIEWER, fourth.task, succeed=False)})
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=unfinished))
    out["reviewer_run_never_succeeded"] = fourth.verdict_state()
    out["reviewer_execution_variants"] = _review_variants(api, store, artifacts)
    # the reviewer execution's own output must be the evaluation of this execution
    unrelated = Case(api, store=store, artifacts=artifacts, tag="unrelated")
    elsewhere = fourth.reviewer_run(REVIEWER, unrelated.task, evaluated=fourth.evaluated(unrelated.task))
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=fourth.evaluation(execution_ref=elsewhere)))
    out["reviewer_judged_another_task"] = {**fourth.verdict_state(expected_scenarios=SCENARIOS)}
    out["reviewer_judged_another_task_require"] = fourth.require(expected_scenarios=SCENARIOS)
    rejected_run = fourth.evaluation(evaluated=fourth.evaluated(fourth.task, verdict="iterate"))
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=rejected_run))
    out["rejection_recorded_as_approval"] = fourth.verdict_state(expected_scenarios=SCENARIOS)
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=rejected_run, verdict="iterate"))
    out["recorded_as_what_it_was"] = fourth.verdict_state()
    half = fourth.evaluation(evaluated=fourth.evaluated(fourth.task, scenarios={"expected": SCENARIOS, "passed": ["login"], "excluded": []}))
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=half))
    out["scenario_results_not_produced"] = fourth.verdict_state()
    other_spec_run = fourth.evaluation(evaluated=fourth.evaluated(fourth.task, spec=OTHER_SPEC))
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=other_spec_run))
    out["reviewer_judged_another_spec"] = fourth.verdict_state()
    out["produced_variants"] = _produced_variants(api, store, artifacts)
    fourth.record(fourth.verdict(execution_ref=fourth_execution, reviewer=OTHER_REVIEWER, kind="human"))
    report = fourth.inspect()
    out["authoritative"] = {**summary(report), "latest": report["latest"]}
    # the consumer's denominator
    out["consumer_names_fewer"] = fourth.verdict_state(expected_scenarios=["login"])
    out["consumer_names_the_same_reordered_and_repeated"] = fourth.verdict_state(expected_scenarios=["checkout", "login", "login"])
    out["consumer_names_nothing"] = fourth.verdict_state(expected_scenarios=None)
    out["require_authority_with_the_consumer_denominator"] = fourth.require(expected_scenarios=SCENARIOS)
    out["consumer_denominator_a_string"] = fourth.obs(fourth.inspect, expected_scenarios="login")
    out["consumer_denominator_a_tuple"] = fourth.obs(fourth.inspect, expected_scenarios=("login", "checkout"))
    out["consumer_denominator_with_a_non_str"] = fourth.obs(fourth.inspect, expected_scenarios=["login", 3])
    out["consumer_denominator_empty"] = fourth.verdict_state(expected_scenarios=[])
    out["require_authority_consumer_denominator_a_string"] = fourth.require(expected_scenarios="login")
    # documents that are not objects propagate (LABELLED: nothing in M7 maps them)
    out["non_object_documents"] = _non_objects(api, store, artifacts)
    out["artifact_reads"] = len(artifacts.calls)
    return out


def _label(fourth, execution):
    label_evaluation = fourth.artifacts.put({"fixture": "evaluation artifact"})
    fourth.record(fourth.verdict(execution_ref=execution, evaluation=label_evaluation))
    return fourth.verdict_state()


def _evaluation_without(case, execution, key):
    task = case.task
    document = {"kind": case.api.EVALUATION_KIND, "task_id": task["id"], "attempt": task["attempt"], "spec_revision": SPEC,
                "scenarios": list(SCENARIOS), "reviewer": {"actor": REVIEWER, "kind": "model"}, "execution_ref": None}
    del document[key]
    evaluation = case.artifacts.put(document)
    case.record(case.verdict(execution_ref=execution, evaluation=evaluation))
    return case.verdict_state()


def _review_variants(api, store, artifacts):
    """The reviewer execution that is not "a succeeded task of the reviewer" in one respect each (the `require` of the lookup)."""
    out = {}

    def make(tag, **kwargs):
        case = Case(api, store=store, artifacts=artifacts, tag="rv-" + tag)
        ref = case.finish()
        return case, ref

    for label, run_kwargs in (
            ("agent_is_another_actor", {"row": {"agent": OTHER_REVIEWER}}), ("status_not_succeeded", {"row": {"status": "failed"}}),
            ("attempt_differs", {"row": {"attempt": 2}}), ("result_missing", {"row": {"result": None}}),
            ("result_not_a_dict", {"row": {"result": "text"}}),
            ("result_names_another_artifact", {"row": {"result": {"execution_ref": "sha256:" + "8" * 64}}})):
        case, ref = make(label)
        run = case.reviewer_run(REVIEWER, case.task, **run_kwargs)
        case.record(case.verdict(execution_ref=ref, evaluation=case.evaluation(execution_ref=run)))
        out[label] = case.verdict_state()
    case, ref = make("task_id_not_a_str")
    run = case.reviewer_run(REVIEWER, case.task, document=lambda review_id: {"task_id": 7, "attempt": 1, "answer": {"evaluated": case.evaluated(case.task)}})
    case.record(case.verdict(execution_ref=ref, evaluation=case.evaluation(execution_ref=run)))
    out["review_document_task_id_not_a_str"] = case.verdict_state()
    case, ref = make("task_id_unknown")
    run = case.reviewer_run(REVIEWER, case.task, document=lambda review_id: {"task_id": "no-such-review", "attempt": 1,
                                                                             "answer": {"evaluated": case.evaluated(case.task)}})
    case.record(case.verdict(execution_ref=ref, evaluation=case.evaluation(execution_ref=run)))
    out["review_document_names_an_unknown_task"] = case.verdict_state()
    for label, value in (("none", None), ("blank", ""), ("not_sha256", "md5:abc"), ("int", 5), ("list", ["sha256:x"])):
        case, ref = make("ref-" + label)
        case.record(case.verdict(execution_ref=ref, evaluation=case.evaluation(execution_ref=value, reviewer_ran=False)))
        out["review_reference_" + label] = case.verdict_state()
    case, ref = make("ref-absent")
    case.record(case.verdict(execution_ref=ref, evaluation=case.evaluation(execution_ref="sha256:" + "7" * 64)))
    out["review_artifact_absent"] = case.verdict_state()
    case, ref = make("review-doc-fault")
    run = case.reviewer_run(REVIEWER, case.task)
    artifacts.document_faults[run] = OSError("disk")
    case.record(case.verdict(execution_ref=ref, evaluation=case.evaluation(execution_ref=run)))
    out["review_artifact_unreadable"] = case.verdict_state()
    del artifacts.document_faults[run]
    case, ref = make("review-doc-list")
    run = case.reviewer_run(REVIEWER, case.task, document=lambda review_id: ["not", "an", "object"])
    case.record(case.verdict(execution_ref=ref, evaluation=case.evaluation(execution_ref=run)))
    out["review_document_not_an_object"] = case.verdict_state()
    # the store fails while the reviewer's task is read (the 2nd transaction of the inspection)
    for label, error in (("long_message", RuntimeError("m" * 300)), ("empty_message", RuntimeError(""))):
        case, ref = make("store-" + label)
        run = case.reviewer_run(REVIEWER, case.task)
        evaluation = case.evaluation(execution_ref=run)
        record = case.verdict(execution_ref=ref, evaluation=evaluation)
        case.record(record)
        failing = Case(api, store=case.base, artifacts=artifacts, tag="rv-" + label, fail_on={2}, error=error)
        report = failing.authority.inspect(case.task["id"], spec_revision=SPEC, evaluation_artifact=evaluation)
        out["store_fails_reading_the_review_task_" + label] = {**summary(report), "transactions": failing.store.count}
    return out


def _produced_variants(api, store, artifacts):
    """The reviewer output that is not what the verdict records (`verdict_mismatch`) or not valid scenario results."""
    out = {}
    excluded = {"id": "checkout", "approved_by": "human:owner", "revision": OTHER_SPEC, "reason": "payment sandbox unavailable"}
    recorded = {"expected": SCENARIOS, "passed": ["login"], "excluded": [excluded]}
    for label, evaluated_edit, verdict_over in (
            ("answer_not_an_object", None, {}),
            ("evaluated_not_an_object", {"answer": {"evaluated": "text"}}, {}),
            ("evaluated_missing", {"answer": {}}, {}),
            ("scenarios_missing", {"scenarios": None}, {}),
            ("scenarios_malformed", {"scenarios": {"expected": "login", "passed": [], "excluded": []}}, {}),
            ("verdict_invalid", {"verdict": "bogus"}, {}),
            ("verdict_none", {"verdict": None}, {}),
            ("verdict_differs", {"verdict": "iterate"}, {}),
            ("passed_differs", {"scenarios": {"expected": SCENARIOS, "passed": ["checkout"], "excluded": []}}, {}),
            ("expected_differs", {"scenarios": {"expected": ["login"], "passed": ["login"], "excluded": []}}, {}),
            ("excluded_reason_differs", {"scenarios": {**recorded, "excluded": [{**excluded, "reason": "another reason"}]}},
             {"scenarios": recorded}),
            ("excluded_approver_differs", {"scenarios": {**recorded, "excluded": [{**excluded, "approved_by": "human:other"}]}},
             {"scenarios": recorded}),
            ("excluded_same_in_another_order", {"scenarios": {"expected": ["checkout", "login"], "passed": ["login"], "excluded": [excluded]}},
             {"scenarios": recorded}),
            ("passed_in_another_order", {"scenarios": {"expected": ["checkout", "login"], "passed": ["checkout", "login"], "excluded": []}}, {})):
        case = Case(api, store=store, artifacts=artifacts, tag="pv-" + label)
        ref = case.finish()
        evaluated = case.evaluated(case.task, scenarios=verdict_over.get("scenarios"))
        if label == "answer_not_an_object":
            document = lambda review_id: {"task_id": review_id, "attempt": 1, "answer": "text"}   # noqa: E731
            run = case.reviewer_run(REVIEWER, case.task, document=document)
        elif evaluated_edit is not None and "answer" in evaluated_edit:
            answer = evaluated_edit["answer"]
            run = case.reviewer_run(REVIEWER, case.task, document=lambda review_id, answer=answer: {"task_id": review_id, "attempt": 1, "answer": answer})
        else:
            run = case.reviewer_run(REVIEWER, case.task, evaluated={**evaluated, **(evaluated_edit or {})})
        case.record(case.verdict(execution_ref=ref, evaluation=case.evaluation(execution_ref=run), **verdict_over))
        out[label] = case.verdict_state()
    return out


def _non_objects(api, store, artifacts):
    out = {}
    for label, which in (("execution_document_a_list", "execution"), ("evaluation_document_a_list", "evaluation")):
        case = Case(api, store=store, artifacts=artifacts, tag="no-" + label)
        ref = case.finish()
        record = case.verdict(execution_ref=ref)
        case.record(record)
        target = ref if which == "execution" else record["evaluation_artifact"]
        artifacts.docs[target] = ["not", "an", "object"]
        out[label] = case.obs(case.inspect)
    return out


# ---- c9 -----------------------------------------------------------------------------------------------------------------
def c9_corruption(api):
    case = Case(api, tag="c")
    execution = case.finish()
    first = case.record(case.verdict(execution_ref=execution))["value"]["id"]
    out = {"intact": summary(case.inspect())}

    def edit(row_id, **changes):
        row = case.get(api.BUCKET, row_id)
        case.put(api.BUCKET, row_id, {**row, **changes})

    row = case.get(api.BUCKET, first)
    edit(first, verdict="false")
    out["verdict_false"] = summary(case.inspect())
    second = case.record(case.verdict(execution_ref=execution, reviewer=OTHER_REVIEWER))["value"]["id"]
    report = case.inspect()
    out["one_corrupt_one_valid"] = {**summary(report), "latest": report["latest"]}
    case.put(api.BUCKET, first, row)
    variants = {}
    for label, changes in (("identity_mismatch", {"id": "0" * 64}), ("sequence_text", {"sequence": "1"}), ("sequence_bool", {"sequence": True}),
                           ("sequence_none", {"sequence": None}), ("observed_at_numeric", {"observed_at": 200}),
                           ("schema_version_text", {"schema_version": "1"}), ("target_text", {"target": "task-c"}),
                           ("extra_key_is_ignored", {"extra": 1}), ("complete_is_recomputed", {"complete": False}),
                           ("record_only_fields_dropped", {"recorded_at": None})):
        edit(first, **changes)
        variants[label] = summary(case.inspect())
        case.put(api.BUCKET, first, row)
    for label, key in (("reviewer_missing", "reviewer"), ("sequence_missing", "sequence"), ("scenarios_missing", "scenarios"),
                       ("event_missing", "event"), ("id_missing", "id")):
        case.put(api.BUCKET, first, {k: v for k, v in row.items() if k != key})
        variants[label] = summary(case.inspect())
        case.put(api.BUCKET, first, row)
    out["stored_row_variants"] = variants
    out["restored"] = summary(case.inspect())
    case.put(api.BUCKET, first, {k: v for k, v in row.items() if k != "target"})
    out["row_without_a_target_is_not_this_tasks"] = summary(case.inspect())
    case.put(api.BUCKET, first, {**row, "target": {"task_id": 5}})
    out["row_with_a_non_str_task_id_is_not_this_tasks"] = summary(case.inspect())
    case.put(api.BUCKET, first, row)
    # every row corrupt
    edit(first, verdict="false")
    edit(second, verdict="false")
    out["all_corrupt"] = summary(case.inspect())
    case.put(api.BUCKET, first, row)
    case.put(api.BUCKET, second, case.get(api.BUCKET, second) | {"verdict": "approved"})
    # a rejection notice for the task whose verdict rows are corrupt
    case.record(case.verdict(execution_ref=execution, schema_version=2))
    edit(first, verdict="false")
    out["rejections_alongside_corrupt_rows"] = summary(case.inspect())
    # unreadable
    out["unreadable_store"] = _unreadable(api)
    return out


def _unreadable(api):
    out = {}
    for label, error in (("closed_port", ConnectionRefusedError("connection refused")), ("long_message", OSError("z" * 500)),
                         ("empty_message", RuntimeError(""))):
        authority = api.CompletionAuthority(Down(error))
        try:
            report = authority.inspect("task-1", spec_revision=SPEC, evaluation_artifact="sha256:" + "0" * 64)
        except Exception as exc:  # noqa: BLE001
            out[label] = {"raised": type(exc).__name__}
            continue
        try:
            authority.require_authority("task-1", spec_revision=SPEC, evaluation_artifact="sha256:" + "0" * 64)
            required = "returned"
        except Exception as exc:  # noqa: BLE001
            required = [type(exc).__name__, str(exc)]
        out[label] = {"report": report, "report_keys": sorted(report), "require_authority": required}
    # `record` does not map a store failure: it propagates.
    broken = api.CompletionAuthority(Down(RuntimeError("store down")))
    for label, record in (("malformed_record", {"x": 1}), ("a_valid_record", Case(api, tag="z").verdict())):
        try:
            broken.record(record, now=SkewNow.AT)
            out["record_" + label] = "returned"
        except Exception as exc:  # noqa: BLE001
            out["record_" + label] = [type(exc).__name__, str(exc)]
    return out


# ---- c10 ----------------------------------------------------------------------------------------------------------------
def c10_constants(api):
    return {"BUCKET": api.BUCKET, "REJECTIONS": api.REJECTIONS, "RECORD_ONLY": list(api.RECORD_ONLY), "STATES": list(api.STATES),
            "EVALUATION_KIND": api.EVALUATION_KIND, "states_are_unique": len(set(api.STATES)) == len(api.STATES)}


def c11_states_reachable(api, observed):
    return {"reached": sorted(observed), "reached_equals_STATES": observed == set(api.STATES),
            "unreached": sorted(set(api.STATES) - observed), "outside_STATES": sorted(observed - set(api.STATES))}


def states_in(value, found=None):
    """Every `state` string in a nested observation."""
    found = set() if found is None else found
    if isinstance(value, dict):
        if isinstance(value.get("state"), str):
            found.add(value["state"])
        for item in value.values():
            states_in(item, found)
    elif isinstance(value, list):
        for item in value:
            states_in(item, found)
    return found


# ---- coverage -----------------------------------------------------------------------------------------------------------
BRANCH_COVERAGE = {
    "_excerpt (the bound of 2000)": "c1_malformed.long_excerpt, excerpt_exactly_at_the_bound_is_kept_whole",
    "_task_of (a dict record, a dict target, a str task_id)": "c1_malformed.task_of, task_of_notice_task_ids",
    "CompletionAuthority.__init__": "every case (store, artifacts, org)",
    "CompletionAuthority.record except ContractError -> notice -> raise (re-raise)": "c1_malformed.records (twice each), cross_target_receipt, notices",
    "CompletionAuthority.record require(same) 'identity reused'": "c7_duplicates.identity_reused_with_different_content, stored_row_lacks_a_key",
    "CompletionAuthority.record require(task is not None) 'unknown task'": "c3_binding.unknown_task",
    "CompletionAuthority.record require(generation/attempt) 'different execution'": "c3_binding.generation_ahead, attempt_ahead, bool_generation_and_attempt_on_the_row, "
                                                                                       "float_generation_on_the_row, row_without_generation; c4_reclaimed.old_target_refused",
    "CompletionAuthority.record calls self.store.transaction": "c1 (notice), c3 (verdict), c7 (replay); c9_corruption.unreadable_store.record_*",
    "CompletionAuthority.inspect require(task identity)": "c2_worker_success.task_identity_required",
    "CompletionAuthority.inspect except Exception -> unreadable": "c9_corruption.unreadable_store (closed_port, long_message, empty_message)",
    "CompletionAuthority.inspect except (ContractError, KeyError, TypeError) -> corrupt": "c9_corruption (ContractError rows; KeyError rows: reviewer_missing, "
                                                                                          "sequence_missing; TypeError: unreachable from a stored row, see NOTES)",
    "CompletionAuthority.inspect calls self.store.transaction": "every inspection",
    "CompletionAuthority._provenance except Exception (artifact read)": "c8_provenance.inspect_fault_*, document_fault_*",
    "CompletionAuthority._provenance require(expected_scenarios) 'must be scenario names'": "c8_provenance.consumer_denominator_a_string, _a_tuple, _with_a_non_str",
    "CompletionAuthority._provenance except Exception (reviewer lookup)": "c8_provenance.reviewer_execution_variants, store_fails_reading_the_review_task_*",
    "CompletionAuthority._provenance require(reviewer reference) and require(reviewer task)": "c8_provenance.reviewer_execution_variants",
    "CompletionAuthority._provenance except ContractError (produced verdict) -> verdict_mismatch": "c8_provenance.produced_variants.scenarios_malformed, verdict_invalid",
    "CompletionAuthority._provenance calls self.artifacts.document/inspect, self.store.transaction": "c8_provenance",
    "CompletionAuthority.require_authority require(authority)": "c2_worker_success.require_authority_refuses, c8_provenance.*_require, c9_corruption.unreadable_store",
}

M7_TESTS = {
    "test_malformed_records_are_rejected_and_logged[memory,postgres]": "c1_malformed",
    "test_worker_success_is_not_completion_authority[memory,postgres]": "c2_worker_success",
    "test_verdict_binds_execution_spec_artifact_and_receipt[memory,postgres]": "c3_binding",
    "test_reclaimed_execution_makes_old_verdicts_stale[memory,postgres]": "c4_reclaimed (the lapse of the lease is the task row's new generation and attempt)",
    "test_recording_order_not_observed_time_selects_the_verdict[memory,postgres]": "c5_recording_order",
    "test_scenario_denominator_is_explicit[memory,postgres]": "c6_denominator",
    "test_duplicate_and_concurrent_records_do_not_inflate[memory,postgres]": "c7_duplicates (sequential deliveries; the PostgreSQL write lock is not a step)",
    "test_authority_needs_real_evidence_an_independent_reviewer_and_the_approved_denominator[memory,postgres]": "c8_provenance",
    "test_memory_corruption_is_a_named_state": "c9_corruption",
    "test_postgres_corruption_and_unreachable_store_are_distinct": {
        "unreachable_store": "c9_corruption.unreadable_store (a store that raises; the PostgreSQL connection itself is not a step)",
        "postgres_row_edits": "unreachable: PostgreSQL (the row edits are the memory ones of c9_corruption)"},
    "test_every_named_state_is_reachable": "c11_states_reachable",
}


GROUPS = (
    ("c1_test_malformed_records_are_rejected_and_logged", c1_malformed),
    ("c2_test_worker_success_is_not_completion_authority", c2_worker_success),
    ("c3_test_verdict_binds_execution_spec_artifact_and_receipt", c3_binding),
    ("c4_test_reclaimed_execution_makes_old_verdicts_stale", c4_reclaimed),
    ("c5_test_recording_order_not_observed_time_selects_the_verdict", c5_recording_order),
    ("c6_test_scenario_denominator_is_explicit", c6_denominator),
    ("c7_test_duplicate_and_concurrent_records_do_not_inflate", c7_duplicates),
    ("c8_test_authority_needs_real_evidence_an_independent_reviewer_and_the_approved_denominator", c8_provenance),
    ("c9_test_memory_corruption_is_a_named_state", c9_corruption),
    ("c10_constants", c10_constants),
)


def run(api) -> dict:
    result, counts, observed = {}, {}, set()
    for name, group in GROUPS:
        result[name] = group(api)
        counts[name] = len(result[name])
        states_in(result[name], observed)
    result["c11_test_every_named_state_is_reachable"] = c11_states_reachable(api, observed)
    result["m7_tests"] = M7_TESTS
    result["branch_coverage"] = BRANCH_COVERAGE
    result["cases_per_group"] = counts
    return result
