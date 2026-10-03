"""Reference driver: `entry.cli_knowledge.pg` on SOURCE M7 (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C3).

M7 `codex_harness.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable
PostgreSQL (see compare/drivers/common/s10_cli_knowledge.py). The work directory is FIXED (`FIXED_WORK`): M7's index ids hash
the resolved root path, so a random temporary directory would make the golden nondeterministic and a mask would be needed.
"""

import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s10_cli_knowledge  # noqa: E402

from codex_harness.cli import main  # noqa: E402

API = SimpleNamespace(main=main)

if __name__ == "__main__":
    work = Path(s10_cli_knowledge.FIXED_WORK)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        result = s10_cli_knowledge.run_all(API, work, os.environ["ZEUS_REBUILD_PG_DSN"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    driver.finish("reference", "entry.cli_knowledge.pg", result)
