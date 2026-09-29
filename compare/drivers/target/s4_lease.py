"""Target driver: `execution.lease_progress` on the target tree (execution.application.lease_progress)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s4_lease  # noqa: E402
from codex_harness.execution.application import lease_progress  # noqa: E402

if __name__ == "__main__":
    driver.finish("target", "execution.lease_progress", s4_lease.run(lease_progress))
