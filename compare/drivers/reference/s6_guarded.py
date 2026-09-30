"""Reference driver: `coordination.guarded_launch` (M7 guarded child launch: argv, one-shot files, guard, observe).

API additions beyond plain M7 objects: none; the lambdas only fix keyword arguments, and `run` is passed only when a
case supplies its labelled double (M7's default is `subprocess.run`).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s6_guarded  # noqa: E402

from codex_harness.adapters import continuation_process as cp  # noqa: E402
from codex_harness.adapters import owner_actions as oa  # noqa: E402

API = SimpleNamespace(
    ConductorProcesses=lambda config, host, *, spawn, environment=None, seconds=None: cp.ConductorProcesses(
        config, host, spawn=spawn, environment=environment, seconds=seconds),
    Assessments=lambda artifacts, root, *, spawn, environment=None, seconds=None: oa.Assessments(
        artifacts, root, spawn=spawn, environment=environment, seconds=seconds),
    ResearchLaunches=lambda root, repository, *, spawn, seconds=None, resolve=None, run=None: oa.ResearchLaunches(
        root, repository, spawn=spawn, seconds=seconds, resolve=resolve, **({"run": run} if run else {})),
    guard=lambda directory, command, *, seconds, sleep: cp.guard(directory, command, seconds=seconds, sleep=sleep),
    observe=cp.observe, launch_directory=cp.launch_directory)

if __name__ == "__main__":
    driver.finish("reference", "coordination.guarded_launch", s6_guarded.run(API))
