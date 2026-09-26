"""INV-RELEASE-001 / INV-HOST-DELIVERY-001: the GitHub-path merge is ONE fast-forward of main from
exactly the reviewed base to exactly the reviewed revision, through git's own server-side old-id
compare-and-swap, and every outcome that is not a positively recognized per-ref rejection is unknown.

Everything here runs against REAL local Git: a bare repository stands in for the remote and the lane
repository is a clone of it. The one seam is `_remote_url`, pointed at that bare repository. A bare
repository demonstrates stock `git receive-pack` behaviour (git 2.53 here) - it is NOT evidence of
GitHub's server, its permissions or its PR bookkeeping, and nothing here touches a network, `gh` or
GitHub. The injected transport outcomes (a remote failure after or without the update, a timeout, a
malformed status) are LABELLED where they are injected: they rewrite what the client reports, never
what the bare remote actually holds.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
from test_git_workspace import git

import codex_harness.adapters.git as git_module
from codex_harness.adapters.git import GitCommandError, GitWorkspace, MergeRefused, classify_push
from codex_harness.domain.model import ContractError, digest

POSIX_HOOKS = pytest.mark.skipif(os.name == "nt", reason="a shell pre-receive hook needs a POSIX shell")


class BareRemote(GitWorkspace):
    """The production workspace with its remote transport URL pointed at a local bare repository."""

    def __init__(self, repository, workspaces, url):
        super().__init__(repository, workspaces, remote="owner/repo")
        self.url = url

    def _remote_url(self) -> str:
        return self.url


class Recorder:
    """Records every command the workspace runs; `on_push` may replace the push (LABELLED injection)."""

    def __init__(self, monkeypatch):
        self.calls, self.on_push, self.real = [], None, git_module.run_process
        monkeypatch.setattr(git_module, "run_process", self)

    def __call__(self, argv, *args, **kwargs):
        self.calls.append(list(argv))
        assert argv[0] != "gh", "the merge path never invokes gh (head-only merge conditions)"
        if self.is_main_push(argv) and self.on_push is not None:
            return self.on_push(argv, *args, **kwargs)
        return self.real(argv, *args, **kwargs)

    @staticmethod
    def is_main_push(argv) -> bool:
        return argv[:2] == ["git", "push"] and any(arg.endswith(":refs/heads/main") for arg in argv[2:])

    def pushes(self) -> list:
        return [argv for argv in self.calls if self.is_main_push(argv)]


def remote_main(remote: Path) -> str:
    return git(remote, "rev-parse", "refs/heads/main")


def world(tmp_path, monkeypatch):
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-b", "main")
    for key, value in (("user.name", "Fixture"), ("user.email", "fixture@localhost")):
        git(seed, "config", key, value)
    (seed / "original.txt").write_text("original", encoding="utf-8")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "first")
    first = git(seed, "rev-parse", "HEAD")
    (seed / "second.txt").write_text("second", encoding="utf-8")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "second")
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(remote))
    lane = tmp_path / "lane"
    git(tmp_path, "clone", "-q", str(remote), str(lane))
    for key, value in (("user.name", "Fixture"), ("user.email", "fixture@localhost")):
        git(lane, "config", key, value)
    workspace = BareRemote(str(lane), str(tmp_path / "workspaces"), str(remote))
    prepared = workspace.prepare("task-one", "HEAD")
    (Path(prepared["path"]) / "change.txt").write_text("reviewed change", encoding="utf-8")
    candidate = workspace.capture(prepared)
    recorder = Recorder(monkeypatch)
    return {"seed": seed, "remote": remote, "lane": lane, "workspace": workspace, "candidate": candidate,
            "first": first, "base": candidate["base"], "recorder": recorder}


def external_commit(w, name="external.txt") -> str:
    """Another writer lands on main (root merging something else, a UI merge, a direct push)."""
    other = w["seed"]
    git(other, "pull", "-q", str(w["remote"]), "main")
    (other / name).write_text("external", encoding="utf-8")
    git(other, "add", ".")
    git(other, "commit", "-m", "external " + name)
    git(other, "push", "-q", str(w["remote"]), "HEAD:refs/heads/main")
    return git(other, "rev-parse", "HEAD")


def hook(remote: Path, body: str) -> None:
    path = remote / "hooks" / "pre-receive"
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def completed(argv, stdout, returncode):
    return subprocess.CompletedProcess(argv, returncode, stdout, "")


# ----- the current candidate --------------------------------------------------------------------------
def test_a_current_candidate_is_fast_forwarded_once_with_an_explicit_full_ref_base_lease(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    candidate = w["candidate"]
    assert w["workspace"].merge_state(candidate)["state"] == "unmerged"
    merged = w["workspace"].merge(candidate)
    assert merged["merged_revision"] == candidate["revision"] == remote_main(w["remote"])
    assert merged["transport"] == "github" and not merged.get("recovered")
    [push] = w["recorder"].pushes()
    # The exact argv: the full ref with the explicit expected old value, porcelain status, and the exact
    # revision to the full main ref - never `--force`, a tracking-ref shorthand or a permissive refspec.
    assert push == ["git", "push", "--porcelain", "--force-with-lease=refs/heads/main:" + candidate["base"],
                    str(w["remote"]), candidate["revision"] + ":refs/heads/main"]
    assert "--force" not in push and not any(arg.startswith("+") for arg in push)
    # The merged tree IS the reviewed tree by construction, and the lane repository followed.
    assert git(w["remote"], "rev-parse", "main^{tree}") == candidate["tree"]
    assert git(w["lane"], "rev-parse", "HEAD") == candidate["revision"]
    # Recognized afterwards (R1), and a replay performs no second push.
    assert w["workspace"].merge_state(candidate)["state"] == "merged"
    assert w["workspace"].merge(candidate)["recovered"] is True
    assert len(w["recorder"].pushes()) == 1


def test_a_divergent_candidate_is_refused_before_any_push(tmp_path, monkeypatch):
    """Binding decision 1: the explicit lease alone permits a rewrite; exact ancestry makes it ff-only."""
    w = world(tmp_path, monkeypatch)
    side = tmp_path / "side"
    git(tmp_path, "clone", "-q", str(w["lane"]), str(side))
    for key, value in (("user.name", "Fixture"), ("user.email", "fixture@localhost")):
        git(side, "config", key, value)
    git(side, "checkout", "-q", "-b", "diverged", w["first"])     # NOT on top of the claimed base
    (side / "change.txt").write_text("diverged change", encoding="utf-8")
    git(side, "add", ".")
    git(side, "commit", "-m", "diverged")
    revision = git(side, "rev-parse", "HEAD")
    git(w["lane"], "fetch", "-q", str(side), "diverged:refs/heads/diverged")
    base = w["base"]
    diverged = {**w["candidate"], "revision": revision, "tree": git(side, "rev-parse", "HEAD^{tree}"),
                "diff_hash": digest(git(w["lane"], "diff", "--no-ext-diff", base, revision, "--")),
                "branch": "diverged"}
    with pytest.raises(MergeRefused) as refused:
        w["workspace"].merge(diverged)
    assert refused.value.reason_code == "candidate_not_fast_forward"
    assert w["recorder"].pushes() == [] and remote_main(w["remote"]) == base


def test_main_moved_before_the_merge_refuses_with_no_push_and_leaves_main_to_its_writer(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    moved = external_commit(w)
    assert w["workspace"].merge_state(w["candidate"])["state"] == "base_moved"
    with pytest.raises(MergeRefused) as refused:
        w["workspace"].merge(w["candidate"])
    assert refused.value.reason_code == "reviewed_base_moved"
    assert w["recorder"].pushes() == [] and remote_main(w["remote"]) == moved


@POSIX_HOOKS
def test_a_writer_after_the_advertisement_is_refused_by_the_servers_old_id_check(tmp_path, monkeypatch):
    """Probe case 3: main moves between ref advertisement and the ref update; receive-pack refuses."""
    w = world(tmp_path, monkeypatch)
    moved = external_commit(w)
    git(w["remote"], "update-ref", "refs/heads/main", w["base"])     # advertise the base again
    hook(w["remote"], "env -u GIT_QUARANTINE_PATH -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES "
                      "git update-ref refs/heads/main " + moved + "\nexit 0")
    with pytest.raises(MergeRefused) as refused:
        w["workspace"].merge(w["candidate"])
    assert refused.value.reason_code == "reviewed_base_moved"
    assert len(w["recorder"].pushes()) == 1 and remote_main(w["remote"]) == moved
    assert git(w["lane"], "rev-parse", "HEAD") == w["base"], "a refused update moves nothing locally"


@POSIX_HOOKS
def test_a_server_rule_rejection_is_a_definite_refusal_with_its_own_code(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    hook(w["remote"], "echo 'protected branch fixture' >&2\nexit 1")
    with pytest.raises(MergeRefused) as refused:
        w["workspace"].merge(w["candidate"])
    assert refused.value.reason_code == "merge_push_refused"
    assert remote_main(w["remote"]) == w["base"]


# ----- unknown outcomes are reconciled, never concluded --------------------------------------------------
def test_a_remote_failure_after_the_update_is_unknown_and_reconciled_without_a_second_push(tmp_path, monkeypatch):
    """Owner review correction: `[remote failure]` after the remote became the candidate is not a refusal."""
    w = world(tmp_path, monkeypatch)
    recorder, candidate = w["recorder"], w["candidate"]

    def failure_after_effect(argv, *args, **kwargs):
        recorder.real(argv, *args, **kwargs)   # the update really happens on the bare remote
        # LABELLED injection: the status that came back is a broken-connection remote failure.
        return completed(argv, "To remote\n!\t" + candidate["revision"]
                         + ":refs/heads/main\t[remote failure] (remote failed to report status)\nDone\n", 1)
    recorder.on_push = failure_after_effect
    with pytest.raises(GitCommandError):
        w["workspace"].merge(candidate)
    assert remote_main(w["remote"]) == candidate["revision"]
    recorder.on_push = None
    state = w["workspace"].merge_state(candidate)
    assert state["state"] == "merged" and state["merged_revision"] == candidate["revision"]
    assert w["workspace"].merge(candidate)["recovered"] is True
    assert len(recorder.pushes()) == 1, "the recognized effect is never pushed a second time"


def test_a_remote_failure_while_main_is_still_the_base_permits_only_the_fenced_retry(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    recorder, candidate = w["recorder"], w["candidate"]
    recorder.on_push = lambda argv, *a, **k: completed(   # LABELLED: nothing reached the remote
        argv, "!\t" + candidate["revision"] + ":refs/heads/main\t[remote failure] (remote hung up)\n", 1)
    with pytest.raises(GitCommandError):
        w["workspace"].merge(candidate)
    assert remote_main(w["remote"]) == w["base"]
    assert w["workspace"].merge_state(candidate)["state"] == "unmerged"
    recorder.on_push = None
    assert w["workspace"].merge(candidate)["merged_revision"] == candidate["revision"]
    assert len(recorder.pushes()) == 2 and remote_main(w["remote"]) == candidate["revision"]


@pytest.mark.parametrize("reported", ["timeout", "no_status", "malformed", "other_ref", "conflict", "two_lines"])
def test_every_other_push_report_is_unknown_not_a_refusal(tmp_path, monkeypatch, reported):
    w = world(tmp_path, monkeypatch)
    revision = w["candidate"]["revision"]
    outputs = {"no_status": ("fatal: unable to access remote\n", 128),
               "malformed": ("!\t" + revision + ":refs/heads/main\trejected stale\n", 1),
               "other_ref": ("!\t" + revision + ":refs/heads/other\t[rejected] (stale info)\n", 1),
               # A rejection line with a success exit code: conflicting output.
               "conflict": ("!\t" + revision + ":refs/heads/main\t[rejected] (stale info)\n", 0),
               "two_lines": (" \t" + revision + ":refs/heads/main\ta..b\n!\t" + revision
                             + ":refs/heads/main\t[rejected] (stale info)\n", 1)}

    def injected(argv, *args, **kwargs):   # LABELLED transport outcome; the remote is untouched
        if reported == "timeout":
            raise subprocess.TimeoutExpired(argv, 120)
        stdout, code = outputs[reported]
        return completed(argv, stdout, code)
    w["recorder"].on_push = injected
    with pytest.raises(GitCommandError):
        w["workspace"].merge(w["candidate"])
    assert remote_main(w["remote"]) == w["base"]


def test_the_per_ref_status_classification_table():
    rev = "a" * 40
    line = "{flag}\t" + rev + ":refs/heads/main\t{summary}\n"
    assert classify_push(line.format(flag=" ", summary="1111111..aaaaaaa"), rev) == "pushed"
    assert classify_push(line.format(flag="=", summary="[up to date]"), rev) == "pushed"
    assert classify_push(line.format(flag="!", summary="[rejected] (stale info)"), rev) == "base_moved"
    assert classify_push(line.format(flag="!", summary="[remote rejected] (incorrect old value provided)"),
                         rev) == "base_moved"
    assert classify_push(line.format(flag="!", summary="[rejected] (fetch first)"), rev) == "base_moved"
    assert classify_push(line.format(flag="!", summary="[remote rejected] (protected branch hook declined)"),
                         rev) == "refused"
    for unknown in ("[remote failure] (remote failed to report status)", "[no match]", "[rejected] stale",
                    "something new"):
        assert classify_push(line.format(flag="!", summary=unknown), rev) == "unknown"
    assert classify_push(line.format(flag="+", summary="1111111...aaaaaaa (forced update)"), rev) == "unknown"
    assert classify_push(line.format(flag=" ", summary="x").replace(rev, "b" * 40), rev) == "unknown"
    assert classify_push("", rev) == "unknown" and classify_push("Done\n", rev) == "unknown"


def test_a_local_fast_forward_failure_after_the_push_is_unknown_and_recognized_next(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    (w["lane"] / "local.txt").write_text("unpushed local commit", encoding="utf-8")
    git(w["lane"], "add", ".")
    git(w["lane"], "commit", "-m", "local divergence")   # the lane repository cannot fast-forward now
    with pytest.raises(GitCommandError):
        w["workspace"].merge(w["candidate"])
    assert remote_main(w["remote"]) == w["candidate"]["revision"]
    assert w["workspace"].merge_state(w["candidate"])["state"] == "merged"
    assert len(w["recorder"].pushes()) == 1


# ----- effects made by someone else ---------------------------------------------------------------------
def ui_merge(w, *, after_external=False) -> str:
    """A merge commit of the candidate branch on the remote main, as the GitHub merge button makes one."""
    git(w["lane"], "push", "-q", str(w["remote"]), w["candidate"]["revision"] + ":refs/heads/harness/task-one")
    if after_external:
        external_commit(w, "before-merge.txt")
    other = w["seed"]
    git(other, "pull", "-q", str(w["remote"]), "main")
    git(other, "fetch", "-q", str(w["remote"]), "harness/task-one")
    git(other, "merge", "-q", "--no-ff", "-m", "Merge pull request", "FETCH_HEAD")
    git(other, "push", "-q", str(w["remote"]), "HEAD:refs/heads/main")
    return git(other, "rev-parse", "HEAD")


def test_an_external_merge_commit_is_recognized_from_the_pr_and_qualified_on_its_tree(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    merge = ui_merge(w)
    candidate = w["candidate"]
    observed = {"state": "MERGED", "head": candidate["revision"], "merged_revision": merge}
    # Reachable only through the merge's second parent: not a mainline fast-forward of the candidate.
    assert w["workspace"].merge_state(candidate)["state"] == "base_moved"
    state = w["workspace"].merge_state(candidate, observed)
    assert (state["state"], state["merged_revision"], state["recognized"]) == ("merged", merge, "pull_request")
    assert w["workspace"].qualify_merged(candidate, merge, fetch=False)["tree"] == candidate["tree"]
    assert w["recorder"].pushes() == []


def test_an_external_merge_onto_a_moved_main_is_recognized_but_never_qualifies(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    merge = ui_merge(w, after_external=True)
    candidate = w["candidate"]
    state = w["workspace"].merge_state(candidate, {"state": "MERGED", "head": candidate["revision"],
                                                   "merged_revision": merge})
    assert state["state"] == "merged"
    with pytest.raises(ContractError, match="Merged tree differs"):
        w["workspace"].qualify_merged(candidate, merge, fetch=False)


def test_the_remote_main_is_read_without_fetching(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    assert w["workspace"].remote_main() == w["base"]
    assert not any(argv[:2] == ["git", "fetch"] for argv in w["recorder"].calls)
    w["recorder"].on_push = None
    monkeypatch.setattr(w["workspace"], "_remote_url", lambda: str(tmp_path / "missing.git"))
    with pytest.raises(GitCommandError):
        w["workspace"].remote_main()


def test_an_unreadable_remote_is_unknown_never_unmerged(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    monkeypatch.setattr(w["workspace"], "_remote_url", lambda: str(tmp_path / "missing.git"))
    with pytest.raises(GitCommandError):
        w["workspace"].merge_state(w["candidate"])
    with pytest.raises(GitCommandError):
        w["workspace"].merge(w["candidate"])
    assert w["recorder"].pushes() == []
