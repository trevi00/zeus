from datetime import datetime, timedelta, timezone

import pytest
from test_git_workspace import git, repository

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.deployment import ReleaseRunner
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError
from codex_harness.domain.policy import POLICY


def candidate_runner(tmp_path, store=None, remote=None):
    root = repository(tmp_path)
    # The target repository is part of the captured identity (FA-015), so it is fixed before capture.
    adapter = GitWorkspace(str(root), str(tmp_path / "workspaces"), remote=remote)
    workspace = adapter.prepare("candidate-task")
    from pathlib import Path
    (Path(workspace["path"]) / "change.txt").write_text("candidate", encoding="utf-8")
    candidate = adapter.capture(workspace)
    service = Harness(store or MemoryStore(), organization())
    runner = ReleaseRunner(service, adapter, FileArtifacts(tmp_path / "artifacts"), "unused")
    release = runner.releases.propose(candidate, {"checks": ["tests"]})
    for actor in ("lead:improvement", "conductor"):
        runner.releases.review(release["id"], actor, candidate["revision"], True, "fixture:review")
    runner.releases.verify(release["id"], candidate["revision"], release["policy_hash"],
                           {"tests": {"passed": True, "evidence": "fixture:tests"}})
    with service.store.transaction() as tx:
        tx.put("images", release["id"], {"image": "sha256:fixture"})
    return runner, release, root


