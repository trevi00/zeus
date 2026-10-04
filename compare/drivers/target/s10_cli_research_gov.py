"""Target driver: `entry.cli_research_gov.pg` on the target tree (REBUILD-DESIGN-v2 §5.2a, §5.3 S10 unit C7b).

`codex_harness.entry.cli.main` runs in-process with `sys.argv` patched on a fresh schema of the labelled disposable PostgreSQL
(see compare/drivers/common/s10_cli_research_gov.py). `scripted` replaces the default clock of `DebateSessions` and `DecisionFeedback`
(the kernel `utcnow` bound at definition) with a ticking clock, as the reference driver does.
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

import s10_cli_research_gov  # noqa: E402
from codex_harness.entry.cli import main  # noqa: E402
from codex_harness.research.application.decision_feedback import DecisionFeedback  # noqa: E402
from codex_harness.research.application.dge import DebateSessions  # noqa: E402


@contextlib.contextmanager
def scripted():
    ticks = itertools.count()
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)

    def utcnow():
        return (start + timedelta(milliseconds=next(ticks))).isoformat()

    with contextlib.ExitStack() as stack:
        for owner in (DebateSessions, DecisionFeedback):
            stack.enter_context(mock.patch.object(owner.__init__, "__defaults__", (utcnow,)))
        yield


API = SimpleNamespace(main=main, scripted=scripted)

if __name__ == "__main__":
    # The dge session records a digest of the resolved repository path, so the fixture directory is a fixed path (recreated, and
    # removed at the end); the PostgreSQL schema is fixed as well, so one run at a time uses either.
    work = Path(tempfile.gettempdir()).resolve() / "zeus-s10-c7b-fixed"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        result = s10_cli_research_gov.run_all(API, work, os.environ["ZEUS_REBUILD_PG_DSN"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    driver.finish("target", "entry.cli_research_gov.pg", result)
