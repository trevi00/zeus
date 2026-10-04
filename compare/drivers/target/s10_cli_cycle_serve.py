"""Target driver: `entry.cli_cycle_serve.pgredis` on the target tree (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C5e).

`codex_harness.entry.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable PostgreSQL and a unique
namespace of the labelled disposable Redis (see compare/drivers/common/s10_cli_cycle_serve.py). `environment` sets
`ZEUS_COMPOSITION_PROFILE=development` (declared difference E-c21, OWNER-DECISIONS-S10 #10; M7 had no profile); `scripted` replaces the local
cycle's `utcnow` with a ticking clock and the observer's process run id with a counter.
"""

import contextlib
import itertools
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s10_cli_cycle_serve  # noqa: E402
from codex_harness.entry.cli import main  # noqa: E402


@contextlib.contextmanager
def scripted():
    ticks = itertools.count()
    runs = itertools.count(1)
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)

    def utcnow():
        return (start + timedelta(milliseconds=next(ticks))).isoformat()

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch("codex_harness.coordination.application.local_cycle.utcnow", lambda clock=None: utcnow()))
        stack.enter_context(mock.patch("codex_harness.observation.domain.observation.new_process_run_id",
                                       lambda: format(next(runs), "032x")))
        yield


API = SimpleNamespace(main=main, scripted=scripted, environment={"ZEUS_COMPOSITION_PROFILE": "development"})

if __name__ == "__main__":
    work = Path(tempfile.mkdtemp(prefix="zeus-s10-c5e-"))
    try:
        result = s10_cli_cycle_serve.run_all(API, work, os.environ["ZEUS_REBUILD_PG_DSN"], os.environ["ZEUS_REBUILD_REDIS_URL"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    driver.finish("target", "entry.cli_cycle_serve.pgredis", result)