@pytest.mark.parametrize("position", ["unrelated", "merged", "remote_uncertain"])
def test_abandon_uses_real_ancestry_and_preserves_uncertain_merges(tmp_path, monkeypatch, position):
    runner, release, root = candidate_runner(tmp_path)
    merge = runner.git.merge
    def stop(candidate):
        raise ConnectionError("fixture before merge")
    monkeypatch.setattr(runner.git, "merge", stop)
    with pytest.raises(ConnectionError):
        runner.run(release["id"])
    if position == "merged":
        merge(release["candidate"])
    else:
        (root / "unrelated.txt").write_text("other work", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-m", "Unrelated main advance")
    if position == "remote_uncertain":
        with runner.service.store.transaction() as tx:
            intent = tx.get("promotion_intents", release["id"])
            tx.put("promotion_intents", release["id"], {**intent, "external_started": True})
    if position == "unrelated":
        assert runner.run(release["id"])["status"] == "blocked"
        assert runner.abandon(release["id"], "New request")["status"] == "abandoned"
    else:
        with pytest.raises(ContractError, match="already in main|External merge uncertain"):
            runner.abandon(release["id"], "Must not abandon")


@pytest.mark.parametrize("backend", ["memory", pytest.param("postgres", marks=pytest.mark.integration)])
@pytest.mark.parametrize("crash", ["before_merge", "after_merge", "during_promote"])
def test_restart_recovers_exact_local_merge_without_rebase(tmp_path, monkeypatch, crash, backend, request):
    store = MemoryStore() if backend == "memory" else request.getfixturevalue("isolated_pgstore")
    runner, release, root = candidate_runner(tmp_path, store)
    merge, promote = runner.git.merge, runner.releases.promote
    calls = []

    def interrupted_merge(candidate):
        if crash == "before_merge":
            raise ConnectionError("fixture before merge")
        calls.append("merge")
        result = merge(candidate)
        if crash == "after_merge":
            raise ConnectionError("fixture after merge before receipt")
        return result

    def interrupted_promote(*args, **kwargs):
        promote(*args, **kwargs)
        raise ConnectionError("fixture after promotion writes before commit")

    monkeypatch.setattr(runner.git, "merge", interrupted_merge)
    if crash == "during_promote":
        monkeypatch.setattr(runner.releases, "promote", interrupted_promote)
    with pytest.raises(ConnectionError):
        runner.run(release["id"])
    monkeypatch.setattr(runner.releases, "promote", promote)

    def count_merge(candidate):
        calls.append("merge")
        return merge(candidate)

    monkeypatch.setattr(runner.git, "merge", count_merge)
    assert runner.run(release["id"])["status"] == "active"
    assert calls == ["merge"]
    assert git(root, "rev-parse", "HEAD") == release["candidate"]["revision"]
    with runner.service.store.transaction() as tx:
        assert not tx.scan("rebase_requests")
        assert tx.get("promotion_intents", release["id"])["status"] == "completed"
        assert tx.get("deployment", "active")["release_id"] == release["id"]


def test_recovery_blocks_unrelated_head_and_unproven_remote_effect(tmp_path, monkeypatch):
    runner, release, root = candidate_runner(tmp_path)
    monkeypatch.setattr(runner.git, "merge", lambda *a: (_ for _ in ()).throw(ConnectionError("fixture")))
    with pytest.raises(ConnectionError):
        runner.run(release["id"])
    (root / "other.txt").write_text("third revision")
    git(root, "add", ".")
    git(root, "commit", "-m", "unrelated")
    assert runner.run(release["id"])["status"] == "blocked"
    with runner.service.store.transaction() as tx:
        assert tx.get("deployment", "active") is None


def test_remote_publication_interruption_is_explicitly_blocked(tmp_path, monkeypatch):
    runner, release, _ = candidate_runner(tmp_path, remote="fixture/repository")
    calls = []

    def interrupted(*args):
        calls.append("publish")
        raise ConnectionError("fixture uncertain remote effect")

    monkeypatch.setattr(runner.git, "publish", interrupted)
    with pytest.raises(ConnectionError):
        runner.run(release["id"])
    assert runner.run(release["id"])["status"] == "blocked_remote"
    assert calls == ["publish"]


def test_remote_merge_before_receipt_remains_explicitly_blocked(tmp_path, monkeypatch):
    runner, release, root = candidate_runner(tmp_path, remote="fixture/repository")
    monkeypatch.setattr(runner.git, "publish", lambda *a: None)
    calls = []
    def merge(candidate):
        calls.append("merge")
        git(root, "merge", "--ff-only", candidate["revision"])
        raise ConnectionError("fixture remote merge completed without durable receipt")
    monkeypatch.setattr(runner.git, "merge", merge)
    with pytest.raises(ConnectionError):
        runner.run(release["id"])
    assert runner.run(release["id"])["status"] == "blocked_remote"
    assert calls == ["merge"]


@pytest.mark.parametrize("backend", ["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def test_queue_backoff_budget_terminal_checks_and_stale_controller(backend, request):
    store = MemoryStore() if backend == "memory" else request.getfixturevalue("isolated_pgstore")
    queue = ReleaseQueue(store)
    now = datetime.now(timezone.utc)
    with store.transaction() as tx:
        tx.put("release_queue", "release", {"id": "release", "status": "queued", "preserve": "metadata"})
    for attempt in range(1, POLICY.release_max_attempts + 1):
        claim = queue.claim(now)
        assert claim["attempt"] == attempt and queue.claim(now) is None
        finished = queue.finish(claim, {"status": "retry", "evidence": "fixture:infra"}, now)
        assert queue.claim(now) is None
        now += timedelta(seconds=POLICY.release_retry_seconds * 2 ** (attempt - 1))
    assert finished["status"] == "failed" and finished["preserve"] == "metadata"
    assert len(finished["attempts"]) == POLICY.release_max_attempts
    assert queue.claim(now) is None
    with store.transaction() as tx:
        tx.put("release_queue", "new", {"id": "new", "status": "queued"})
    stale = queue.claim(now)
    later = now + timedelta(seconds=POLICY.release_lease_seconds + 1)
    replacement = queue.claim(later)
    with pytest.raises(ContractError, match="Stale"):
        queue.finish(stale, {"status": "active"}, later)
    checks = {"tests": {"passed": False, "evidence": "fixture:real-failure"}}
    result = queue.finish(replacement, {"status": "rejected", "checks": checks}, later)
    assert result["result"]["checks"] == checks and queue.claim(later) is None


def test_queue_transient_errors_then_success():
    store = MemoryStore()
    queue = ReleaseQueue(store)
    now = datetime.now(timezone.utc)
    with store.transaction() as tx:
        tx.put("release_queue", "release", {"id": "release", "status": "queued"})
    for status in ("retry", "retry", "active"):
        claim = queue.claim(now)
        row = queue.finish(claim, {"status": status}, now)
        now += timedelta(seconds=120)
    assert row["status"] == "active" and row["attempt"] == 3
    assert queue.claim(now) is None


@pytest.mark.parametrize("backend", ["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def test_concurrent_controllers_claim_only_one_release(backend, request):
    from concurrent.futures import ThreadPoolExecutor
    store = MemoryStore() if backend == "memory" else request.getfixturevalue("isolated_pgstore")
    with store.transaction() as tx:
        for name in ("one", "two"):
            tx.put("release_queue", name, {"id": name, "status": "queued"})
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: ReleaseQueue(store).claim(), range(4)))
    assert sum(claim is not None for claim in claims) == 1
