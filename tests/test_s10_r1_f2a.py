"""S10 round-1 correction F2-A (FLEET-REBUILD-S10-ACCEPT F2 rows 3 and 4): CI timing through the CI adapter and the cleanup
lifecycle wired to the process observer. Every boundary is driven through its real builder with fixture stores and transports and a
recording `CatalogCheckingObserver` (a non-catalog attribute fails the test); no provider, Git, PostgreSQL or live Docker.

- CI: `GitHubDelivery.observe` (a fixture `gh` runner) -> `CiObservation.observe_ci` -> the real `DeliveryState.emit_check`.
- Cleanup, container path: `operation.build_executor` over a real `IsolatedWorker` (the ported `FakeDocker`) -> the worker's own
  `IsolatedClaudeRuntime.run`.
- Cleanup, process path: `process_entries.isolated_worker_reconcile` (the `isolated_worker_runs reconcile` operator step).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "ported"))
from m7_containers import host, install_fake, iw  # noqa: E402
from test_isolated_worker import IMAGE, SCHEMA, TOKEN, FakeDocker  # noqa: E402
from test_s10_a5_2_seams import observed  # noqa: E402

from codex_harness import composition  # noqa: E402
from codex_harness.composition import configuration, operation, process_entries  # noqa: E402
from codex_harness.delivery.adapters.host_delivery import (  # noqa: E402
    GitHubDelivery,
    check_durations,
    normalize_checks,
)
from codex_harness.delivery.application.host_delivery.stages.ci import CiObservation  # noqa: E402
from codex_harness.delivery.application.host_delivery.state import DeliveryState  # noqa: E402
from codex_harness.delivery.domain.host_delivery import ci_verdict  # noqa: E402
from codex_harness.execution.adapters.containers import launcher  # noqa: E402
from codex_harness.observation.domain.feature_registry import FEATURES  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402


def ref(value):
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


# ----- CI timing ----------------------------------------------------------------------------------------------------------
HEAD = "a" * 40
T0 = "2026-10-04T12:00:00Z"
REQUIRED = ["test (3.12)", "lint", "tests", "docs", "naive", "snake", "stale"]
PLAN = {"plan_id": "p1", "release_id": "r1", "target_id": "t1", "required_checks": REQUIRED}
ROWS = [
    {"name": "test (3.12)", "status": "COMPLETED", "conclusion": "SUCCESS", "startedAt": T0, "completedAt": "2026-10-04T12:06:52Z"},
    {"name": "lint", "status": "COMPLETED", "conclusion": "FAILURE", "startedAt": T0, "completedAt": "2026-10-04T12:00:05.900+00:00"},
    # an unfinished check: GitHub reports the zero time as its completion
    {"name": "tests", "status": "IN_PROGRESS", "conclusion": "", "startedAt": T0, "completedAt": "0001-01-01T00:00:00Z"},
    {"name": "naive", "status": "COMPLETED", "conclusion": "SUCCESS", "startedAt": "2026-10-04T12:00:00", "completedAt": T0},
    {"name": "snake", "status": "COMPLETED", "conclusion": "SUCCESS", "started_at": T0, "completed_at": "2026-10-04T13:00:00Z"},
    {"name": "stale", "status": "COMPLETED", "conclusion": "SUCCESS"},  # no timestamps at all
]  # `docs` is absent from the rollup


def gh(rows):
    body = [{"number": 7, "url": "u", "headRefOid": HEAD, "state": "OPEN", "mergeCommit": None, "statusCheckRollup": rows}]

    def runner(argv, *, timeout):
        assert argv[:3] == ["gh", "pr", "list"] and "statusCheckRollup" in argv[-1]
        return subprocess.CompletedProcess(argv, 0, json.dumps(body), "")
    return GitHubDelivery(SimpleNamespace(remote="o/r"), runner=runner)


def delivery(observer, rows=ROWS):
    """The real stage over the real adapter and the real DeliveryState; a MemoryStore holding the candidate."""
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put("releases", "r1", {"candidate": {"branch": "b", "revision": HEAD}})
    state = DeliveryState(store, observer=observer, clock=lambda: "2026-10-04T12:10:00Z")
    intent = {"id": "i1", "stage": "awaiting_ci", "head": HEAD, "stage_entered_at": "2026-10-04T12:00:00Z",
              "stage_deadline": "2999-01-01T00:00:00Z", "attempts": 0}
    return CiObservation(store, github=gh(rows), state=state), intent, store


def ci_events(recorder):
    return {attrs["check"]: attrs for kind, _, attrs in recorder.events if kind == "operations.ci_observed"}


def test_ci_observed_carries_the_adapters_per_check_duration_and_null_where_unknown():
    recorder, observer = observed()
    stage, intent, _ = delivery(observer)
    stage.observe_ci(PLAN, intent, None)
    events = ci_events(recorder)
    assert {name: events[ref(name)]["duration_seconds"] for name in REQUIRED} == {
        "test (3.12)": 412, "lint": 5, "tests": None, "docs": None, "naive": None, "snake": 3600, "stale": None}
    assert [events[ref(name)]["conclusion"] for name in REQUIRED] == [
        "success", "failure", "pending", "other", "success", "success", "success"]


def test_the_verdict_and_the_normalized_rows_are_unchanged_and_the_timing_is_a_side_mapping():
    observed_pr = gh(ROWS).observe({"branch": "b", "revision": HEAD})
    assert observed_pr["checks"] == normalize_checks(ROWS)
    assert all(set(row) == {"name", "state"} for row in observed_pr["checks"])
    assert observed_pr["check_durations"] == {"test (3.12)": 412, "lint": 5, "snake": 3600}
    assert ci_verdict(REQUIRED, observed_pr["checks"], HEAD, observed_head=observed_pr["head"]) == ci_verdict(
        REQUIRED, normalize_checks(ROWS), HEAD, observed_head=HEAD)
    untimed = gh([{"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"}]).observe({"branch": "b", "revision": HEAD})
    assert set(untimed) == {"number", "url", "head", "state", "merged_revision", "checks"}  # the legacy shape: no extra key


def test_the_stage_result_and_the_store_are_the_same_with_and_without_an_observer():
    _, observer = observed()
    watched, watched_intent, watched_store = delivery(observer)
    plain, plain_intent, plain_store = delivery(None)
    assert watched.observe_ci(PLAN, watched_intent, None) == plain.observe_ci(PLAN, plain_intent, None)
    with watched_store.transaction() as left, plain_store.transaction() as right:
        assert left.get("host_delivery_intents", "i1") == right.get("host_delivery_intents", "i1")


def test_a_port_that_reports_no_timing_emits_null_durations():
    recorder, observer = observed()
    stage, intent, _ = delivery(observer)
    stage.github = SimpleNamespace(observe=lambda candidate: {
        "head": HEAD, "checks": normalize_checks(ROWS)})  # the M7 fake's shape: no `check_durations`
    stage.observe_ci(PLAN, intent, None)
    assert {attrs["duration_seconds"] for attrs in ci_events(recorder).values()} == {None}


@pytest.mark.parametrize("started,completed,expected", [
    (T0, "2026-10-04T12:00:00.999Z", 0),                    # whole seconds, floored
    (T0, "2026-10-04T11:59:59Z", None),                     # completion before start
    ("not a time", T0, None), (T0, "", None), (None, T0, None),
    ("2026-10-04T12:00:00+02:00", "2026-10-04T10:00:30Z", 30),  # offsets are honoured
    ("2026-10-04T12:00:00", "2026-10-04T12:00:30", None),   # both naive
])
def test_check_durations_needs_both_timezone_aware_timestamps(started, completed, expected):
    row = {"name": "c", "status": "COMPLETED", "conclusion": "SUCCESS", "startedAt": started, "completedAt": completed}
    assert check_durations([row]) == ({} if expected is None else {"c": expected})


def test_check_durations_ignores_unusable_rows_and_the_later_row_of_a_name_wins():
    done = {"status": "COMPLETED", "conclusion": "SUCCESS"}
    assert check_durations(None) == {} and check_durations(["x", {"state": "SUCCESS"}, {"name": ""}]) == {}
    first = {**done, "name": "c", "startedAt": T0, "completedAt": "2026-10-04T12:00:10Z"}
    rerun = {**done, "name": "c", "startedAt": T0, "completedAt": "2026-10-04T12:00:20Z"}
    assert check_durations([first, rerun]) == {"c": 20}
    assert check_durations([first, {**done, "name": "c"}]) == {}  # a later unknown must not keep the earlier timing
    legacy = {"context": "c", "state": "SUCCESS", "startedAt": T0}  # a status context carries no completion
    assert check_durations([legacy]) == {}


# ----- cleanup: the executor-built container path ---------------------------------------------------------------------------
@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime"), "ZEUS_COMPOSITION_PROFILE": "development"}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    return values


@pytest.fixture
def config():
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    config["limits"] = {**config["limits"], "inner_grace_seconds": 1, "cleanup_seconds": 2}
    return config


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@localhost", *args],
                   capture_output=True, text=True, check=True)


def candidate(root):
    repo = root / "candidate"
    repo.mkdir()
    git(repo, "init", "-q")
    for name, body in (("kept.txt", "original\n"), ("gone.txt", "bye\n"), ("src/pkg/mod.py", "X = 1\n")):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(body, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def worker_run(root, config, monkeypatch, *, observer=None, through_builder=True):
    """One container run of a real `IsolatedWorker` over the fake Docker; `through_builder=False` is the legacy worker that no
    composition touched. Returns (the result, the run record's states, the worker, the executor or None)."""
    root.mkdir()
    fake = FakeDocker(root)
    install_fake(monkeypatch, fake)
    monkeypatch.setenv(iw.TOKEN_NAME, TOKEN)
    worker = launcher.IsolatedWorker(config, root / "iw", host=host())
    executor = None
    if through_builder:
        service = composition.ServiceHandle(MemoryStore(), packaged_organization())
        executor = operation.build_executor(service, observer=observer, isolation=worker, evidence_profile=None,
                                            knowledge=False, profile="development")
        assert executor.isolation is worker
    runtime = worker.runtime(model="fable", runtime={}, max_budget_usd=1.0, settings_document=None)
    with runtime as opened:
        result = opened.run("do it", str(candidate(root)), SCHEMA, 20)
    states = [step["state"] for step in iw.run_records(root / "iw" / "runs")[-1]["lifecycle"]]
    return result, states, worker, executor


def cleanup(recorder):
    return [attrs for kind, _, attrs in recorder.events if kind == "operations.cleanup_recorded"]


def test_the_executor_built_container_path_records_one_removed_cleanup(tmp_path, settings, config, monkeypatch):
    recorder, observer = observed()
    result, states, worker, executor = worker_run(tmp_path / "w", config, monkeypatch, observer=observer)
    assert worker.observer is observer and executor.observer is observer
    assert result["isolation"]["cleanup"]["removed"] is True
    assert cleanup(recorder) == [{"resource": "container", "cleanup_outcome": "removed", "cleanup_reason": "completed"}]
    assert states[-2:] == ["evidence_retained", "removed"]


def test_the_container_run_is_the_same_with_and_without_the_observer(tmp_path, settings, config, monkeypatch):
    _, observer = observed()
    watched, watched_states, _, _ = worker_run(tmp_path / "a", config, monkeypatch, observer=observer)
    plain, plain_states, worker, _ = worker_run(tmp_path / "b", config, monkeypatch, through_builder=False)
    assert worker.observer is None and plain_states == watched_states
    assert plain["answer"] == watched["answer"] and plain["isolation"]["cleanup"]["removed"] is True
    assert plain["isolation"]["import"]["added"] == watched["isolation"]["import"]["added"]


def test_build_executor_leaves_an_isolation_that_already_has_an_observer_and_none_stays_none(tmp_path, settings, config):
    _, mine = observed()
    _, other = observed()
    service = composition.ServiceHandle(MemoryStore(), packaged_organization())
    worker = launcher.IsolatedWorker(config, tmp_path / "iw", host=host())
    worker.observer = mine
    operation.build_executor(service, observer=other, isolation=worker, evidence_profile=None, knowledge=False, profile="development")
    assert worker.observer is mine
    assert operation.build_executor(service, observer=other, isolation=None, evidence_profile=None, knowledge=False,
                                    profile="development").isolation is None


# ----- cleanup: the `isolated_worker_runs reconcile` process path --------------------------------------------------------------
def run_record(directory, **row):
    directory.mkdir()
    stop = {"confirmed": True, "client_confirmed": True}
    body = {"run_id": "r1", "role": "worker", "record": str(directory / "run.json"), "container": "c1", "image": "i",
            "state": "stop_unconfirmed", "lifecycle": [{"state": "stop_confirmed", "stop": stop}], **row}
    (directory / "run.json").write_text(json.dumps(body))
    return directory


def listing(monkeypatch, stdout):
    calls = []

    def docker(binary, args, *, timeout, env=None):
        calls.append([binary, *args])
        return subprocess.CompletedProcess([binary, *args], 0, stdout, "")
    monkeypatch.setattr(process_entries, "_docker", docker)
    return calls


def test_the_reconcile_step_passes_its_runner_the_argv_the_ledger_calls_it_with(tmp_path, monkeypatch):
    calls = listing(monkeypatch, "")
    out = process_entries.isolated_worker_reconcile(run_record(tmp_path / "r"), observer=observed()[1])
    assert out == {"reconciled": True, "run_id": "r1"} and calls[0][:3] == ["docker", "ps", "-a"]


def test_the_reconcile_step_records_the_cleanup_decision_through_the_observer_it_holds(tmp_path, monkeypatch):
    listing(monkeypatch, "")
    recorder, observer = observed()
    assert process_entries.isolated_worker_reconcile(run_record(tmp_path / "a"), observer) == {"reconciled": True, "run_id": "r1"}
    assert cleanup(recorder) == [{"resource": "container", "cleanup_outcome": "removed", "cleanup_reason": "completed"}]
    listing(monkeypatch, "abc")
    held = process_entries.isolated_worker_reconcile(run_record(tmp_path / "b"), observer)
    assert held["reason"] == "container_still_present" and cleanup(recorder)[1:] == [
        {"resource": "container", "cleanup_outcome": "held", "cleanup_reason": "still_in_use"}]


def test_the_reconcile_step_builds_its_own_spool_observer_when_it_holds_none(tmp_path, settings, monkeypatch):
    listing(monkeypatch, "")
    built = []
    from codex_harness.composition import observation
    real = observation.build_observer

    def build(store, component, **kwargs):
        built.append((store, component))
        return real(store, component, **kwargs)
    monkeypatch.setattr(observation, "build_observer", build)
    out = process_entries.isolated_worker_reconcile(run_record(tmp_path / "r"))
    assert out == {"reconciled": True, "run_id": "r1"} and built == [(None, "isolated-worker-runs")]
    spool = tmp_path / "runtime" / "observations" / "spool"
    rows = [json.loads(line.split(" ", 2)[2]) for path in spool.glob("*.jsonl") for line in path.read_text("utf-8").splitlines()]
    assert [row["attributes"] for row in rows if row["event_type"] == "operations.cleanup_recorded"] == [
        {"resource": "container", "cleanup_outcome": "removed", "cleanup_reason": "completed"}]
    assert list(spool.glob("*.closed"))  # the one-shot step closes the spool it opened


def test_the_reconcile_outcome_is_the_same_when_its_observer_cannot_be_built(tmp_path, settings, monkeypatch):
    listing(monkeypatch, "")
    from codex_harness.composition import observation

    def broken(*args, **kwargs):
        raise OSError("spool unavailable")
    monkeypatch.setattr(observation, "build_observer", broken)
    assert process_entries.isolated_worker_reconcile(run_record(tmp_path / "r")) == {"reconciled": True, "run_id": "r1"}


def test_the_cleanup_feature_is_instrumented_and_names_no_missing_seam():
    assert FEATURES["cleanup"].instrumented is True and FEATURES["cleanup"].seam is None
