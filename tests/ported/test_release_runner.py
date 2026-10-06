"""Ported SOURCE M7 suite `tests/test_release_runner.py` (e38aa722) run against the S7 target (DESIGN-s7 §6).

Every assertion is M7's, unchanged. Adaptations, all construction, import and patch-target (the `m7_delivery` shim
docstring names the routing): `ReleaseRunner` is the release runner as composition wires it; `deployment` is the moved
`delivery.adapters.deployment`, whose `run_process` is the runner's injected process port (the string patch target
`codex_harness.adapters.deployment.run_process` is `monkeypatch.setattr(deployment, "run_process", ...)`);
`fake_verification_services` is M7 `tests/conftest.py`'s fixture over the injected `verification_services` port;
`Workflow.request_rebase` (patched on the class) is the shim's name for the injected `request_rebase` port (its owner is
S5), called as M7 called it; `Harness`, `FileArtifacts`, `MemoryStore` and `organization` come from their target homes;
`ContractError` and `digest` from `kernel`.
"""
# ruff: noqa: F811  (the shim's fixture is imported by name and requested as a parameter, as M7's conftest fixture was)
from pathlib import Path
from types import SimpleNamespace

import pytest
from m7_delivery import (
    Harness,
    ReleaseRunner,
    Workflow,
    deployment,
    fake_verification_services,  # noqa: F401  (fixture)
    organization,
)

from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore


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
        stage = ("install" if _is_uv_sync(argv) else
                 "tests" if "pytest" in argv else
                 "startup" if argv[:2] == ["docker", "run"] else "build")
        calls.append(stage)
        return {"passed": stage != failure,
                "evidence": artifacts.put(stage, "fixture")['ref']}

    monkeypatch.setattr(runner, "_check", check)
    monkeypatch.setattr(deployment, "run_process",
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


@pytest.mark.parametrize("drift", ["patch", "repository"])
def test_runner_refuses_reviewed_candidate_whose_patch_or_target_drifted(tmp_path, monkeypatch, drift,
                                                                          fake_verification_services):
    from codex_harness.kernel.errors import ContractError
    from codex_harness.kernel.ids import digest
    service = Harness(MemoryStore(), organization())
    git = SimpleNamespace(repository=tmp_path, remote="fixture/repo", _git=lambda *args: "base",
                          target_identity=lambda: "github:fixture/repo",
                          inspect=lambda *args: {"tree": "tree", "diff": "reviewed diff"},
                          review_workspace=lambda *args: str(tmp_path))
    artifacts = FileArtifacts(tmp_path / "artifacts")
    runner = ReleaseRunner(service, git, artifacts, str(tmp_path / "unused-auth"))
    candidate = {"revision": "candidate", "base": "base", "tree": "tree", "author": "worker:implementation",
                 "repository": "github:fixture/repo" if drift == "patch" else "github:other/repo",
                 "diff_hash": digest("tampered diff" if drift == "patch" else "reviewed diff")}
    release = runner.releases.propose(candidate, {"checks": ["tests", "cli_start", "cli_file_task"]})
    for actor in ("lead:improvement", "conductor"):
        runner.releases.review(release["id"], actor, "candidate", True, "fixture:review")
    monkeypatch.setattr(runner, "_check", lambda *a, **k: pytest.fail("checks ran for a drifted candidate"))
    with pytest.raises(ContractError, match="patch mismatch" if drift == "patch" else "target repository changed"):
        runner.run(release["id"])
    with service.store.transaction() as tx:
        assert tx.get("releases", release["id"])["status"] == "reviewed"
        assert not tx.scan("promotion_intents") and not tx.scan("deployment")


def _is_uv_sync(argv) -> bool:
    """The install step, whichever `uv` the evaluator resolved: bare `uv` on PATH, or the service user's
    absolute `~/.local/bin/uv` when PATH has none (`deployment.uv_command`, the aibox controller)."""
    return bool(argv) and Path(argv[0]).name == "uv" and list(argv[1:2]) == ["sync"]


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
