"""Reference driver: `delivery.tooling` (M7 `deploy/aibox/zeus_aibox_service.py` and `scripts/aibox_data`).

The API holds the two tools exactly as SOURCE ships them:
- `launcher`: the unchanged `deploy/aibox/zeus_aibox_service.py`, loaded by path from the SOURCE tree
  (`importlib.util.spec_from_file_location`; the tool is a script, not a package);
- `data_main`: `aibox_data.cli.main` of a COPY of SOURCE `scripts/aibox_data` placed on `sys.path` (the transfer family's
  pattern; the copy keeps the SOURCE tree free of bytecode, and the tool imports the installed M7 `codex_harness`);
- `install_execve(fn)`: a context manager that makes `launcher.os.execve` the callable `fn` for the block and restores it
  (LABELLED: the common module passes a recording sentinel that raises, so no real exec ever happens).

Clock and ids come from `determinism.install`; the common module also substitutes each tool's `utcnow`, identically on both
sides."""

import contextlib
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_tooling  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)

SOURCE_ROOT = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve()
LAUNCHER_PATH = SOURCE_ROOT / "deploy" / "aibox" / "zeus_aibox_service.py"
_spec = importlib.util.spec_from_file_location("zeus_aibox_service_tooling", LAUNCHER_PATH)
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)

TOOL_COPY = Path(tempfile.mkdtemp(prefix="s7tool-ref-")).resolve()
shutil.copytree(SOURCE_ROOT / "scripts" / "aibox_data", TOOL_COPY / "aibox_data",
                ignore=shutil.ignore_patterns("__pycache__"))
sys.path.insert(0, str(TOOL_COPY))
from aibox_data import cli as data_cli  # noqa: E402


@contextlib.contextmanager
def install_execve(fn):
    saved = launcher.os.execve
    launcher.os.execve = fn
    try:
        yield
    finally:
        launcher.os.execve = saved


API = SimpleNamespace(launcher=launcher, data_main=data_cli.main, install_execve=install_execve)

if __name__ == "__main__":
    try:
        result = s7_tooling.run(API)
    finally:
        shutil.rmtree(TOOL_COPY, ignore_errors=True)
    driver.finish("reference", "delivery.tooling", result)
