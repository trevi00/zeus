"""The owner-action delivery plan publisher: argv-only Git with a fixed author (INV-OWNER-ACTIONS-001).

Layer: adapters
Context: coordination
Owns: `GitPlanPublisher` (the deterministic plan commit, create-only ref publication, the committed plan read), `GIT_TIMEOUT`, `PLAN_AUTHOR`
Does not own: process creation (the host_os chokepoint `process_groups.run`: injected as `runner`), the plan loader and the Git source (delivery and host_os: injected as `load_plan` and `git_source`; wired in `composition.owner_action_adapters`), the target state files (`delivery.adapters.target_files`)
Entry points: GitPlanPublisher
Contracts: INV-OWNER-ACTIONS-001

S7 named transcription of M7 `adapters/owner_actions.py` (SOURCE e38aa722, A/evidence/rebuild/s7/owner-actions-adapters/transcribe.py): `GitPlanPublisher` verbatim except the REQUIRED keywords `runner`, `load_plan` and `git_source` (V6: `subprocess.run(` -> `self.runner(`; the plan loader and Git source are injected).
"""
from __future__ import annotations

import os
import subprocess

GIT_TIMEOUT = 60
PLAN_AUTHOR = ("Zeus owner actions", "owner-actions@zeus.invalid")


class GitPlanPublisher:
    """One repository; argv-only Git with a fixed author, never a shell and never the working tree."""

    def __init__(self, repository, *, timeout: int = GIT_TIMEOUT, runner, load_plan, git_source):
        self.repository, self.timeout = str(repository), timeout
        self.runner, self.load_plan, self.git_source = runner, load_plan, git_source

    def _git(self, *args, stdin: bytes | None = None, env=None) -> subprocess.CompletedProcess:
        environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, **(env or {})}
        try:
            return self.runner(["git", "-C", self.repository, *args], input=stdin, capture_output=True,
                               timeout=self.timeout, env=environment)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("git unavailable") from exc

    def _out(self, *args, stdin: bytes | None = None, env=None) -> str:
        done = self._git(*args, stdin=stdin, env=env)
        if done.returncode:
            raise RuntimeError("git refused")
        return done.stdout.decode("ascii", "replace").strip()

    def commit_for(self, data: bytes, path: str, when: str) -> str:
        """The deterministic commit carrying exactly `data` at `path` (content addressed objects only)."""
        blob = self._out("hash-object", "-w", "--stdin", stdin=data)
        parts = path.split("/")
        entry = "100644 blob " + blob + "\t" + parts[-1] + "\n"
        tree = self._out("mktree", stdin=entry.encode("utf-8"))
        for name in reversed(parts[:-1]):
            tree = self._out("mktree", stdin=("040000 tree " + tree + "\t" + name + "\n").encode("utf-8"))
        identity = {"GIT_AUTHOR_NAME": PLAN_AUTHOR[0], "GIT_AUTHOR_EMAIL": PLAN_AUTHOR[1],
                    "GIT_COMMITTER_NAME": PLAN_AUTHOR[0], "GIT_COMMITTER_EMAIL": PLAN_AUTHOR[1],
                    "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        return self._out("commit-tree", tree, "-m", "owner delivery plan " + parts[-1], env=identity)

    def current(self, ref: str) -> str | None:
        done = self._git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
        return done.stdout.decode("ascii", "replace").strip() if done.returncode == 0 else None

    def publish(self, data: bytes, path: str, ref: str, when: str) -> dict:
        """Create `ref` at the deterministic commit only when absent; recognize our own; never move another."""
        commit = self.commit_for(data, path, when)
        existing = self.current(ref)
        if existing is None:
            done = self._git("update-ref", ref, commit, "")  # "" = must not exist yet
            existing = self.current(ref)
            if done.returncode and existing is None:
                raise RuntimeError("git refused")
        return {"revision": commit, "conflict": existing != commit}

    def load(self, revision: str, path: str) -> dict:
        return self.load_plan(self.git_source(self.repository), revision, path)
