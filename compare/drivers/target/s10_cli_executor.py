"""Target driver: `entry.cli_executor.pgredis` on the target tree (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C5d).

`codex_harness.entry.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable PostgreSQL and a unique
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

driver.start("target")

import s10_cli_executor  # noqa: E402
from codex_harness.entry.cli import main  # noqa: E402
from codex_harness.kernel.ids import SYSTEM_IDS  # noqa: E402


@contextlib.contextmanager
def scripted():
    ticks, counter = itertools.count(), itertools.count(1)
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)

    def draw():
        return uuid.UUID(int=(0x5EED << 112) | (next(counter) << 80), version=4)

    def utcnow(clock=None):
        return (start + timedelta(milliseconds=next(ticks))).isoformat()

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(SYSTEM_IDS, "uuid4", draw))
        stack.enter_context(mock.patch("codex_harness.entry.cli.research.uuid4", draw))
        stack.enter_context(mock.patch("codex_harness.entry.cli.improve.uuid4", draw))
        for module in ("kernel.message", "storage.adapters.maintenance"):
            stack.enter_context(mock.patch("codex_harness." + module + ".utcnow", utcnow))
        yield


# E-c21: the target composes under an explicit profile (OWNER-DECISIONS-S10 #10); M7 had none.
API = SimpleNamespace(main=main, scripted=scripted, environment={"ZEUS_COMPOSITION_PROFILE": "development"})

if __name__ == "__main__":
    work = Path(tempfile.mkdtemp(prefix="zeus-s10-c5d-"))
    try:
        result = s10_cli_executor.run_all(API, work, os.environ["ZEUS_REBUILD_PG_DSN"], os.environ["ZEUS_REBUILD_REDIS_URL"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    driver.finish("target", "entry.cli_executor.pgredis", result)
