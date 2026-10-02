"""Target driver: `observation.monitoring_readiness` on the target tree (S8 pilot 89: `observation.adapters.monitoring_readiness`).

The API is the target module itself (the same names as the reference driver's M7 module). As in the reference driver the harness clock is
not installed: the harness clock would replace the module's `datetime`, so every case passes its own aware `now`."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_monitoring_readiness  # noqa: E402
from codex_harness.observation.adapters import monitoring_readiness as API  # noqa: E402

if __name__ == "__main__":
    driver.finish("target", "observation.monitoring_readiness", s8_monitoring_readiness.run(API))
