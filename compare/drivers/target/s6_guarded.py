"""Target driver: `coordination.guarded_launch` on the target tree (the one GuardedChildLauncher, DESIGN-s6 §6).

The launchers are the S6 transcriptions `coordination.adapters.{conductor_launch,owner_launches}`; `guard` is the
composition's (host_os ProcessTree bound); `observe`/`launch_directory` are `coordination.adapters.guarded_launch`.
The scenario supplies every spawn/resolve/run double, exactly as on the reference side.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s6_guarded  # noqa: E402
from codex_harness.composition.guarded_launch import guard_function  # noqa: E402
from codex_harness.coordination.adapters import (  # noqa: E402
    conductor_launch,
    guarded_launch,
    owner_launches,
)

GUARD = guard_function()
API = SimpleNamespace(
    ConductorProcesses=lambda config, host, *, spawn, environment=None, seconds=None: conductor_launch.ConductorProcesses(
        config, host, spawn=spawn, environment=environment, seconds=seconds),
    Assessments=lambda artifacts, root, *, spawn, environment=None, seconds=None: owner_launches.Assessments(
        artifacts, root, spawn=spawn, environment=environment, seconds=seconds),
    ResearchLaunches=lambda root, repository, *, spawn, seconds=None, resolve=None, run=None:
        owner_launches.ResearchLaunches(root, repository, spawn=spawn, seconds=seconds, resolve=resolve, run=run),
    guard=lambda directory, command, *, seconds, sleep: GUARD(directory, command, seconds=seconds, sleep=sleep),
    observe=guarded_launch.observe, launch_directory=guarded_launch.launch_directory)

if __name__ == "__main__":
    driver.finish("target", "coordination.guarded_launch", s6_guarded.run(API))
