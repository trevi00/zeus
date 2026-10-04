"""Reference driver: `entry.cli_executor.pgredis` on SOURCE M7 (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C5d).

M7 `codex_harness.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable PostgreSQL and a unique
namespace of the labelled disposable Redis (see compare/drivers/common/s10_cli_executor.py).
"""

import contextlib
import itertools
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s10_cli_executor  # noqa: E402

from codex_harness.cli import main  # noqa: E402



@contextlib.contextmanager
def scripted():
    ticks, counter = itertools.count(), itertools.count(1)
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)

    def draw():
        return uuid.UUID(int=(0x5EED << 112) | (next(counter) << 80), version=4)

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch("codex_harness.domain.model.uuid4", draw))
        stack.enter_context(mock.patch("codex_harness.cli.uuid4", draw))
        for module in ("domain.model", "adapters.maintenance"):
            stack.enter_context(mock.patch("codex_harness." + module + ".utcnow",
                                           lambda: (start + timedelta(milliseconds=next(ticks))).isoformat()))
        yield


API = SimpleNamespace(main=main, scripted=scripted, environment={})

if __name__ == "__main__":
    work = Path(tempfile.mkdtemp(prefix="zeus-s10-c5d-"))
    try:
        result = s10_cli_executor.run_all(API, work, os.environ["ZEUS_REBUILD_PG_DSN"], os.environ["ZEUS_REBUILD_REDIS_URL"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    driver.finish("reference", "entry.cli_executor.pgredis", result)
