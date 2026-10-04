"""Target driver: `entry.cli_governance.pg` on the target tree (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C7a).

`codex_harness.entry.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable PostgreSQL
(see compare/drivers/common/s10_cli_governance.py); the seeded task is submitted through the target `Workflow` (`composition.cli.workflow`).
"""

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s10_cli_governance  # noqa: E402
from codex_harness.composition import build  # noqa: E402
from codex_harness.composition.cli import workflow  # noqa: E402
from codex_harness.entry.cli import main  # noqa: E402


def seed_task(message):
    service = build()
    return workflow(service).submit(message)


API = SimpleNamespace(main=main, seed_task=seed_task)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s10-c7a-") as raw:
        result = s10_cli_governance.run_all(API, Path(raw).resolve(), os.environ["ZEUS_REBUILD_PG_DSN"])
    driver.finish("target", "entry.cli_governance.pg", result)
