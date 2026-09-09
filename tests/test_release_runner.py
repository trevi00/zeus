from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.deployment import ReleaseRunner
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization


@pytest.mark.parametrize("failure", ["install", "tests", "startup"])
def test_failed_prerequisite_stops_downstream_execution(tmp_path, monkeypatch, failure, fake_verification_services):
    service = Harness(MemoryStore(), organization())
    service.store.dsn = "fixture:no-connection"
    git = SimpleNamespace(repository=tmp_path, _git=lambda *args: "base",
                          inspect=lambda *args: {"tree": "tree"},
                          review_workspace=lambda *args: str(tmp_path))
    artifacts = FileArtifacts(tmp_path / "artifacts")
    runner = ReleaseRunner(service, git, artifacts, str(tmp_path / "unused-auth"))
    candidate = {"revision": "candidate", "base": "base", "tree": "tree",
                 "author": "worker:implementation"}
    release = runner.releases.propose(candidate, {"checks": ["tests", "cli_start", "cli_file_task"]})
    for actor in ("lead:improvement", "conductor"):
        runner.releases.review(release["id"], actor, "candidate", True, "fixture:review")
    calls = []

    def check(argv, *args, **kwargs):
        stage = ("install" if argv[:2] == ["uv", "sync"] else
                 "tests" if "pytest" in argv else
                 "startup" if argv[:2] == ["docker", "run"] else "build")
        calls.append(stage)
        return {"passed": stage != failure,
                "evidence": artifacts.put(stage, "fixture")['ref']}

    monkeypatch.setattr(runner, "_check", check)
    monkeypatch.setattr("codex_harness.adapters.deployment.run_process",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="sha256:image"))
    monkeypatch.setattr(runner, "file_canary",
                        lambda *args: pytest.fail("Model canary ran after failed prerequisite"))
    result = runner.run(release["id"])
    assert result["status"] == "rejected"
    if failure == "install":
        assert calls == ["install"]
    elif failure == "tests":
        assert "build" not in calls
    assert result["checks"]["cli_file_task"].get("skipped") is True
    with service.store.transaction() as tx:
        assert tx.get("releases", release["id"])["status"] == "rejected"
        assert not tx.scan("deployment")


def test_verified_retry_rebases_before_remote_side_effects(tmp_path, monkeypatch):
    service = Harness(MemoryStore(), organization())

    def forbidden(*args):
        pytest.fail("Stale candidate reached remote publication or merge")

    git = SimpleNamespace(repository=tmp_path, remote="fixture/repo",
                          _git=lambda *args: "advanced-main", publish=forbidden, merge=forbidden)
    runner = ReleaseRunner(service, git, FileArtifacts(tmp_path / "artifacts"), "unused")
    candidate = {"revision": "candidate", "base": "old-main", "tree": "tree",
                 "author": "worker:implementation", "task_id": "original-task"}
    release = runner.releases.propose(candidate, {"checks": ["tests", "cli_start", "cli_file_task"]})
    for actor in ("lead:improvement", "conductor"):
        runner.releases.review(release["id"], actor, "candidate", True, "fixture:review")
    runner.releases.verify(release["id"], "candidate", release["policy_hash"],
        {name: {"passed": True, "evidence": "fixture:check"} for name in release["policy"]["checks"]})
    with service.store.transaction() as tx:
        tx.put("images", release["id"], {"image": "sha256:fixture"})
    calls = []

    def rebase(self, task_id, revision):
        calls.append((task_id, revision))
        return {"message_id": "rebase-task"}

    monkeypatch.setattr(Workflow, "request_rebase", rebase)
    assert runner.run(release["id"])["status"] == "rebasing"
    assert calls == [("original-task", "advanced-main")]
