"""INV-CONTINUATION-001: the owner-validated continuation workspace over REAL temporary Git
repositories. No remote, provider or store is touched."""
import os
from pathlib import Path

import pytest
from test_git_workspace import git, repository

from codex_harness.adapters.git import GitWorkspace
from codex_harness.domain.model import ContractError


def rejected_candidate(tmp_path):
    root = repository(tmp_path)
    adapter = GitWorkspace(str(root), str(tmp_path / "workspaces"))
    workspace = adapter.prepare("origin-task", "HEAD")
    (Path(workspace["path"]) / "change.txt").write_text("first attempt", encoding="utf-8")
    return adapter, workspace, adapter.capture(workspace)


def test_successor_continues_the_origin_workspace_and_keeps_rejected_history(tmp_path):
    adapter, origin, rejected = rejected_candidate(tmp_path)
    continued = adapter.continue_workspace("origin-task", "successor-task", rejected["revision"], rejected["base"])
    assert continued["path"] == origin["path"] and continued["branch"] == origin["branch"]
    assert continued["base"] == origin["base"] and continued["task_id"] == "successor-task"
    assert continued["origin_task_id"] == "origin-task" and continued["continued_from"] == rejected["revision"]
    (Path(continued["path"]) / "change.txt").write_text("corrected", encoding="utf-8")
    corrected = adapter.capture(continued)
    # The corrected candidate descends from the rejected one (preserved, never reset) and is reviewed
    # as the whole change from the SAME pinned base; the origin branch moves forward only.
    assert corrected["revision"] != rejected["revision"] and corrected["base"] == rejected["base"]
    assert adapter.is_ancestor(rejected["revision"], corrected["revision"])
    assert git(Path(continued["path"]), "rev-parse", "HEAD") == corrected["revision"]
    assert adapter.inspect(corrected["revision"], corrected["base"])["files"] == ["change.txt"]
    assert (Path(origin["path"]) / ".git" / "harness-assignment-base").read_text("utf-8") == origin["base"]


def test_dirty_moved_rebased_or_foreign_workspaces_are_refused_without_cleanup(tmp_path):
    adapter, origin, rejected = rejected_candidate(tmp_path)
    path = Path(origin["path"])
    (path / "stray.txt").write_text("unowned evidence", encoding="utf-8")
    with pytest.raises(ContractError, match="dirty"):
        adapter.continue_workspace("origin-task", "successor", rejected["revision"], rejected["base"])
    assert (path / "stray.txt").read_text(encoding="utf-8") == "unowned evidence", "never cleaned to pass"
    (path / "stray.txt").unlink()
    with pytest.raises(ContractError, match="moved from its candidate"):
        adapter.continue_workspace("origin-task", "successor", "f" * 40, rejected["base"])
    with pytest.raises(ContractError, match="base changed"):
        adapter.continue_workspace("origin-task", "successor", rejected["revision"], "e" * 40)
    with pytest.raises(ContractError, match="missing from managed root"):
        adapter.continue_workspace("never-prepared", "successor", rejected["revision"], rejected["base"])
    for bad in ("../origin-task", "origin/task", ""):
        with pytest.raises(ContractError, match="Invalid workspace ID"):
            adapter.continue_workspace(bad, "successor", rejected["revision"], rejected["base"])
    with pytest.raises(ContractError, match="exact head and base"):
        adapter.continue_workspace("origin-task", "successor", "HEAD", rejected["base"])
    git(path, "checkout", "-b", "other")
    with pytest.raises(ContractError, match="branch mismatch"):
        adapter.continue_workspace("origin-task", "successor", rejected["revision"], rejected["base"])


@pytest.mark.skipif(os.name == "nt", reason="creating a symlink needs a Windows privilege; POSIX only")
def test_a_linked_origin_directory_is_not_a_managed_workspace(tmp_path):
    adapter, origin, rejected = rejected_candidate(tmp_path)
    (tmp_path / "workspaces" / "linked-task").symlink_to(origin["path"], target_is_directory=True)
    with pytest.raises(ContractError, match="missing from managed root"):
        adapter.continue_workspace("linked-task", "successor", rejected["revision"], rejected["base"])
