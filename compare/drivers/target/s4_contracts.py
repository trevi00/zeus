"""Target driver: `execution.output_contracts` on the target tree (execution.domain.output_contracts)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s4_contracts  # noqa: E402
from codex_harness.execution.domain import output_contracts  # noqa: E402

if __name__ == "__main__":
    driver.finish("target", "execution.output_contracts", s4_contracts.run(output_contracts))
