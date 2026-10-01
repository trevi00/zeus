"""Composition of the research program adapters: the host_os process runner and Git source injected into `GitCapture`, and the
dge `verify_sources` injected into `collect_local` and `ProgramRunner`.

Layer: composition
Owns: the wiring of `GitCapture` (the host_os `process_groups.run_process` and `git_source.GitSource`) and of the dge source
verifier (`research.adapters.dge_sources.verify_sources`, S8 V14), the same wiring the program drivers use
Does not own: the adapters themselves (`research.adapters.research_program`, `research.adapters.dge_sources`)
Entry points: git_capture, local_collector, program_runner
Contracts: INV-RESEARCH-PROGRAM-001
"""
from __future__ import annotations

from functools import partial

from codex_harness.host_os.adapters import git_source, process_groups
from codex_harness.research.adapters import dge_sources
from codex_harness.research.adapters.research_program import (
    GIT_TIMEOUT,
    GitCapture,
    ProgramRunner,
    collect_local,
)


def git_capture(repository, *, timeout: int = GIT_TIMEOUT) -> GitCapture:
    return GitCapture(repository, timeout, run_process=process_groups.run_process, git_source=git_source.GitSource)


def local_collector(verify_sources=dge_sources.verify_sources):
    """`collect_local` with the dge verifier bound (production: `dge_sources.verify_sources`)."""
    return partial(collect_local, verify_sources=verify_sources)


def program_runner(*args, verify_sources=dge_sources.verify_sources, **kwargs) -> ProgramRunner:
    """`ProgramRunner` with the dge verifier wired (R-q3b); every other argument is the runner's own."""
    return ProgramRunner(*args, verify_sources=verify_sources, **kwargs)
