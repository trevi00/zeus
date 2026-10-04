"""Target driver: `entry.cli_ticket_sdd.pg` on the target tree (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C2c).

`codex_harness.entry.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable PostgreSQL
(see compare/drivers/common/s10_cli_ticket_sdd.py). `scripted` replaces the ticket-id `uuid4` and the `utcnow` of the ticket,
ticket-lifecycle, SDD and artifact modules with a counter and a ticking clock.
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

import s10_cli_ticket_sdd  # noqa: E402
from codex_harness.entry.cli import main  # noqa: E402


@contextlib.contextmanager
def scripted():
    ticks = itertools.count()
    counter = itertools.count(1)
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)

    def utcnow():
        return (start + timedelta(milliseconds=next(ticks))).isoformat()

    class Clock:
        @staticmethod
        def now(tz=None):
            return start + timedelta(milliseconds=next(ticks))

    with contextlib.ExitStack() as stack:
        for module in ("intake.application.tickets", "intake.application.ticket_lifecycle", "review.application.sdd",
                       "storage.adapters.file_artifacts"):
            stack.enter_context(mock.patch("codex_harness." + module + ".utcnow", lambda clock=None: utcnow()))
        stack.enter_context(mock.patch("codex_harness.intake.application.tickets.uuid4",
                                       lambda: uuid.UUID(int=(0x5EED << 112) | (next(counter) << 80), version=4)))
        stack.enter_context(mock.patch("codex_harness.intake.application.ticket_lifecycle.datetime", Clock))
        yield


API = SimpleNamespace(main=main, scripted=scripted)

if __name__ == "__main__":
    # The SDD iteration id digests the spec's origin (the repository and the path), so the fixture directory is a fixed path
    # (recreated, and removed at the end); the PostgreSQL schema is fixed as well, so one run at a time uses either.
    work = Path(tempfile.gettempdir()).resolve() / "zeus-s10-c2c-fixed"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        result = s10_cli_ticket_sdd.run_all(API, work, os.environ["ZEUS_REBUILD_PG_DSN"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    driver.finish("target", "entry.cli_ticket_sdd.pg", result)
