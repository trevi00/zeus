"""Reference driver: `intake.ticket_review` (M7 `adapters/ticket_review.py`: `render_ticket_review`).

The API holds the plain M7 function: `adapters.ticket_review.render_ticket_review`. The reviews are built literals; the harness clock and
ids are installed but unused."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_ticket_review  # noqa: E402

from codex_harness.adapters.ticket_review import render_ticket_review  # noqa: E402

determinism.install(determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc)), determinism.FakeIds())

API = SimpleNamespace(render_ticket_review=render_ticket_review)

if __name__ == "__main__":
    driver.finish("reference", "intake.ticket_review", s8_ticket_review.run(API))
