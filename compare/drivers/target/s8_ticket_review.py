"""Target driver: `intake.ticket_review` on the target tree (S8 pilot 87: `intake.adapters.ticket_review`).

The API mirrors the reference driver's name over the target home: `render_ticket_review` from `intake.adapters.ticket_review`."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_ticket_review  # noqa: E402
from codex_harness.intake.adapters.ticket_review import render_ticket_review  # noqa: E402

API = SimpleNamespace(render_ticket_review=render_ticket_review)

if __name__ == "__main__":
    driver.finish("target", "intake.ticket_review", s8_ticket_review.run(API))
