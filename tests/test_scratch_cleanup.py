"""The runner's scratch: what is kept leaves first, and what refuses to be removed is named.

`workdir_removed: false` was observed again in the Windows pilot. These tests build the same shape
the runner builds - a real throwaway Git repository with a linked worktree and packed objects - and
hold the two refusals apart, because they have different fixes: a read-only attribute is cleared, a
file somebody still has open is reported and left alone.

Nothing here calls a provider. The behaviour under test is filesystem behaviour, and paying a model
to observe it again would measure nothing new.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness.adapters.scratch import Scratch, ScratchEscape, file_digest

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt",
                                  reason="the read-only attribute only refuses deletion on Windows")


def git(*args, cwd):
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done


def build_repository(root: Path) -> dict:
    """The runner's shape: a repository, a commit, a linked worktree, and packed objects.

    `git gc` is what produces the read-only files; without it this fixture would not reach the
    condition that was actually observed.
    """
    repository = root / "repository"
    repository.mkdir(parents=True)
    git("init", "-b", "main", cwd=repository)
    git("config", "user.email", "evidence@localhost", cwd=repository)
    git("config", "user.name", "Zeus Evidence", cwd=repository)
    (repository / "slug.py").write_text("def slugify(text):\n    return text\n", encoding="utf-8")
    git("add", "--all", cwd=repository)
    git("commit", "-m", "fixture", cwd=repository)
    workspaces = root / "workspaces"
    workspaces.mkdir()
    worktree = workspaces / "task-1"
    git("worktree", "add", str(worktree), "-b", "harness/task-1", cwd=repository)
    git("gc", "--aggressive", "--prune=now", cwd=repository)
    return {"repository": repository, "worktree": worktree}


def scratch_at(parent: Path, name: str = "scratch") -> Scratch:
    """The runner creates its root before it owns it; these tests do the same."""
    root = parent / name
    root.mkdir(parents=True, exist_ok=True)
    return Scratch(root)


def make_directory_link(link: Path, target: Path) -> str:
    """A directory link, by whichever mechanism this host lets an unprivileged process use.

    Windows needs a privilege for a symbolic link but not for a junction, and a junction is the form
    that actually turns up on this host, so the boundary is exercised rather than skipped.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                              capture_output=True, text=True, timeout=60)
        if done.returncode == 0 and link.exists():
            return "junction"
    pytest.skip("this host does not allow this process to create a directory link")


def read_only_files(root: Path) -> list:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*")
                  if path.is_file() and not (path.lstat().st_mode & stat.S_IWRITE))


# ---- the failure that was observed, and the fix that is not a retry ------------------------------

def test_a_packed_git_repository_is_removed_and_the_read_only_files_are_named(tmp_path):
    """The condition from the pilot, reproduced: git's packed objects are read-only.

    They are removed by clearing the attribute, not by waiting, and each one is reported by path so
    a reader can see which files needed it.
    """
    scratch = scratch_at(tmp_path)
    build_repository(scratch.root)
    before = read_only_files(scratch.root)
    assert before, "this fixture must reach the read-only condition, or it tests nothing"

    report = scratch.remove()

    assert report["removed"] is True and not scratch.root.exists()
    assert report["refusals"] == []
    if os.name == "nt":
        assert sorted(report["cleared_read_only"]) == before, "every read-only file is named"
    assert report["remaining"] == [] and report["remaining_count"] == 0


@WINDOWS_ONLY
def test_the_old_retry_loop_cannot_remove_what_this_one_does(tmp_path):
    """The contrast that shows the old cleanup failed for a reason waiting cannot fix."""
    import shutil
    import time

    root = tmp_path / "old"
    root.mkdir()
    build_repository(root)
    attempts = []
    for _ in range(5):  # exactly the loop the runner used
        shutil.rmtree(root, ignore_errors=True)
        attempts.append(root.exists())
        if not root.exists():
            break
        time.sleep(0.05)
    assert all(attempts), "five attempts leave the same files; this is not a race"
    assert read_only_files(root), "and what is left is read-only"
    assert Scratch(root).remove()["removed"] is True


