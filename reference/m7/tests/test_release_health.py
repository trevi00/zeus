import subprocess
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.deployment import ReleaseRunner
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.policy import POLICY


@pytest.fixture
def runner(tmp_path):
    service = Harness(MemoryStore(), organization())
    service.store.dsn = "fixture:no-db"
    git = SimpleNamespace(repository=tmp_path, _git=lambda *a: "base",
        inspect=lambda *a: {"tree": "tree"}, review_workspace=lambda *a: str(tmp_path))
    return ReleaseRunner(service, git, FileArtifacts(tmp_path / "artifacts"), "unused")


@pytest.mark.parametrize("failure", ["timeout", "missing_tool", "docker_unavailable", "localized_daemon_error",
                                     "test_failure", "invalid_image"])
def test_observation_errors_are_distinct_from_executed_failures(runner, monkeypatch, failure):
    def run(argv, **kwargs):
        if argv[1] == "info":
            return SimpleNamespace(returncode=1 if failure == "localized_daemon_error" else 0,
                                   stderr="", stdout="")
        if failure == "timeout":
            raise subprocess.TimeoutExpired("fixture", 1)
        if failure == "missing_tool":
            raise FileNotFoundError("fixture executable")
        return SimpleNamespace(returncode=125 if failure == "invalid_image" else 1,
            stderr="Cannot connect to the Docker daemon" if failure == "docker_unavailable"
                   else "서버에 연결할 수 없습니다" if failure == "localized_daemon_error"
                   else "executable file not found", stdout="")

    monkeypatch.setattr("codex_harness.adapters.deployment.run_process", run)
    check = runner._check(["docker", "run", "fixture"])
    assert check["passed"] is False
    assert check["outcome"] == ("executed" if failure in {"test_failure", "invalid_image"} else "observation_error")


def test_install_timeout_retains_review_and_can_retry(runner, monkeypatch, fake_verification_services):
    release = runner.releases.propose({"revision": "candidate", "base": "base", "tree": "tree",
        "author": "worker:implementation"}, {"checks": ["tests", "cli_start", "cli_file_task"]})
    for actor in ("lead:improvement", "conductor"):
        runner.releases.review(release["id"], actor, "candidate", True, "fixture:review")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("uv", 1)
    monkeypatch.setattr("codex_harness.adapters.deployment.run_process", timeout)
    assert runner.run(release["id"])["status"] == "retry"
    with runner.service.store.transaction() as tx:
        current = tx.get("releases", release["id"])
        assert current["status"] == "reviewed" and current["checks"] == {}
    monkeypatch.setattr(runner, "_check", lambda *a, **k: {"passed": True, "evidence": "fixture:check"})
    monkeypatch.setattr("codex_harness.adapters.deployment.run_process", lambda *a, **k:
        SimpleNamespace(returncode=0, stdout="sha256:fixture"))
    monkeypatch.setattr(runner, "file_canary", lambda *a: {"passed": True, "evidence": "fixture:canary"})
    monkeypatch.setattr(runner, "_promote", lambda *a: {"status": "fixture_verified"})
    assert runner.run(release["id"])["status"] == "fixture_verified"
    with runner.service.store.transaction() as tx:
        assert tx.get("releases", release["id"])["status"] == "verified"


def active(runner, previous=True):
    with runner.service.store.transaction() as tx:
        tx.put("deployment", "active", {"release_id": "current",
            "previous": {"release_id": "previous"} if previous else None})
        tx.put("images", "current", {"image": "sha256:expected"})


