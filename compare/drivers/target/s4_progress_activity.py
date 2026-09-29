"""Target driver: `execution.progress_activity` on the target tree (execution.domain.progress_activity)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s4_progress_activity  # noqa: E402
from codex_harness.execution.domain import progress_activity  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402

API = SimpleNamespace(pa=progress_activity, ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("target", "execution.progress_activity", s4_progress_activity.run(API))
