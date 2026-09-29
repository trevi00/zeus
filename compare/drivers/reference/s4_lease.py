"""Reference driver: `execution.lease_progress` (M7 executor.LeaseProgress)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s4_lease  # noqa: E402

from codex_harness.adapters import executor  # noqa: E402

if __name__ == "__main__":
    driver.finish("reference", "execution.lease_progress", s4_lease.run(executor))
