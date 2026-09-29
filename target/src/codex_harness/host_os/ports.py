"""host_os ports: Git workspaces, candidate inspection and publication (the M7 `SourceControl` split),
and the bounded process runner other contexts use instead of creating processes themselves.

Layer: ports
Context: host_os
Owns: the Protocols only; `host_os.adapters.git_workspace.GitWorkspace` implements the first three;
    `ProcessRunner` is implemented by `host_os.adapters.process_groups.run_process` (the one spawn
    chokepoint), injected by composition (S3: the container adapters' docker/git calls)
Does not own: who may publish or merge (review), release policy, what a caller runs
Entry points: Workspaces, CandidateInspection, Publication, ProcessRunner
Contracts: INV-RELEASE-001, INV-SESSION-001

Shared infrastructure ports (`SP` in the §3.6 table). The five unrelated M7 `SourceControl` methods
are split by consumer (design §2.5) with their signatures unchanged.
"""

from __future__ import annotations

from typing import Protocol


class Workspaces(Protocol):
    def prepare(self, task_id: str, base: str) -> dict: ...
    def capture(self, workspace: dict) -> dict: ...


class CandidateInspection(Protocol):
    def inspect(self, revision: str, base: str) -> dict: ...


class Publication(Protocol):
    def publish(self, candidate: dict, title: str, body: str) -> dict: ...
    def merge(self, candidate: dict) -> dict: ...


class ProcessRunner(Protocol):
    """One bounded child: argv only (no shell), killed with its tree on timeout. Returns a
    completed-process value with `args`, `returncode`, `stdout` and `stderr` (text)."""

    def __call__(self, argv: list, cwd: str | None = None, timeout: int = 120,
                 input_text: str | None = None, env: dict | None = None): ...
