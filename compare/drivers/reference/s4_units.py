"""Reference driver: `execution.units` (M7 domain/provider_stream and domain/worker_sessions, pure units)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s4_units  # noqa: E402

from codex_harness.domain import provider_stream, worker_sessions  # noqa: E402

if __name__ == "__main__":
    driver.finish("reference", "execution.units", s4_units.run(provider_stream, worker_sessions))
