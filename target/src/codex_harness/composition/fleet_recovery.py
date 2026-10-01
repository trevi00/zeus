"""Composition of the fleet recovery collectors: the Docker call and the wired `state`, `run_records` and git source (DESIGN-s7 adapters-move §14).

Layer: composition
Owns: `_docker` (M7 `adapters/isolated_worker.py`, moved ahead of S3) and the collector wiring
Does not own: the rest of the isolated worker (S3), the machine call budget (S10)
Entry points: collectors
Contracts: INV-FLEET-001

Moved ahead of its slice from M7 `adapters/isolated_worker.py` (SOURCE e38aa722) through named rules (A/evidence/rebuild/s7/fleet-recovery-move/move_aheads.py); the only changes are the homes of `run_process` (host_os.adapters.process_groups) and `docker_environment` (execution.adapters.containers.owned_container, which only composition may import next to host_os); the body is otherwise M7's.
"""
from __future__ import annotations

import subprocess

from codex_harness.execution.adapters.containers.owned_container import docker_environment
from codex_harness.host_os.adapters.process_groups import run_process


def _docker(docker, args, *, timeout, env=None):
    try:
        return run_process([docker, *args], timeout=timeout, env=env if env is not None else docker_environment())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess([docker, *args], None, "", type(exc).__name__)
