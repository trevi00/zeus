"""Target driver: `coordination.fleet_recovery` on the target tree (the Fleet split, DESIGN-s5 §F; composed by s5_fleet_composition)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s5_fleet_composition  # noqa: E402
import s5_fleet_recovery  # noqa: E402

if __name__ == "__main__":
    driver.finish("target", "coordination.fleet_recovery", s5_fleet_recovery.run(SimpleNamespace(**s5_fleet_composition.api())))