@pytest.mark.parametrize("observation", ["wrong_image", "inspect_failed", "both_inspects_failed", "idle", "matching"])
def test_monitor_never_matches_failed_inspects_or_hides_drift(runner, monkeypatch, observation):
    active(runner)
    calls = []
    def check(argv, **kwargs):
        calls.append(argv)
        return {"passed": True, "evidence": "fixture:healthy"}
    monkeypatch.setattr(runner, "_check", check)
    monkeypatch.setattr(runner.releases, "rollback", lambda *a: pytest.fail("Observation caused rollback"))
    def run(argv, **kwargs):
        if argv[:3] == ["docker", "compose", "ps"]:
            body = '' if observation == "idle" else '{"Service":"implementation-worker","ID":"fixture"}'
            return SimpleNamespace(returncode=0, stdout=body)
        if ((argv[:2] == ["docker", "inspect"] and observation == "inspect_failed")
                or observation == "both_inspects_failed"):
            return SimpleNamespace(returncode=1, stdout="")
        return SimpleNamespace(returncode=0, stdout=("sha256:wrong" if
            argv[:2] == ["docker", "inspect"] and observation == "wrong_image" else "sha256:expected"))
    monkeypatch.setattr("codex_harness.adapters.deployment.run_process", run)
    result = runner.monitor()
    assert result["status"] == ({"wrong_image": "degraded", "inspect_failed": "unknown",
        "both_inspects_failed": "unknown", "idle": "healthy", "matching": "healthy"}[observation])
    assert sum(argv[1] == "exec" for argv in calls) == (1 if observation == "matching" else 0)


def test_health_failure_counter_is_durable_and_unknown_never_rolls_back(runner, monkeypatch):
    active(runner)
    verdict = {"passed": False, "evidence": "fixture:failure", "outcome": "observation_error"}
    monkeypatch.setattr(runner, "_check", lambda *a, **k: verdict.copy())
    rollbacks = []
    monkeypatch.setattr(runner.releases, "rollback", lambda *a:
                        rollbacks.append(a) or {"release_id": "previous"})
    for _ in range(4):
        result = runner.monitor()
        assert result["status"] == "unknown" and result["failures"] == 0
    verdict["outcome"] = "executed"
    assert runner.monitor()["status"] == "unhealthy"
    assert runner.monitor()["failures"] == 2
    verdict["outcome"] = "observation_error"
    assert runner.monitor()["failures"] == 2
    assert not rollbacks
    verdict["outcome"] = "executed"
    result = runner.monitor()
    assert result["failures"] == 3 and result["status"] == "rolled_back"
    assert len(rollbacks) == 1


def test_first_deployment_failure_has_explicit_status_without_impossible_rollback(runner, monkeypatch):
    active(runner, previous=False)
    monkeypatch.setattr(runner, "_check", lambda *a, **k: {"passed": False, "evidence": "fixture"})
    monkeypatch.setattr(runner.releases, "rollback", lambda *a: pytest.fail("No rollback target"))
    for _ in range(POLICY.health_failure_threshold + 1):
        assert runner.monitor()["status"] == "unhealthy"


def test_recreated_container_keeps_service_failure_history(runner, monkeypatch):
    active(runner)
    counter = [0]
    def run(argv, **kwargs):
        if argv[:3] == ["docker", "compose", "ps"]:
            counter[0] += 1
            return SimpleNamespace(returncode=0, stdout=(
                '{"Service":"implementation-worker","ID":"container-' + str(counter[0]) + '"}'))
        return SimpleNamespace(returncode=0, stdout="sha256:expected")
    monkeypatch.setattr("codex_harness.adapters.deployment.run_process", run)
    monkeypatch.setattr(runner, "_check", lambda argv, **kw:
        {"passed": argv[1] != "exec", "evidence": "fixture:probe", "outcome": "executed"})
    rollbacks = []
    monkeypatch.setattr(runner.releases, "rollback", lambda *a:
        rollbacks.append(a) or {"release_id": "previous"})
    for attempt in range(1, POLICY.health_failure_threshold + 1):
        result = runner.monitor()
        assert result["failures"] == attempt
    assert result["status"] == "rolled_back" and len(rollbacks) == 1
    with runner.service.store.transaction() as tx:
        assert len(tx.scan("health_probes")) == 2  # Image and service, independent of container churn.


def test_success_resets_failure_counter_across_controller_restart(runner):
    pointer = {"release_id": "fixture"}
    failed = {"passed": False, "evidence": "fixture:failure"}
    assert runner._probe_status(pointer, failed, "image")["failures"] == 1
    restarted = ReleaseRunner(runner.service, runner.git, runner.artifacts, "unused")
    assert restarted._probe_status(pointer, failed, "image")["failures"] == 2
    assert restarted._probe_status(pointer, {"passed": True}, "image") is None
    assert restarted._probe_status(pointer, failed, "image")["failures"] == 1
