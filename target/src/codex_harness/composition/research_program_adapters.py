"""Composition of the research program adapters: the host_os process runner and Git source injected into `GitCapture`.

Layer: composition
Owns: the wiring of `GitCapture` (the host_os `process_groups.run_process` and `git_source.GitSource`), the same wiring the
program drivers use
Does not own: the adapter itself (`research.adapters.research_program`); the dge `verify_sources` that `collect_local` takes
(an S10 CLI module with no target home yet: its wiring is a named S10 carry, `local_collector` binds it once it exists)
Entry points: git_capture, local_collector
Contracts: INV-RESEARCH-PROGRAM-001
"""
from __future__ import annotations

from functools import partial

from codex_harness.host_os.adapters import git_source, process_groups
from codex_harness.research.adapters.research_program import GIT_TIMEOUT, GitCapture, collect_local


def git_capture(repository, *, timeout: int = GIT_TIMEOUT) -> GitCapture:
    return GitCapture(repository, timeout, run_process=process_groups.run_process, git_source=git_source.GitSource)


def local_collector(verify_sources):
    """`collect_local` with the dge verifier bound (S10 supplies `verify_sources`)."""
    return partial(collect_local, verify_sources=verify_sources)
