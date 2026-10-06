"""The Git, project-skill and skill-history sources of a composition over the M7 adapters.

Layer: adapters
Context: context
Owns: GitRepository, ProjectSkills, SkillHistoryRecorder (structural implementations of context.ports)
Does not own: the Git process (host_os.adapters.git_workspace), the threshold definition (research, S8)
Entry points: GitRepository, ProjectSkills, SkillHistoryRecorder
Contracts: INV-SKILL-001, INV-SKILL-HISTORY-001
"""

from __future__ import annotations

from codex_harness.context.adapters.project_skills import project_context
from codex_harness.context.adapters.skill_history import (
    finalize_delivery,
    prepare_history,
    project_identity,
    record_history,
)


class GitRepository:
    """`revision(cwd)` reads HEAD of the turn's checkout; `show` reads the configured repository,
    exactly as M7 `Executor._run` did (`_git("show", ...)` without a cwd)."""

    def __init__(self, git):
        self.git = git

    def revision(self, cwd: str) -> str:
        return self.git._git("rev-parse", "HEAD", cwd=cwd)

    def show(self, revision: str, path: str) -> str:
        return self.git._git("show", revision + ":" + path, strip=False)


class ProjectSkills:
    def __init__(self, git, artifacts, thresholds):
        self.git, self.artifacts, self.thresholds = git, artifacts, thresholds

    def select(self, cwd: str, revision: str, objective: str) -> tuple[list, dict]:
        return project_context(self.git, self.artifacts, cwd, revision, objective, thresholds=self.thresholds)


class SkillHistoryRecorder:
    def __init__(self, store, artifacts, git, clock=None):
        self.store, self.artifacts, self.git, self.clock = store, artifacts, git, clock

    def prepare(self, selection, agent, task, objective, items):
        return prepare_history(self.store, self.artifacts, project_identity(selection, self.git), agent, task,
                               objective, selection, items, self.clock)

    def finalize(self, observation, packet):
        return finalize_delivery(observation, packet)

    def record(self, observation, context_ref, guard=None):
        return record_history(observation, context_ref, guard)
