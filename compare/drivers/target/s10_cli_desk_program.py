"""Target driver: `entry.cli_desk_program.pg` on the target tree (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C6c).

`codex_harness.entry.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable PostgreSQL
(see compare/drivers/common/s10_cli_desk_program.py). `environment` sets `ZEUS_COMPOSITION_PROFILE=development` (declared difference E-c21,
OWNER-DECISIONS-S10 #10; M7 had no profile); every case refuses or reads the store before a clock, bus, budget or provider is reached,
so nothing is scripted.
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

import s10_cli_desk_program  # noqa: E402
from codex_harness.entry.cli import main  # noqa: E402

API = SimpleNamespace(main=main, environment={"ZEUS_COMPOSITION_PROFILE": "development"})

if __name__ == "__main__":
    work = Path(s10_cli_desk_program.FIXED_WORK)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        result = s10_cli_desk_program.run_all(API, work, os.environ["ZEUS_REBUILD_PG_DSN"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    driver.finish("target", "entry.cli_desk_program.pg", result)
