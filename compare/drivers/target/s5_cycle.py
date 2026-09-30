"""Target driver: `coordination.local_cycle` on the target tree (DESIGN-s5 §L; composed by
s5_coordination_composition)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition  # noqa: E402
import s5_cycle  # noqa: E402

if __name__ == "__main__":
    driver.finish("target", "coordination.local_cycle", s5_cycle.run(s5_coordination_composition.api()))
