"""Target driver: `coordination.owner_actions_research` on the target tree (the OwnerActions split, DESIGN-s6 §4)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s6_owner_actions_composition  # noqa: E402
import s6_owner_actions_research  # noqa: E402

if __name__ == "__main__":
    driver.finish("target", "coordination.owner_actions_research",
                  s6_owner_actions_research.run(SimpleNamespace(**s6_owner_actions_composition.api())))
