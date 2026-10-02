"""Reference driver: `observation.frontend_checks` (M7 `adapters/monitor_frontend_checks.py`, U9).

`observe` and `main` are M7's own; `capture=None` leaves M7's default in place (the real `evidence_inspection._capture` that the module imports at module level). No clock or id
source is installed: temporary paths, the interpreter path and the durations are normalized by the shared steps."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_frontend_checks  # noqa: E402

import codex_harness.adapters.monitor_frontend_checks as module  # noqa: E402


def observe(cwd, node=None, dependencies=None, capture=None):
    return module.observe(cwd, node=node, dependencies=dependencies, **({} if capture is None else {"capture": capture}))


API = SimpleNamespace(module=module, observe=observe, main=module.main, real_capture=lambda: module._capture)

if __name__ == "__main__":
    driver.finish("reference", "observation.frontend_checks", s9_frontend_checks.run(API))