def test_a_file_someone_still_has_open_is_a_bounded_failure_not_a_forced_one(tmp_path):
    """An open handle is a real refusal. It is reported with its cause and the file is left alone."""
    scratch = scratch_at(tmp_path)
    built = build_repository(scratch.root)
    held = built["worktree"] / "held-open.log"
    handle = open(held, "w", encoding="utf-8")
    handle.write("a reader still has this\n")
    handle.flush()
    try:
        report = scratch.remove()
    finally:
        handle.close()

    if os.name == "nt":
        assert report["removed"] is False
        [refusal] = [r for r in report["refusals"] if r["path"].endswith("held-open.log")]
        assert refusal["cause"] == "in_use" and refusal["winerror"] == 32
        assert refusal["read_only_attribute"] is False
        assert report["recleanable"] is True, "an open file can be removed once the handle closes"
        assert any("held-open.log" in name for name in report["remaining"])
        assert Scratch(scratch.root).remove()["removed"] is True, "and it is, afterwards"
    else:
        # POSIX unlinks an open file; the difference between the hosts is part of the record.
        assert report["removed"] is True and report["refusals"] == []


def test_the_two_causes_are_never_reported_as_one(tmp_path):
    """A read-only attribute and an open handle need different answers, so they get different names."""
    scratch = scratch_at(tmp_path)
    built = build_repository(scratch.root)
    handle = open(built["worktree"] / "held.bin", "wb")
    handle.write(b"held")
    handle.flush()
    try:
        report = scratch.remove()
    finally:
        handle.close()
    causes = {refusal["cause"] for refusal in report["refusals"]}
    assert "read_only_attribute" not in causes, "a read-only file inside our own root is cleared, not refused"
    if os.name == "nt":
        assert {refusal["cause"] for refusal in report["blocking_refusals"]} == {"in_use"}
        # The directories above it also refuse, and they are reported, but as the consequence they
        # are rather than as a second thing standing in the way.
        assert causes == {"in_use", "not_empty"}
    else:
        # POSIX unlinks an open file, so the first removal already finished.
        assert report["removed"] is True and report["refusals"] == []
    if scratch.root.exists():
        Scratch(scratch.root).remove()


# ---- staying inside the root this run created ----------------------------------------------------

def test_a_link_is_removed_as_a_link_and_what_it_points_at_is_untouched(tmp_path):
    """Following a link would reach another run's data. The link goes; the target stays."""
    outside = tmp_path / "somebody-elses-data"
    outside.mkdir()
    treasure = outside / "keep.txt"
    treasure.write_text("this belongs to another run", encoding="utf-8")

    root = tmp_path / "scratch"
    root.mkdir()
    scratch = Scratch(root)
    link = root / "pointer"
    kind = make_directory_link(link, outside)

    report = scratch.remove()

    assert treasure.exists() and treasure.read_text(encoding="utf-8") == "this belongs to another run"
    assert outside.exists(), "the directory on the other side of the link is not removed"
    [record] = report["links_removed"]
    assert record["kind"] == kind
    assert record["removed"] is True and record["note"].endswith("never followed")
    assert report["removed"] is True


