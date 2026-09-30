"""Target driver: `coordination.workflow_handle` on the target tree (DESIGN-s5 §M; composed by
s5_coordination_composition: the S4 Workflow with the real, clock-injected terminal-operation park, and the
MessageHandler over it)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition  # noqa: E402
import s5_handle  # noqa: E402

if __name__ == "__main__":
    driver.finish("target", "coordination.workflow_handle", s5_handle.run(s5_coordination_composition.api()))
