"""Reference driver: `execution.output_contracts` (M7 executor output schemas and request contracts)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s4_contracts  # noqa: E402

from codex_harness.adapters import executor  # noqa: E402

if __name__ == "__main__":
    driver.finish("reference", "execution.output_contracts", s4_contracts.run(executor))
