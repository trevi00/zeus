"""Shared S8 scenario steps (`intake.frontdesk_adapter`): M7 `adapters/frontdesk.py` (`execute_frontdesk`, `clean_checkout`, the desk output
schema and prompt, and the desk's monitoring evidence builder `monitoring_facts`/`monitoring_evidence`), characterized BEFORE pilot 90
split-moves it (DESIGN-s8 §12.1 V17 P-b: the execute side to `intake.adapters.frontdesk`, the monitoring side to
`observation.adapters.desk_monitoring`).

The cases mirror the 28 adapter-level tests of M7 `tests/test_frontdesk.py` that pilot 84 left unreachable (`M7_TESTS` names each case group;
the 10 CLI tests are not adapter tests and stay S10), plus LABELLED additions for the branches those tests do not reach (`_fleet`,
`_observations`, `_sources`, the entry limits, a naive `now`).

- **s1_constants**: every module-level constant of both halves (the prompt, the output schema, the schema/file names, the windows, the limits).
- **s2_clean_checkout**: the exact HEAD and clean-tree refusals of `clean_checkout`.
- **s3_execute**: `execute_frontdesk` over a LABELLED fake executor (`service`, `git.review_workspace`/`git._git`, a `_run` recorder) with an
  EXPLICIT `snapshot` (the V17 seam: composition passes the evidence), the assignment refusals, a dirty or moved checkout before and after
  the run, malformed answers, heartbeat and stored-state invariants.
- **s4_monitoring_facts**: `monitoring_facts` over documents with a fixed clock: fresh, stale, future, undated, malformed, the accounting modes,
  every fleet/observation branch and bound.
- **s5_monitoring_evidence**: `monitoring_evidence(path, now)` over snapshot files in the scenario temp dir: fresh, stale, future, missing,
  directory, oversized, 20 malformed payloads, agreement with the readiness endpoint, no write.
- **s6_snapshot_none** and **s7_default_path** (present ONLY when the side still has `snapshot_path`, i.e. M7): `execute_frontdesk(..., snapshot=None)`
  self-reads the runtime file, and `snapshot_path()`/`monitoring_evidence()` with no path read it through the default path. These are the two V17
  intended differences (the target refuses `snapshot=None`, R-f1; its `monitoring_evidence` requires the path and `snapshot_path` is gone, R-m1):
  the scenario declares each group absent on the target. The refusal itself is pinned by the target's own tests.

Temp-path rule (documented, driver-side): every snapshot file lives in one scenario temp directory; `norm` replaces that directory's string,
wherever it occurs in a result, by `<tmp>` and counts the replacements (`TEMP_PATH_REPLACEMENTS`). It never masks a state, a reason or an age;
the results contain no path, so the count is expected to be zero.

The `now` the cases pass is built from `api.datetime`: the reference run installs the harness clock, which replaces `datetime.datetime`
in every M7 module, so a plain stdlib datetime would fail the module's own `isinstance(now, datetime)` check; the target uses the stdlib class.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. `api.FrontDesk(service, revision)` and `api.Harness(store, org)`
build the (real) desk and service; the executor, its git and `_run` are LABELLED doubles; nothing here starts a provider, a database or a
network call; the only file system use is the scenario's own temp directory."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import s8_frontdesk as base
from s8_frontdesk import ANSWER, IDS, REVISION, World, plain

TEMP_PATH_REPLACEMENTS = {"count": 0}
CONSTANT_NAMES = ("MONITORING_SCHEMA", "MONITORING_FILE", "MONITORING_MAX_BYTES", "FRESH_SECONDS", "FUTURE_TOLERANCE_SECONDS", "JOB_LIMIT",
                  "LANE_LIMIT", "FRESHNESS", "BASIS", "MONITORING_AUTHORITY", "ACCOUNTING_NOTE", "TEXT", "STRINGS", "DESK_PROPERTIES",
                  "DESK_OUTPUT", "PROMPT")

FLEET_DATA = {"schema": "urn:zeus:fleet-status:1", "registered": True, "id": "fleet-local",
              "paused": False, "max_parallel": 2,
              "budget": {"per_host": 192, "total": 192, "mode": "subscription"},
              "accounting_mode": "subscription",
              "lanes": [{"id": "lane-a", "team": "team-a", "active_job": "job-1"},
                        {"id": "lane-b", "team": "team-b", "active_job": None}],
              "jobs": [{"id": "job-1", "lane": "lane-a", "team": "team-a", "status": "running",
                        "reason_code": None, "operation_id": "op-1",
                        "goal": {"path": "docs/zeus/operations/secret-plan/SPEC.md",
                                 "criterion": "숨겨진 목표 문장"},
                        "dependencies": [], "calls": {"reserved": 1, "settled": 1},
                        "created_at": "2026-09-19T00:00:00+00:00",
                        "updated_at": "2026-09-19T00:00:00+00:00"}],
              "truncated": False}
OBSERVATION_DATA = {"schema": "urn:zeus:observation-monitor:1", "authority": "informational_only",
                    "observed_at": "2026-09-19T12:00:00+00:00",
                    "events": {"total": 120, "high_severity_total": 7},
                    "sample": {"limit_per_bucket": 500, "truncated": True},
                    "terminations": {"by_status": {"pending": 1}, "pending": 1},
                    "local": {"status": "ok", "segments": 3, "pending_terminations": 1,
                              "unreadable_terminations": 0, "pending_alerts": 2}}
COLLECTED = "2026-09-19T12:00:00+00:00"
FORBIDDEN_TEXT = ("docs/zeus", "숨겨진 목표 문장", "op-1", "per_host", "192", "secret-plan")


def now_of(api, offset=0.0):
    return api.datetime(2026, 9, 19, 12, tzinfo=timezone.utc) + timedelta(seconds=offset)


def monitoring_document(collected_at=COLLECTED, **sources):
    """The shape `adapters/monitoring.collect()` writes (M7 test helper)."""
    return {"schema": "harness-monitor.v1", "collected_at": collected_at,
            "scope": {"label": "repository zeus", "docker": "compose", "containers": None},
            "sources": {"database": {"status": "ok", "observed_at": collected_at, "data": {}},
                        "docker": {"status": "unavailable", "observed_at": collected_at, "error": "DockerUnavailable", "data": None},
                        "redis": {"status": "ok", "observed_at": collected_at, "data": {}},
                        "fleet": {"status": "ok", "observed_at": collected_at, "data": copy.deepcopy(FLEET_DATA)},
                        "research_programs": {"status": "ok", "observed_at": collected_at, "data": {"programs": []}},
                        "observations": {"status": "ok", "observed_at": collected_at, "data": copy.deepcopy(OBSERVATION_DATA)},
                        **sources}}


class Scratch:
    """The scenario's single temp directory; removed by `close`."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="s8fda-")).resolve()
        self.n = 0

    def path(self):
        self.n += 1
        return self.root / f"monitoring-{self.n}.json"

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def listing(self):
        return sorted((e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in self.root.iterdir())


def norm(value, root):
    """Replace the temp directory string by `<tmp>` anywhere in a result (documented rule; never masks a state, a reason or an age)."""
    text = str(root)
    if isinstance(value, str):
        TEMP_PATH_REPLACEMENTS["count"] += value.count(text)
        return value.replace(text, "<tmp>")
    if isinstance(value, dict):
        return {norm(k, root): norm(v, root) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [norm(v, root) for v in value]
    return value


def write(path, body):
    if isinstance(body, bytes):
        path.write_bytes(body)
    else:
        path.write_text(json.dumps(body, ensure_ascii=False), "utf-8")


def leaks(value):
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return [word for word in FORBIDDEN_TEXT if word in text]


def raised(fn, *args, **kwargs):
    """The type, fixed code and message of what `fn` raised (the refusal is the characterized result), or its value."""
    try:
        return {"returned": plain(fn(*args, **kwargs))}
    except Exception as exc:  # recorded, never swallowed
        return {"raised": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc)[:200]}


# ---- LABELLED doubles (M7 `tests/test_frontdesk.py`) -------------------------------------------------------------------
class FakeGit:
    """LABELLED. The M7 `FakeGit`, plus a call log and `after_run` hooks. An unexpected git call is an assertion failure."""

    def __init__(self, revision=REVISION, dirty=False):
        self.revision, self.dirty, self.workspaces, self.calls = revision, dirty, [], []

    def review_workspace(self, revision, review_id):
        self.workspaces.append((revision, review_id))
        return "/tmp/review-" + review_id

    def _git(self, *args, cwd=None, strip=True):
        self.calls.append([list(args), cwd])
        if args[:2] == ("rev-parse", "HEAD"):
            return self.revision
        if args[0] == "status":
            return "M file.py" if self.dirty else ""
        raise AssertionError("unexpected git call: " + str(args))


def executor_object(svc, answer, git=None, recorder=None, after_run=None):
    """LABELLED. The M7 `fake_executor_object`: `service`, `git` and a `_run` that records every argument and returns `answer`."""
    recorder = recorder if recorder is not None else []
    git = git or FakeGit()

    def _run(agent, key, objective, evidence, cwd, schema, read_only=False, heartbeat=None, lease=None, stage=None,
             workload="final_validation", importance=None, action=None, max_handoffs=4, delivery=None):
        recorder.append({"agent": agent, "key": key, "objective": objective, "evidence": evidence, "cwd": cwd, "schema": schema,
                         "read_only": read_only, "heartbeat": heartbeat, "lease": lease, "stage": stage, "workload": workload,
                         "importance": importance, "action": action, "max_handoffs": max_handoffs, "delivery": delivery})
        if after_run is not None:
            after_run(git)
        return copy.deepcopy(answer)

    return SimpleNamespace(service=svc, git=git, _run=_run)


def desk_task(api, w, svc, desk, session_id, intent="consult", text="지금 상태가 어때?"):
    accepted = w.submit(desk, session_id, intent=intent, text=text)
    with svc.store.transaction() as tx:
        message = tx.get("outbox", api.message_id_of(accepted["request"]["id"]))["message"]
    return accepted["request"], {"id": message["message_id"], "message": message}


def turn(api, w, intent="consult", text="지금 상태가 어때?"):
    svc, desk, session_id = w.opened()
    row, task = desk_task(api, w, svc, desk, session_id, intent=intent, text=text)
    return svc, desk, session_id, row, task


def execute(api, svc, task, answer=None, git=None, snapshot=..., heartbeat=None, after_run=None):
    """Run `execute_frontdesk` once; returns the result (or the raised refusal), the recorded `_run` calls, the git log and the stores' digests."""
    calls, git = [], git or FakeGit()
    executor = executor_object(svc, ANSWER if answer is None else answer, git, calls, after_run)
    before = base.store_digest(svc.store)
    kwargs = {} if snapshot is ... else {"snapshot": snapshot}
    outcome = raised(api.execute_frontdesk, executor, task, heartbeat, **kwargs)
    return {"outcome": outcome, "run_calls": calls, "workspaces": git.workspaces, "git_calls": git.calls,
            "store_unchanged": before == base.store_digest(svc.store)}


# ---- groups ------------------------------------------------------------------------------------------------------------
def s1_constants(api):
    return {name: api.constants[name] for name in CONSTANT_NAMES}


def s2_clean_checkout(api):
    out = {}
    for label, git in (("clean_at_expected", FakeGit()), ("dirty", FakeGit(dirty=True)), ("moved", FakeGit(revision="b" * 40)),
                       ("moved_and_dirty", FakeGit(revision="b" * 40, dirty=True)), ("empty_revision", FakeGit(revision=""))):
        out[label] = {"outcome": raised(api.clean_checkout, git, "/tmp/w", REVISION), "git_calls": git.calls}
    out["expected_other"] = {"outcome": raised(api.clean_checkout, FakeGit(), "/tmp/w", "c" * 40)}
    return out


def s3_execute(api, w):
    out = {}
    probe = {"answer": "구독 사용량은 기록되고 호출 수 상한은 적용되지 않습니다.", "objective": None, "acceptance_criteria": [], "questions": []}

    # ---- test_conversational_branch_runs_read_only_in_a_clean_checkout_at_the_request_base (both intents, an explicit snapshot)
    snapshot = {"schema": "urn:zeus:desk-monitoring:1", "availability": "observed", "marker": "explicit-snapshot"}
    case = {}
    for intent, answer in (("consult", ANSWER), ("request", {**ANSWER, "objective": "관측소 개선", "acceptance_criteria": ["관측 사실만 보고한다"],
                                                              "questions": ["범위를 넓힐까요?"], "basis_revision": "d" * 40})):
        svc, desk, session_id, row, task = turn(api, w, intent=intent)
        case[intent] = {"request": plain(row), **execute(api, svc, task, answer, snapshot=snapshot, heartbeat="heartbeat-token")}
    out["test_conversational_branch_runs_read_only_in_a_clean_checkout_at_the_request_base"] = case

    # ---- test_conversational_branch_refuses_a_dirty_or_moved_checkout (before the run) and the same after it (LABELLED)
    case = {}
    for label, git in (("dirty", FakeGit(dirty=True)), ("moved", FakeGit(revision="b" * 40))):
        svc, desk, session_id, row, task = turn(api, w)
        case[label] = execute(api, svc, task, git=git, snapshot=snapshot)
    for label, hook in (("dirty_after_run", lambda git: setattr(git, "dirty", True)),
                        ("moved_after_run", lambda git: setattr(git, "revision", "e" * 40))):
        svc, desk, session_id, row, task = turn(api, w)
        case[label] = execute(api, svc, task, snapshot=snapshot, after_run=hook)
    out["test_conversational_branch_refuses_a_dirty_or_moved_checkout"] = case

    # ---- test_conversational_branch_refuses_a_malformed_answer (and every other answer shape validate_answer refuses)
    case = {}
    for label, answer in (("blank", {"answer": "   "}), ("empty", {"answer": ""}), ("not_text", {"answer": 5}), ("objective_not_text", {"answer": "ok", "objective": 3}),
                          ("criteria_not_list", {"answer": "ok", "acceptance_criteria": "x"}), ("plain_string", "plain string"),
                          ("minimal_valid", {"answer": "답"}), ("extra_key", {**probe, "extra": 1})):
        svc, desk, session_id, row, task = turn(api, w)
        case[label] = execute(api, svc, task, answer, snapshot=snapshot)
    out["test_conversational_branch_refuses_a_malformed_answer"] = case

    # ---- LABELLED: the assignment refusals, before any workspace is taken
    case = {}
    svc, desk, session_id, row, task = turn(api, w)

    def variant(label, edit):
        broken = copy.deepcopy(task)
        edit(broken["message"])
        case[label] = execute(api, svc, broken, snapshot=snapshot)

    variant("details_absent", lambda m: m["what"]["details"].pop("frontdesk"))
    variant("details_not_a_dict", lambda m: m["what"]["details"].__setitem__("frontdesk", "x"))
    variant("base_revision_mismatch", lambda m: m["what"]["details"]["frontdesk"].__setitem__("base_revision", "f" * 40))
    variant("revision_malformed", lambda m: m["where"].__setitem__("revision", "not-a-revision"))
    variant("request_unknown", lambda m: m["what"]["details"]["frontdesk"].__setitem__("request_id", IDS.uuid()))
    variant("session_mismatch", lambda m: m["what"]["details"]["frontdesk"].__setitem__("session_id", IDS.uuid()))
    out["assignment_refusals"] = case

    # ---- LABELLED: the snapshot is carried verbatim as the evidence (explicit evidence of every kind, a falsy dict included)
    case = {}
    for label, facts in (("empty_dict", {}), ("string", "text"), ("list", [1, 2]), ("zero", 0), ("nested", {"a": {"b": [1, None]}})):
        svc, desk, session_id, row, task = turn(api, w)
        result = execute(api, svc, task, snapshot=facts)
        case[label] = {"fleet_snapshot": result["run_calls"][0]["evidence"].get("fleet_snapshot", "<absent>") if result["run_calls"] else "<no run>",
                       "outcome_keys": sorted(result["outcome"].get("returned", result["outcome"]))}
    out["snapshot_is_the_evidence_verbatim"] = case
    return out


def s4_monitoring_facts(api):
    out = {}
    now = now_of(api, 10)

    # ---- test_monitoring_facts_are_bounded_sanitized_and_dated
    facts = api.monitoring_facts(monitoring_document(), now=now)
    out["test_monitoring_facts_are_bounded_sanitized_and_dated"] = {"facts": plain(facts), "leaks": leaks(facts)}

    # ---- test_an_old_capture_is_historical_not_current (+ the exact window edges)
    case = {}
    for age in (10, 19, 19.999, 20, 20.001, 60, 600):
        collected = (now_of(api) - timedelta(seconds=age)).isoformat()
        case["age_%s" % age] = plain(api.monitoring_facts(monitoring_document(collected), now=now_of(api)))
    out["test_an_old_capture_is_historical_not_current"] = case

    # ---- test_each_source_carries_its_own_observed_at_age
    n = now_of(api)
    document = monitoring_document((n - timedelta(seconds=5)).isoformat())
    document["sources"]["fleet"]["observed_at"] = (n - timedelta(seconds=300)).isoformat()
    first = plain(api.monitoring_facts(document, now=n))
    document["sources"].pop("redis")
    out["test_each_source_carries_its_own_observed_at_age"] = {"lagging_fleet": first["sources"], "freshness": first["freshness"],
                                                              "redis_missing": plain(api.monitoring_facts(document, now=n))["sources"]["redis"]}

    # ---- test_a_malformed_capture_is_explicitly_unknown
    case = {}
    for label, document in (("string", "not a snapshot"), ("none", None), ("list", [{"schema": "harness-monitor.v1"}]),
                            ("schema_other", {"schema": "something-else.v9", "sources": {}}), ("sources_absent", {"schema": "harness-monitor.v1"}),
                            ("sources_list", {"schema": "harness-monitor.v1", "sources": ["fleet"]}), ("int", 7), ("empty_dict", {})):
        case[label] = plain(api.monitoring_facts(document, now=n))
    out["test_a_malformed_capture_is_explicitly_unknown"] = case

    # ---- test_a_malformed_nested_capture_is_unknown_evidence_and_never_raises (the M7 test passes no `now`: shape-only variant below)
    mutations = {
        "fleet_jobs_int": {"sources": {"fleet": {"status": "ok", "observed_at": None, "data": {"registered": True, "jobs": 7}}}},
        "fleet_containers_wrong": {"sources": {"fleet": {"status": "ok", "data": {"registered": True, "jobs": {"job-1": {}}, "lanes": "lane-a",
                                                                                  "budget": [1, 2], "paused": "yes", "truncated": "no"}}}},
        "observations_wrong": {"sources": {"observations": {"status": "ok", "data": {"local": "ok", "events": 3, "terminations": None, "sample": []}}}},
        "envelopes_not_dicts": {"sources": {"fleet": ["not an envelope"], "observations": 5}},
        "collected_at_dict": {"collected_at": {"at": COLLECTED}},
        "scope_none_database_none": {"scope": None, "sources": {"database": None}}}
    case, shapes = {}, {}
    for label, mutation in mutations.items():
        document = monitoring_document()
        document.update({k: v for k, v in mutation.items() if k != "sources"})
        document["sources"].update(mutation.get("sources") or {})
        case[label] = plain(api.monitoring_facts(document, now=n))
        unclocked = api.monitoring_facts(document)
        shapes[label] = {"schema": unclocked["schema"], "freshness_known": unclocked["freshness"] in {"current", "stale", "unknown"},
                         "fleet_dict": isinstance(unclocked["fleet"], dict), "observations_dict": isinstance(unclocked["observations"], dict),
                         "fleet_availability_known": unclocked["fleet"]["availability"] in {"observed", "unknown"},
                         "leaks": leaks(unclocked)}
    out["test_a_malformed_nested_capture_is_unknown_evidence_and_never_raises"] = {"with_now": case, "without_now_shape_only": shapes}

    # ---- test_a_malformed_container_is_unknown_not_zero
    document = monitoring_document()
    document["sources"]["fleet"]["data"] = {**FLEET_DATA, "jobs": {"job-1": {}}, "lanes": 3, "paused": "yes", "truncated": "no"}
    out["test_a_malformed_container_is_unknown_not_zero"] = plain(api.monitoring_facts(document, now=n)["fleet"])

    # ---- test_an_unusable_capture_time_is_unknown_freshness
    case = {}
    for label, value in (("yesterday_ko", "어제"), ("none", None), ("naive", "2026-09-19T12:00:00"), ("int", 12), ("empty", ""),
                         ("date_only", "2026-09-19"), ("offset", "2026-09-19T21:00:00+09:00"), ("z", "2026-09-19T12:00:00Z")):
        case[label] = plain(api.monitoring_facts(monitoring_document(value), now=n))
    out["test_an_unusable_capture_time_is_unknown_freshness"] = case

    # ---- test_a_capture_from_the_future_is_not_reported_as_current
    case = {}
    for offset in (4, 5, 5.001, 60):
        case["ahead_%s" % offset] = plain(api.monitoring_facts(monitoring_document((n + timedelta(seconds=offset)).isoformat()), now=n))
    out["test_a_capture_from_the_future_is_not_reported_as_current"] = case

    # ---- test_accounting_modes_and_their_explanations_never_silently_claim_a_ceiling
    case = {}
    for label, accounting, budget_mode in (("sub_sub", "subscription", "subscription"), ("sub_finite", "subscription", "finite"),
                                          ("finite_finite", "finite", "finite"), ("absent_absent", "absent", "absent"),
                                          ("made_up", "made-up", "made-up"), ("null_absent", None, "absent"), ("absent_null", "absent", None),
                                          ("sub_absent", "subscription", "absent"), ("absent_sub", "absent", "subscription"),
                                          ("finite_sub", "finite", "subscription")):
        data = {**copy.deepcopy(FLEET_DATA), "budget": {"per_host": 1, "total": 1}}
        if accounting == "absent":
            data.pop("accounting_mode")
        else:
            data["accounting_mode"] = accounting
        if budget_mode != "absent":
            data["budget"]["mode"] = budget_mode
        document = monitoring_document()
        document["sources"]["fleet"] = {"status": "ok", "observed_at": document["collected_at"], "data": data}
        fleet = plain(api.monitoring_facts(document, now=n)["fleet"])
        case[label] = {"fleet": fleet, "claims_no_ceiling": "no call-count ceiling is applied" in fleet["accounting_note"]}
    out["test_accounting_modes_and_their_explanations_never_silently_claim_a_ceiling"] = case

    # ---- test_an_unavailable_fleet_or_observation_source_is_unknown_not_healthy
    document = monitoring_document()
    document["sources"]["fleet"] = {"status": "unavailable", "observed_at": document["collected_at"], "error": "OperationalError", "data": None}
    document["sources"]["observations"] = {"status": "ok", "observed_at": document["collected_at"], "data": None}
    out["test_an_unavailable_fleet_or_observation_source_is_unknown_not_healthy"] = {
        "fleet": plain(api.monitoring_facts(document, now=n)["fleet"]), "observations": plain(api.monitoring_facts(document, now=n)["observations"])}

    # ---- test_an_unregistered_fleet_makes_no_ceiling_claim
    document = monitoring_document()
    document["sources"]["fleet"]["data"] = {"schema": "urn:zeus:fleet-status:1", "registered": False, "lanes": [], "jobs": []}
    out["test_an_unregistered_fleet_makes_no_ceiling_claim"] = plain(api.monitoring_facts(document, now=n)["fleet"])

    out["labelled_fleet_branches"] = fleet_branches(api, n)
    out["labelled_observation_branches"] = observation_branches(api, n)
    out["labelled_source_branches"] = source_branches(api, n)
    out["labelled_naive_now"] = naive_now(api)
    return out


def with_fleet(api, now, fleet_source):
    document = monitoring_document()
    document["sources"]["fleet"] = fleet_source
    return plain(api.monitoring_facts(document, now=now)["fleet"])


def fleet_branches(api, now):
    case = {}
    ok = lambda data: {"status": "ok", "observed_at": COLLECTED, "data": data}  # noqa: E731
    jobs = [{"status": "running" if i % 3 else "queued"} for i in range(250)]
    lanes = [{"id": "l%d" % i, "active_job": "j" if i % 2 else None} for i in range(100)]
    case["bounded_jobs_and_lanes"] = with_fleet(api, now, ok({"registered": True, "jobs": jobs, "lanes": lanes, "accounting_mode": "finite"}))
    case["exact_limits"] = with_fleet(api, now, ok({"registered": True, "jobs": jobs[:200], "lanes": lanes[:64]}))
    case["non_dict_entries_dropped"] = with_fleet(api, now, ok({"registered": True, "jobs": [1, "x", None, {"status": "done"}], "lanes": ["a", {"active_job": "j"}]}))
    case["job_status_labels"] = with_fleet(api, now, ok({"registered": True, "jobs": [
        {"status": 7}, {"status": None}, {}, {"status": "Weird Status!"}, {"status": "x" * 100}, {"status": "ok"}, {"status": "ok"}]}))
    for label, value in (("true", True), ("negative", -1), ("string", "2"), ("zero", 0), ("three", 3), ("float", 2.0)):
        case["max_parallel_" + label] = with_fleet(api, now, ok({"registered": True, "max_parallel": value}))["max_parallel"]
    for label, value in (("true", True), ("false", False), ("one", 1), ("none", None)):
        case["flags_" + label] = {k: v for k, v in with_fleet(api, now, ok({"registered": True, "paused": value, "truncated": value})).items()
                                  if k in ("paused", "jobs_truncated")}
    case["budget_not_a_dict"] = with_fleet(api, now, ok({"registered": True, "budget": "x", "accounting_mode": "subscription"}))
    case["registered_not_true"] = {label: with_fleet(api, now, ok({"registered": value})) for label, value in (("yes", "yes"), ("one", 1), ("none", None))}
    case["source_failed_error_labels"] = {
        label: with_fleet(api, now, {"status": "unavailable", "error": error})
        for label, error in (("type", "OperationalError"), ("unsafe", "Err: secret=hunter2 at /srv/x"), ("long", "E" * 300), ("int", 7), ("none", None))}
    case["source_shapes"] = {label: with_fleet(api, now, value) for label, value in (("none", None), ("string", "x"), ("list", []), ("status_other", {"status": "ok2", "data": {}}),
                                                                                    ("data_not_dict", {"status": "ok", "data": []}))}
    return case


def observation_branches(api, now):
    case = {}

    def observed(source):
        document = monitoring_document()
        document["sources"]["observations"] = source
        return plain(api.monitoring_facts(document, now=now)["observations"])

    ok = lambda data: {"status": "ok", "observed_at": COLLECTED, "data": data}  # noqa: E731
    case["counters"] = {label: observed(ok(data)) for label, data in (
        ("empty", {}), ("bool_counts", {"local": {"pending_alerts": True, "pending_terminations": False}, "events": {"total": True}}),
        ("negative", {"local": {"pending_alerts": -1}, "terminations": {"pending": -5}, "events": {"total": -1, "high_severity_total": -2}}),
        ("float", {"local": {"pending_alerts": 1.5}}), ("string", {"local": {"status": "Bad Status!", "pending_alerts": "2"}}),
        ("local_status_long", {"local": {"status": "s" * 90}}), ("sample_truncated_flags", {"sample": {"truncated": False}}),
        ("sample_truncated_str", {"sample": {"truncated": "yes"}}))}
    case["source_shapes"] = {label: observed(value) for label, value in (
        ("none", None), ("string", "x"), ("failed", {"status": "unavailable", "error": "OSError"}), ("failed_unsafe_error", {"status": "unavailable", "error": "a b/c"}),
        ("failed_not_text_error", {"status": "unavailable", "error": 3}), ("data_none", {"status": "ok", "data": None}))}
    return case


def source_branches(api, now):
    case = {}
    for label, sources in (
            ("only_required", {"database": {"status": "ok", "observed_at": COLLECTED}, "docker": {"status": "ok", "observed_at": COLLECTED},
                               "redis": {"status": "ok", "observed_at": COLLECTED}}),
            ("unknown_name_ignored", {"zzz": {"status": "ok", "observed_at": COLLECTED}}),
            ("status_not_text", {"database": {"status": ["ok"], "observed_at": COLLECTED}}),
            ("error_unsafe", {"database": {"status": "unavailable", "error": "boom: s3cr3t!", "observed_at": COLLECTED}}),
            ("error_long", {"database": {"status": "unavailable", "error": "E" * 300}}),
            ("status_unsafe", {"database": {"status": "Not OK!", "observed_at": COLLECTED}}),
            ("age_fraction", {"database": {"status": "ok", "observed_at": "2026-09-19T11:59:58.5+00:00"}}),
            ("no_sources", {})):
        document = {"schema": "harness-monitor.v1", "collected_at": COLLECTED, "sources": sources}
        facts = plain(api.monitoring_facts(document, now=now))
        case[label] = {"sources": facts["sources"], "fleet": facts["fleet"], "observations": facts["observations"]}
    return case


def naive_now(api):
    naive = api.datetime(2026, 9, 19, 12)
    return {"facts": raised(api.monitoring_facts, monitoring_document(), naive),
            "facts_malformed_document_naive_now": raised(api.monitoring_facts, "x", naive)}


PAYLOADS = {
    "empty": b"", "truncated": b'{"schema": "harness-monitor.v1", "sources": ', "bom": b'\xef\xbb\xbf{"schema": "harness-monitor.v1", "sources": {}}',
    "invalid_utf8": b'{"schema": "harness-monitor.v1", "sources": {}, "label": "\xff\xfe"}',
    "not_json": b"{not json", "duplicate_key": b'{"schema": "harness-monitor.v1", "sources": {}, "sources": {}}',
    "duplicate_nested": b'{"schema": "harness-monitor.v1", "sources": {"a": {"b": 1, "b": 2}}}',
    "nan": b'{"schema": "harness-monitor.v1", "sources": {"a": NaN}}', "infinity": b'{"schema": "harness-monitor.v1", "collected_at": Infinity, "sources": {}}',
    "deep_nesting": b'{"schema": "harness-monitor.v1", "sources": ' + b"[" * 20000 + b"]" * 20000 + b"}",
    "root_array": b"[]", "root_string": b'"harness-monitor.v1"', "root_null": b"null", "root_number": b"7",
    "schema_absent": b'{"sources": {}}', "schema_other": b'{"schema": "harness-monitor.v2", "sources": {}}',
    "sources_absent": b'{"schema": "harness-monitor.v1"}', "sources_array": b'{"schema": "harness-monitor.v1", "sources": []}',
    "sources_null": b'{"schema": "harness-monitor.v1", "sources": null}', "whitespace_only": b"   \n",
    "trailing_garbage": b'{"schema": "harness-monitor.v1", "sources": {}} x',
    "sources_empty_with_collected_at": b'{"schema": "harness-monitor.v1", "collected_at": "2026-09-19T11:59:59+00:00", "sources": {}}'}


def s5_monitoring_evidence(api, scratch):
    out = {}
    n = now_of(api)

    def evidence(body, now=n, path=None, text=False):
        path = path or scratch.path()
        write(path, body)
        return norm(plain(api.monitoring_evidence(str(path) if text else path, now=now)), scratch.root)

    # ---- the capture on disk, by age
    out["test_the_execution_helper_carries_the_owner_runtime_capture_as_evidence"] = {
        "evidence": evidence(monitoring_document((n - timedelta(seconds=10)).isoformat())),
        "path_as_str": evidence(monitoring_document((n - timedelta(seconds=10)).isoformat()), text=True)}
    case = {}
    for age in (10, 19, 20, 60, 600, -4, -5.001, -60):
        case["age_%s" % age] = evidence(monitoring_document((n - timedelta(seconds=age)).isoformat()))
    out["captures_by_age"] = case

    # ---- test_the_desk_and_the_readiness_endpoint_agree_on_one_freshness_rule
    case = {}
    for age in (10, 19, 20, 60, 600):
        path = scratch.path()
        write(path, monitoring_document((n - timedelta(seconds=age)).isoformat()))
        answer = api.readiness(path, now=n)
        facts = api.monitoring_evidence(path, now=n)
        case["age_%d" % age] = {"desk_current": facts["freshness"] == "current", "readiness_state": answer["snapshot"]["state"],
                                "agree": (facts["freshness"] == "current") is (answer["snapshot"]["state"] == "fresh")}
    out["test_the_desk_and_the_readiness_endpoint_agree_on_one_freshness_rule"] = case

    # ---- test_a_missing_or_unreadable_capture_never_fails_the_turn (+ the malformed payloads)
    missing = scratch.path()
    out["test_a_missing_or_unreadable_capture_never_fails_the_turn"] = {
        "missing": norm(plain(api.monitoring_evidence(missing, now=n)), scratch.root),
        "not_json": evidence(PAYLOADS["not_json"]), "duplicate_key": evidence(PAYLOADS["duplicate_key"]), "nan": evidence(PAYLOADS["nan"])}
    out["malformed_payloads"] = {label: evidence(body) for label, body in PAYLOADS.items()}

    # ---- test_an_oversized_or_unopenable_capture_is_unknown
    limit = api.constants["MONITORING_MAX_BYTES"]
    valid = json.dumps(monitoring_document(), ensure_ascii=False).encode("utf-8")
    case = {"override_10": None}
    path = scratch.path()
    write(path, monitoring_document())
    with api.max_bytes(10):
        case["override_10"] = norm(plain(api.monitoring_evidence(path, now=n)), scratch.root)
    case["limit_plus_one_spaces"] = evidence(b" " * (limit + 1))
    case["limit_plus_one_valid_prefix"] = evidence(valid + b" " * (limit + 1 - len(valid)))
    case["at_limit_valid"] = {k: v for k, v in evidence(valid.ljust(limit, b" ")).items() if k in ("availability", "reason_code", "freshness", "age_seconds")}
    case["at_limit_spaces"] = evidence(b" " * limit)
    directory = scratch.path()
    directory.mkdir()
    case["directory_in_place"] = norm(plain(api.monitoring_evidence(directory, now=n)), scratch.root)
    case["directory_as_the_root"] = norm(plain(api.monitoring_evidence(scratch.root, now=n)), scratch.root)
    out["test_an_oversized_or_unopenable_capture_is_unknown"] = case

    # ---- LABELLED: a naive now is not a raised conversation failure; the default now keeps the shape; nothing is written
    path = scratch.path()
    write(path, monitoring_document())
    out["naive_now_is_unknown_not_raised"] = norm(plain(api.monitoring_evidence(path, now=api.datetime(2026, 9, 19, 12))), scratch.root)
    unclocked = api.monitoring_evidence(path)
    out["now_default_shape_only"] = {"schema": unclocked["schema"], "keys": sorted(unclocked), "availability": unclocked["availability"],
                                     "freshness_known": unclocked["freshness"] in {"current", "stale", "unknown"}}
    before = scratch.listing()
    for _ in range(3):
        api.monitoring_evidence(path, now=n)
        api.monitoring_evidence(scratch.path(), now=n)
    out["reads_write_nothing"] = {"unchanged": before == scratch.listing()}
    return out


def s6_snapshot_none(api, scratch, w):
    """M7 only: `execute_frontdesk(..., snapshot=None)` self-reads the owner's runtime capture through the default `snapshot_path()`.
    The target refuses `snapshot=None` (V17 R-f1: composition supplies the evidence): intended difference 1, the whole group is absent there."""
    out = {}
    seam = api.default_path
    n = seam.collected(5)
    path = scratch.root / "monitoring.json"
    with seam.install(path):
        # ---- test_the_execution_helper_carries_the_owner_runtime_capture_as_evidence / ..._reports_a_malformed_capture_as_unknown_without_failing /
        # ---- ..._reports_an_absent_capture_as_unknown: `snapshot` omitted, the runtime file read through the default path
        for label, body in (("owner_capture", monitoring_document(n)), ("malformed_capture", b'{"schema": "harness-monitor.v1", "sources": 3}'),
                            ("absent_capture", None)):
            if body is None:
                path.unlink(missing_ok=True)
            else:
                write(path, body)
            svc, desk, session_id, row, task = turn(api, w)
            result = execute(api, svc, task)
            out[label] = norm({"fleet_snapshot": result["run_calls"][0]["evidence"]["fleet_snapshot"], "answer": result["outcome"]["returned"]["answer"],
                               "store_unchanged": result["store_unchanged"]}, scratch.root)
        # `snapshot=None` passed explicitly is the omitted default
        write(path, monitoring_document(n))
        svc, desk, session_id, row, task = turn(api, w)
        explicit_none = execute(api, svc, task, snapshot=None)
        svc, desk, session_id, row, task = turn(api, w)
        omitted = execute(api, svc, task)
        keys = ("availability", "fleet", "freshness")
        out["explicit_none_equals_omitted"] = {"same_fleet_and_availability": [explicit_none["run_calls"][0]["evidence"]["fleet_snapshot"][k] for k in keys]
                                               == [omitted["run_calls"][0]["evidence"]["fleet_snapshot"][k] for k in keys]}
    return out


def s7_default_path(api, scratch, w):
    """M7 only: `snapshot_path()` (the runtime file, through the composition's `runtime_dir`) and `monitoring_evidence()` with no path.
    The target has neither (V17 R-m1: the path is required, composition owns `runtime_dir`): intended difference 2, the whole group is absent there."""
    out = {"has_snapshot_path": True}
    seam = api.default_path
    n = seam.collected(5)
    path = scratch.root / "monitoring.json"
    with seam.install(path):
        out["snapshot_path_name"] = seam.current().name
        write(path, monitoring_document(n))
        out["monitoring_evidence_no_path"] = norm(plain(api.monitoring_evidence()), scratch.root)
        out["monitoring_evidence_path_none"] = norm(plain(api.monitoring_evidence(None)), scratch.root)
        # the default path is not touched when the snapshot is explicit
        write(path, b"{not json")
        svc, desk, session_id, row, task = turn(api, w)
        explicit = execute(api, svc, task, snapshot={"marker": "explicit"})
        out["explicit_snapshot_ignores_the_default_path"] = explicit["run_calls"][0]["evidence"]["fleet_snapshot"]
        # a failing default path (an exception from the configuration) is explicit unknown evidence, never a raised turn failure
        out["default_path_raises"] = norm(plain(seam.raising(RuntimeError("configuration failure"))), scratch.root)
    return out


M7_TESTS = {
    "test_the_desk_output_schema_requires_every_property_and_keeps_null_and_empty_values": {
        "s1_constants": "the schema, its required list and the objective type are recorded directly; completed_output (adapters.execution_output) "
                        "is another module's, not this family's; validate_answer's refusals are in s3_execute (the malformed answers)"},
    "test_conversational_branch_runs_read_only_in_a_clean_checkout_at_the_request_base": "s3_execute (same name, both intents, explicit snapshot)",
    "test_conversational_branch_refuses_a_dirty_or_moved_checkout": "s3_execute (same name; after-run variants added)",
    "test_conversational_branch_refuses_a_malformed_answer": "s3_execute (same name; 8 answer shapes)",
    "test_monitoring_facts_are_bounded_sanitized_and_dated": "s4_monitoring_facts (same name, fixed now)",
    "test_an_old_capture_is_historical_not_current": "s4_monitoring_facts (same name, 7 ages)",
    "test_the_desk_and_the_readiness_endpoint_agree_on_one_freshness_rule": "s5_monitoring_evidence (same name)",
    "test_each_source_carries_its_own_observed_at_age": "s4_monitoring_facts (same name)",
    "test_a_malformed_capture_is_explicitly_unknown": "s4_monitoring_facts (same name, 8 documents)",
    "test_a_malformed_nested_capture_is_unknown_evidence_and_never_raises": "s4_monitoring_facts (same name; with a fixed now and the M7 no-now shape)",
    "test_a_malformed_container_is_unknown_not_zero": "s4_monitoring_facts (same name)",
    "test_an_unusable_capture_time_is_unknown_freshness": "s4_monitoring_facts (same name, 8 values)",
    "test_a_capture_from_the_future_is_not_reported_as_current": "s4_monitoring_facts (same name, 4 offsets)",
    "test_accounting_modes_and_their_explanations_never_silently_claim_a_ceiling": "s4_monitoring_facts (same name, 10 combinations)",
    "test_an_unavailable_fleet_or_observation_source_is_unknown_not_healthy": "s4_monitoring_facts (same name)",
    "test_an_unregistered_fleet_makes_no_ceiling_claim": "s4_monitoring_facts (same name)",
    "test_a_missing_or_unreadable_capture_never_fails_the_turn": "s5_monitoring_evidence (same name, plus 22 malformed payloads)",
    "test_an_oversized_or_unopenable_capture_is_unknown": "s5_monitoring_evidence (same name; a real oversized file as well)",
    "test_the_execution_helper_carries_the_owner_runtime_capture_as_evidence": "s5_monitoring_evidence (the capture on disk as evidence) and s3_execute "
                                                                               "(explicit snapshot); s6_snapshot_none (M7 self-read, intended difference)",
    "test_the_execution_helper_reports_a_malformed_capture_as_unknown_without_failing": "s6_snapshot_none (M7 self-read, intended difference); "
                                                                                       "s5_monitoring_evidence.malformed_payloads (the evidence itself)",
    "test_the_execution_helper_reports_an_absent_capture_as_unknown": "s6_snapshot_none (M7 self-read, intended difference); "
                                                                      "s5_monitoring_evidence (missing path)",
}


def run(api) -> dict:
    api.reset()
    world = World(api)
    scratch = Scratch()
    try:
        result = {"s1_constants": s1_constants(api), "s2_clean_checkout": s2_clean_checkout(api), "s3_execute": s3_execute(api, world),
                  "s4_monitoring_facts": s4_monitoring_facts(api), "s5_monitoring_evidence": s5_monitoring_evidence(api, scratch)}
        if api.default_path is not None:
            result["s6_snapshot_none"] = s6_snapshot_none(api, scratch, world)
            result["s7_default_path"] = s7_default_path(api, scratch, world)
    finally:
        scratch.close()
    result["s8_m7_tests"] = M7_TESTS
    result["temp_path_replacements"] = TEMP_PATH_REPLACEMENTS["count"]
    result["cases_per_group"] = {name: len(result[name]) for name in ("s1_constants", "s2_clean_checkout", "s3_execute", "s4_monitoring_facts",
                                                                      "s5_monitoring_evidence")}
    return result
