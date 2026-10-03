"""Target driver: `entry.cli_knowledge.pg` on the target tree (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C3).

`codex_harness.entry.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable
PostgreSQL (see compare/drivers/common/s10_cli_knowledge.py). The work directory is FIXED (`FIXED_WORK`), as on the
reference side: the index ids hash the resolved root path.
"""

import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s10_cli_knowledge  # noqa: E402
from codex_harness.entry.cli import main  # noqa: E402

API = SimpleNamespace(main=main)

if __name__ == "__main__":
    work = Path(s10_cli_knowledge.FIXED_WORK)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        result = s10_cli_knowledge.run_all(API, work, os.environ["ZEUS_REBUILD_PG_DSN"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    driver.finish("target", "entry.cli_knowledge.pg", result)
