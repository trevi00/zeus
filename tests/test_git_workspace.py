from pathlib import Path

import pytest

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.git import GitWorkspace
from codex_harness.domain.model import ContractError


def git(root, *args):
    result = run_process(["git", *args], cwd=str(root))
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@localhost")
    (root / "original.txt").write_text("original", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "Initial fixture")
    return root


def test_candidate_isolation_commit_capture_and_exact_merge(tmp_path):
    root = repository(tmp_path)
    adapter = GitWorkspace(str(root), str(tmp_path / "workspaces"))
    workspace = adapter.prepare("task-one", "HEAD")
    (Path(workspace["path"]) / "change.txt").write_text("review me", encoding="utf-8")
    candidate = adapter.capture(workspace)
    assert not (root / "change.txt").exists()
    assert adapter.inspect(candidate["revision"], candidate["base"])["files"] == ["change.txt"]
    review = adapter.review_workspace(candidate["revision"], "review-one")
    assert (Path(review) / "change.txt").read_text() == "review me"
    assert adapter.merge(candidate)["merged"]
    assert (root / "change.txt").read_text() == "review me"


def test_capture_binds_target_repository_and_patch_hash_and_merge_rechecks_them(tmp_path):
    # FA-015: the reviewed identity carries base (preimage), tree (postimage), patch and target.
    from codex_harness.domain.model import digest
    root = repository(tmp_path)
    adapter = GitWorkspace(str(root), str(tmp_path / "workspaces"))
    workspace = adapter.prepare("task-one", "HEAD")
    (Path(workspace["path"]) / "change.txt").write_text("review me", encoding="utf-8")
    candidate = adapter.capture(workspace)
    assert candidate["repository"] == "local"
    assert candidate["diff_hash"] == digest(adapter.inspect(candidate["revision"], candidate["base"])["diff"])
    remote_adapter = GitWorkspace(str(root), str(tmp_path / "workspaces"), remote="owner/repo")
    with pytest.raises(ContractError, match="target repository changed"):
        remote_adapter.merge(candidate)
    with pytest.raises(ContractError, match="target repository changed"):
        remote_adapter.publish({**candidate, "branch": "harness/task-one"}, "t", "b")
    with pytest.raises(ContractError, match="Candidate patch changed"):
        adapter.merge({**candidate, "diff_hash": "0" * 64})
    assert not (root / "change.txt").exists(), "no rejected path touched main"
    legacy = {k: v for k, v in candidate.items() if k not in {"repository", "diff_hash"}}
    assert adapter.merge(legacy)["merged"], "pre-FA-015 candidates stay mergeable"


def test_main_advance_invalidates_previous_merge_approval(tmp_path):
    root = repository(tmp_path)
    adapter = GitWorkspace(str(root), str(tmp_path / "workspaces"))
    workspace = adapter.prepare("task-one", "HEAD")
    (Path(workspace["path"]) / "change.txt").write_text("candidate")
    candidate = adapter.capture(workspace)
    (root / "other.txt").write_text("new main")
    git(root, "add", ".")
    git(root, "commit", "-m", "Concurrent change")
    with pytest.raises(ContractError, match="Main changed"):
        adapter.merge(candidate)


def test_retry_keeps_original_base_and_uncommitted_work(tmp_path):
    root = repository(tmp_path)
    adapter = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    workspace = adapter.prepare('retry', 'HEAD')
    work = Path(workspace['path']) / 'unfinished.txt'
    work.write_text('saved work')
    (root / 'advanced.txt').write_text('main changed during model turn')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'Concurrent change')
    assert adapter.prepare('retry', 'HEAD')['base'] == workspace['base']
    assert work.read_text() == 'saved work'
    with pytest.raises(ContractError, match='Assignment base changed'):
        adapter.prepare('retry', git(root, 'rev-parse', 'HEAD'))


def test_hook_identity_survives_rework_and_rebase_without_prompt_metadata(tmp_path):
    root = repository(tmp_path)
    adapter = GitWorkspace(str(root), str(tmp_path / "workspaces"))
    workspace = adapter.prepare("hook-work", "HEAD")
    manifests = Path(workspace["path"]) / "harness_hooks"
    manifests.mkdir()
    (manifests / "hook-fixture.json").write_text('{}')
    candidate = adapter.capture(workspace)
    assert candidate["hook_id"] == "hook-fixture"
    candidate.pop("hook_id")  # Simulate metadata from an older runtime.
    (root / "main.txt").write_text("new base")
    git(root, "add", ".")
    git(root, "commit", "-m", "Advance fixture")
    recovered = adapter.rebase("hook-rebase", candidate, git(root, "rev-parse", "HEAD"))
    assert recovered["hook_id"] == "hook-fixture"
