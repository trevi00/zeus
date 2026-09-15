"""Reproduce the runner's temporary-directory cleanup failure, and name its causes separately.

The receipt says `workdir_removed: false`. That is a symptom, and "Windows is slow" is a guess. This
builds the same shape the runner builds - a throwaway git repository with a worktree - and then asks
the filesystem what actually refuses, one cause at a time.
"""
import errno
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=120)


def build(root: Path) -> dict:
    """The runner's shape: a repository, a commit, a linked worktree, packed objects."""
    repository = root / "repository"
    repository.mkdir(parents=True)
    git("init", "-b", "main", cwd=repository)
    git("config", "user.email", "zeus@local", cwd=repository)
    git("config", "user.name", "zeus", cwd=repository)
    (repository / "slug.py").write_text("def slug(text):\n    return text\n", encoding="utf-8")
    git("add", ".", cwd=repository)
    git("commit", "-m", "first", cwd=repository)
    worktrees = root / "workspaces"
    worktrees.mkdir()
    git("worktree", "add", str(worktrees / "task-1"), "-b", "harness/task-1", cwd=repository)
    # The runner's executions pack objects; packed files are the ones git makes read-only.
    git("gc", "--aggressive", "--prune=now", cwd=repository)
    return {"repository": str(repository), "worktree": str(worktrees / "task-1")}


def read_only_files(root: Path) -> list:
    found = []
    for path in root.rglob("*"):
        try:
            if path.is_file() and not (path.stat().st_mode & stat.S_IWRITE):
                found.append(str(path.relative_to(root)))
        except OSError:
            continue
    return found


def survey(root: Path) -> list:
    """What refuses to go, and why, asked one file at a time rather than through rmtree's silence."""
    refusals = []
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_file():
            continue
        try:
            path.unlink()
        except PermissionError as exc:
            writable = bool(path.stat().st_mode & stat.S_IWRITE)
            refusals.append({"path": str(path.relative_to(root)),
                             "errno": errno.errorcode.get(exc.errno, exc.errno),
                             "winerror": getattr(exc, "winerror", None),
                             "read_only_attribute": not writable,
                             # 5 is ERROR_ACCESS_DENIED, 32 is ERROR_SHARING_VIOLATION: a read-only
                             # attribute and a file somebody still holds open are different refusals.
                             "cause": ("read_only_attribute" if not writable else "in_use_or_denied")})
        except OSError as exc:
            refusals.append({"path": str(path.relative_to(root)), "errno": exc.errno,
                             "cause": "other"})
    return refusals


def case_packed_git() -> dict:
    """Case A: nothing is open. Only git's own read-only files stand in the way."""
    root = Path(tempfile.mkdtemp(prefix="zeus-repro-packed-"))
    built = build(root)
    before = read_only_files(root)
    attempts = []
    for attempt in range(5):  # exactly what the runner does today
        shutil.rmtree(root, ignore_errors=True)
        attempts.append({"attempt": attempt + 1, "exists": root.exists()})
        if not root.exists():
            break
        time.sleep(1)
    record = {"case": "packed_git_repository_no_open_handles", "built": built,
              "read_only_files_before": {"count": len(before), "sample": sorted(before)[:8]},
              "rmtree_ignore_errors_attempts": attempts, "removed": not root.exists()}
    if root.exists():
        record["refusals"] = survey(root)
    # This script cleans up after itself; a reproduction must not leave what it studied.
    if root.exists():
        for path in root.rglob("*"):
            try:
                os.chmod(path, stat.S_IWRITE)
            except OSError:
                pass
        shutil.rmtree(root, ignore_errors=True)
    record["left_behind_by_this_script"] = root.exists()
    return record


def case_open_file() -> dict:
    """Case B: one file is held open by this process. A different refusal with a different fix."""
    root = Path(tempfile.mkdtemp(prefix="zeus-repro-open-"))
    built = build(root)
    held = Path(built["worktree"]) / "held-open.log"
    handle = open(held, "w", encoding="utf-8")
    handle.write("a reader still has this\n")
    handle.flush()
    try:
        attempts = []
        for attempt in range(5):
            shutil.rmtree(root, ignore_errors=True)
            attempts.append({"attempt": attempt + 1, "exists": root.exists()})
            if not root.exists():
                break
            time.sleep(1)
        record = {"case": "one_file_held_open_by_this_process", "built": built,
                  "held_open": str(held.relative_to(root)),
                  "rmtree_ignore_errors_attempts": attempts, "removed": not root.exists()}
        if root.exists():
            record["refusals"] = survey(root)
    finally:
        handle.close()
    for path in root.rglob("*"):
        try:
            os.chmod(path, stat.S_IWRITE)
        except OSError:
            pass
    shutil.rmtree(root, ignore_errors=True)
    record["removed_after_the_handle_closed"] = not root.exists()
    record["left_behind_by_this_script"] = root.exists()
    return record


if __name__ == "__main__":
    report = {"platform": sys.platform, "python": sys.version.split()[0],
              "git": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip(),
              "cases": [case_packed_git(), case_open_file()]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
