"""Reference driver: `entry.cli_bus.pgredis` on SOURCE M7 (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C4).

M7 `codex_harness.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable PostgreSQL and a unique
namespace of the labelled disposable Redis (see compare/drivers/common/s10_cli_bus.py).
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s10_cli_bus  # noqa: E402
from codex_harness.cli import main  # noqa: E402

API = SimpleNamespace(main=main)

if __name__ == "__main__":
    work = Path(tempfile.mkdtemp(prefix="zeus-s10-c4-"))
    try:
        result = s10_cli_bus.run_all(API, work, os.environ["ZEUS_REBUILD_PG_DSN"], os.environ["ZEUS_REBUILD_REDIS_URL"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    driver.finish("reference", "entry.cli_bus.pgredis", result)
