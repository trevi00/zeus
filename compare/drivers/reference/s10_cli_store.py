"""Reference driver: `entry.cli_store.pg` on SOURCE M7 (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C2a).

M7 `codex_harness.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable
PostgreSQL (see compare/drivers/common/s10_cli_store.py); tasks are seeded through M7's own `Workflow.submit`.
"""

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s10_cli_store  # noqa: E402

from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import build  # noqa: E402
from codex_harness.cli import main  # noqa: E402


def seed(message):
    service = build()
    return Workflow(service.store, service.org).submit(message)


API = SimpleNamespace(main=main, seed=seed)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s10-c2a-") as raw:
        result = s10_cli_store.run_all(API, Path(raw).resolve(), os.environ["ZEUS_REBUILD_PG_DSN"])
    driver.finish("reference", "entry.cli_store.pg", result)
