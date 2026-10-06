"""Composition of the owner-action plan publisher: the host_os runner, the plan loader and the Git source.

Layer: composition
Owns: the wiring of `GitPlanPublisher` (the V6 chokepoint `process_groups.run`, `host_delivery.load_plan` bound to
`backlog_blobs.read_blob`, `git_source.GitSource`), the same wiring the canaries and host_delivery drivers use
Does not own: the publisher itself (`coordination.adapters.owner_actions`), the owner-action policy and run loop (S10)
Entry points: git_plan_publisher
Contracts: INV-OWNER-ACTIONS-001
"""
from __future__ import annotations

from functools import partial

from codex_harness.coordination.adapters.owner_actions import GIT_TIMEOUT, GitPlanPublisher
from codex_harness.delivery.adapters import host_delivery
from codex_harness.host_os.adapters import git_source, process_groups
from codex_harness.intake.adapters import backlog_blobs


def git_plan_publisher(repository, *, timeout: int = GIT_TIMEOUT) -> GitPlanPublisher:
    return GitPlanPublisher(repository, timeout=timeout, runner=process_groups.run,
                            load_plan=partial(host_delivery.load_plan, read_blob=backlog_blobs.read_blob),
                            git_source=git_source.GitSource)
