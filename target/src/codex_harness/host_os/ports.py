"""host_os ports: Git workspaces, candidate inspection and publication (the M7 `SourceControl` split),
and the bounded process runner other contexts use instead of creating processes themselves.

Layer: ports
Context: host_os
Owns: the Protocols only, and `ProcessCancelled` (the one exception class a logged child's owner-cancellation
    raises; a value other contexts catch, defined here so they need not import an adapter, S8 V19);
    `host_os.adapters.git_workspace.GitWorkspace` implements the first three;
    `ProcessRunner` is implemented by `host_os.adapters.process_groups.run_process`,
    `LoggedProcessRunner` by `host_os.adapters.process_groups.run_logged_process` and
    `ChildProcesses` by `host_os.adapters.process_groups.ChokepointProcesses` (the one spawn
    chokepoint), both injected by composition (S3: the container adapters' docker/git calls, the
    staging export and the attached transports)
Does not own: who may publish or merge (review), release policy, what a caller runs
Entry points: Workspaces, CandidateInspection, Publication, ProcessRunner, LoggedProcessRunner, ProcessCancelled, ChildProcesses, GitBlobSource
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


class ProcessCancelled(KeyboardInterrupt):
    """A logged child interrupted by the owner; `observation` says what cleanup could prove."""

    def __init__(self, observation: dict):
        super().__init__("process cancelled")
        self.observation = observation


class LoggedProcessRunner(Protocol):
    """One bounded child whose stdout/stderr stream straight into owner files, so a deadline keeps them: returns the observation
    (`exit_code`, `timed_out`, cleanup facts); an owner interruption raises `ProcessCancelled` after the same cleanup."""

    def __call__(self, argv: list[str], *, stdout_path, stderr_path, cwd: str | None = None,
                 timeout: int = 120, env: dict | None = None) -> dict: ...


class ChildProcesses(Protocol):
    """`subprocess.run`/`subprocess.Popen`-compatible creation through the one chokepoint: the same
    arguments and results, with the no-console keywords applied (`process_group=True` also gives the
    child its own process group for the caller's kill path)."""

    def run(self, argv: list, *, process_group: bool = False, **kwargs): ...
    def popen(self, argv: list, *, process_group: bool = False, **kwargs): ...


class GitBlobSource(Protocol):
    """Pinned bytes from Git (M7 `GitSource`): whether a commit exists, and the (mode, bytes) of a path at it."""

    def commit_exists(self, revision: str) -> bool: ...
    def blob(self, revision: str, path: str) -> tuple[str | None, bytes]: ...
