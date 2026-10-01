"""Target driver: `delivery.tooling` on the target tree (S7 step 7).

The API holds the two tools as the target tree ships them, so the common module runs unchanged:
- `launcher`: `target/deploy/aibox/zeus_aibox_service.py`, the verbatim copy of the SOURCE launcher (tools/routine
  `copy_deploy.py --check` proves byte equality), loaded by path as the reference loads SOURCE's;
- `data_main`: `aibox_data.cli.main` of a COPY of `target/scripts/aibox_data` (pilot 44, kernel rewrites only) placed on
  `sys.path`, as the transfer family's target does for its canonical tool (the copy keeps the tree free of bytecode, and the
  tool imports the target `codex_harness`);
- `install_execve(fn)`: a context manager that makes `launcher.os.execve` the callable `fn` for the block and restores it
  (LABELLED: a recording sentinel that raises; no real exec ever happens).

The clock seam: the reference installs `determinism`; this driver installs none. Both sides' common run substitutes each
tool's `utcnow` (the launcher's and `aibox_data.inventory`'s) with the same fixed instant for the whole run, a
module-attribute substitution restored afterwards, so no digest embeds a wall-clock time."""

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

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s7_tooling  # noqa: E402

TOOL_ROOT = Path(os.environ["ZEUS_REBUILD_TARGET_SRC"]).resolve().parent
LAUNCHER_PATH = TOOL_ROOT / "deploy" / "aibox" / "zeus_aibox_service.py"
_spec = importlib.util.spec_from_file_location("zeus_aibox_service_tooling", LAUNCHER_PATH)
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)

TOOL_COPY = Path(tempfile.mkdtemp(prefix="s7tool-tgt-")).resolve()
shutil.copytree(TOOL_ROOT / "scripts" / "aibox_data", TOOL_COPY / "aibox_data",
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
    driver.finish("target", "delivery.tooling", result)
