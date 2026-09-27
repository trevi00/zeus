"""INV-RELEASE-ENVIRONMENT-REVERIFY-001: an environment re-verification runs only on its own code.

The repository, release and checks are labelled fixtures; nothing claims an actual Codex, GitHub
or production verification.
"""
import subprocess
from pathlib import Path

import pytest
from test_release_evaluator_migration import reviewed_record, runner_for
from verification_fixtures import source_repository

from codex_harness.adapters import deployment
from codex_harness.adapters.deployment import EvaluatorCodeMismatch, controller_code_revision

RUNNING = "1" * 40


def reverification(repo, controller_revision):
    release = reviewed_record(repo)
    release["environment_reverification"] = {"source_release_id": "b" * 64, "controller_revision": controller_revision}
    return release


def test_the_matching_controller_revision_proceeds(tmp_path, monkeypatch, fake_verification_services):
    repo = source_repository(tmp_path / "repo")
    release = reverification(repo, RUNNING)
    runner, calls = runner_for(tmp_path, repo, release, monkeypatch)
    monkeypatch.setattr(deployment, "controller_code_revision", lambda: RUNNING)
    answer = runner.evaluate(release["id"])
    assert answer["receipt"]["workspaces"]["incumbent"]["revision"] == repo["base"] and len(calls) == 2


@pytest.mark.parametrize("recorded,running", [("2" * 40, RUNNING), (RUNNING, None), (None, RUNNING),
                                              ("ABC", RUNNING), ("A" * 40, "A" * 40)])
def test_a_different_or_unknown_revision_is_refused_before_any_workspace(tmp_path, monkeypatch, recorded, running,
                                                                          fake_verification_services):
    repo = source_repository(tmp_path / "repo")
    release = reverification(repo, recorded)
    runner, calls = runner_for(tmp_path, repo, release, monkeypatch)
    monkeypatch.setattr(deployment, "controller_code_revision", lambda: running)
    inspected = []
    monkeypatch.setattr(runner.git, "inspect", lambda *a: inspected.append(a))
    with pytest.raises(EvaluatorCodeMismatch) as refused:
        runner.evaluate(release["id"], attempt="0123456789abcdef" * 2)
    assert refused.value.reason_code == "evaluator_code_mismatch"
    workspaces = tmp_path / "workspaces"
    assert calls == [] and inspected == []
    assert not workspaces.exists() or not any(workspaces.iterdir())
    assert not (tmp_path / "artifacts").exists() or not any((tmp_path / "artifacts").iterdir())


def test_a_non_dict_record_is_refused(tmp_path, monkeypatch, fake_verification_services):
    repo = source_repository(tmp_path / "repo")
    release = reviewed_record(repo)
    release["environment_reverification"] = RUNNING
    runner, calls = runner_for(tmp_path, repo, release, monkeypatch)
    monkeypatch.setattr(deployment, "controller_code_revision", lambda: RUNNING)
    with pytest.raises(EvaluatorCodeMismatch):
        runner.evaluate(release["id"])
    assert calls == []


def test_an_ordinary_release_never_asks_for_the_controller_revision(tmp_path, monkeypatch, fake_verification_services):
    repo = source_repository(tmp_path / "repo")
    release = reviewed_record(repo)
    runner, calls = runner_for(tmp_path, repo, release, monkeypatch)

    def unexpected():
        raise AssertionError("an ordinary release must not consult the controller revision")

    monkeypatch.setattr(deployment, "controller_code_revision", unexpected)
    answer = runner.evaluate(release["id"])
    assert answer["verdict"] == "checked" and len(calls) == 2


def test_the_running_revision_is_this_checkout_by_the_runtime_revision_ssot():
    root = Path(deployment.__file__).resolve().parents[3]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    if head.returncode != 0:
        pytest.skip("not a git checkout")
    from codex_harness.adapters.host_delivery import runtime_revision
    assert controller_code_revision() == runtime_revision(root)


def test_the_owner_coordinator_binds_the_runtime_revision_ssot_as_the_trusted_controller_port(tmp_path,
                                                                                               monkeypatch):
    """PR214 review B1: the owner/lane boundary resolves the running controller code through the SAME
    SSOT the runner's own-code guard uses, never through the requester's approval string."""
    from types import SimpleNamespace

    from codex_harness.adapters import owner_actions as adapter
    from codex_harness.adapters.store import MemoryStore
    from codex_harness.bootstrap import organization

    monkeypatch.setenv("HARNESS_RUNTIME_DIR", str(tmp_path / "runtime"))
    lane = SimpleNamespace(store=MemoryStore())
    owner = adapter.coordinator(SimpleNamespace(store=MemoryStore(), org=organization()), {}, {},
                                lanes=lambda lane_id: lane, assessments=object(), continuation=object())
    delivery = owner.deliveries("a")
    assert delivery.controller_code is deployment.controller_code_revision
    monkeypatch.setattr(delivery, "controller_code", lambda: "0" * 40)
    with pytest.raises(Exception) as caught:
        delivery.require_controller_code("7" * 40)
    assert caught.value.reason_code == "migration_controller_code_mismatch"
