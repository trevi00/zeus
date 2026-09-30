"""Target driver: `coordination.continuation_tick` on the target tree (the Continuation split, DESIGN-s6 §3; composed by s6_continuation_composition)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s6_continuation_composition  # noqa: E402
import s6_tick  # noqa: E402

if __name__ == "__main__":
    driver.finish("target", "coordination.continuation_tick", s6_tick.run(SimpleNamespace(**s6_continuation_composition.api())))