def test_a_path_that_resolves_outside_the_root_is_refused_and_reported(tmp_path, monkeypatch):
    """Containment is checked against the resolved path, and a breach stops the removal."""
    root = tmp_path / "scratch"
    root.mkdir()
    (root / "ordinary.txt").write_text("x", encoding="utf-8")
    scratch = Scratch(root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.setattr(Scratch, "within", lambda self, path: False)
    report = scratch.remove()

    assert report["escapes"], "the breach is recorded rather than passed over"
    assert report["aborted"]["reason"] == "path_escaped_the_scratch"
    assert report["removed"] is False and report["recleanable"] is False
    assert (root / "ordinary.txt").exists(), "nothing is removed once containment is in doubt"


def test_preserving_a_path_outside_the_scratch_is_refused(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    scratch = Scratch(root)
    outsider = tmp_path / "outside.txt"
    outsider.write_text("not this run's", encoding="utf-8")

    report = scratch.preserve(tmp_path / "kept", [{"name": "x.txt", "source": outsider}])

    assert report["complete"] is False
    assert report["failures"][0]["error"] == ScratchEscape.__name__
    assert not (tmp_path / "kept" / "x.txt").exists()


# ---- what must survive the cleanup ---------------------------------------------------------------

def test_evidence_is_verified_on_disk_before_the_scratch_is_removed(tmp_path):
    """The receipt points at bytes somebody can still open, and the copy is hashed to prove it."""
    root = tmp_path / "scratch"
    root.mkdir()
    scratch = Scratch(root)
    artifact = root / "artifacts" / "execution.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"process": {"exit_code": 0}}', encoding="utf-8")

    kept = scratch.preserve(tmp_path / "kept", [
        {"name": "execution.json", "source": artifact},
        {"name": "runner-tests-after.log", "text": "3 passed in 0.10s\n"},
    ])
    report = scratch.remove()

    assert kept["complete"] is True and len(kept["kept"]) == 2
    assert report["removed"] is True and not artifact.exists()
    for entry in kept["kept"]:
        copy = Path(entry["path"])
        assert copy.exists(), "the evidence outlives the scratch it came from"
        assert file_digest(copy) == entry["sha256"], "and it is the same bytes, re-read from disk"
    assert (tmp_path / "kept" / "runner-tests-after.log").read_text(encoding="utf-8").startswith("3 passed")


def test_a_preserved_copy_that_cannot_be_written_is_reported_not_assumed(tmp_path, monkeypatch):
    """A failure to keep evidence is the one thing that must not be silent."""
    root = tmp_path / "scratch"
    root.mkdir()
    scratch = Scratch(root)
    source = root / "diff.txt"
    source.write_text("diff --git a/slug.py b/slug.py\n", encoding="utf-8")

    def refuse(self, data):
        raise OSError("the destination is full")

    monkeypatch.setattr(Path, "write_bytes", refuse)
    report = scratch.preserve(tmp_path / "kept", [{"name": "diff.txt", "source": source}])

    assert report["complete"] is False and report["kept"] == []
    assert report["failures"][0]["name"] == "diff.txt"


def test_a_sibling_directory_is_never_touched(tmp_path):
    """Other work on the same machine keeps its data."""
    neighbour = tmp_path / "another-run"
    neighbour.mkdir()
    (neighbour / "receipt.json").write_text("{}", encoding="utf-8")
    root = tmp_path / "scratch"
    root.mkdir()
    build_repository(root)

    Scratch(root).remove()

    assert (neighbour / "receipt.json").exists()


def test_removal_is_bounded_and_says_so_when_it_runs_out_of_time(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    for index in range(5):
        (root / f"file-{index}.txt").write_text("x", encoding="utf-8")

    report = Scratch(root).remove(timeout=0.0)

    assert report["timed_out"] is True
    assert report["removed"] is False, "a bounded removal stops rather than working past its deadline"


def test_the_scratch_root_is_the_one_this_run_created(tmp_path):
    scratch = Scratch.create(prefix="zeus-scratch-test-")
    try:
        assert scratch.root.is_dir() and scratch.root.name.startswith("zeus-scratch-test-")
        assert scratch.within(scratch.root / "anything" / "deeper")
        assert not scratch.within(tmp_path)
        assert not scratch.within(scratch.root.parent)
    finally:
        scratch.remove()
    assert not scratch.root.exists()


def test_a_missing_root_cannot_be_constructed():
    with pytest.raises(OSError):
        Scratch(Path(sys.executable).parent / "does-not-exist-zeus-scratch")
