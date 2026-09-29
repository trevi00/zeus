"""Reference driver: `execution.progress_activity` (M7 domain/progress_activity, the provider-stream projection)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s4_progress_activity  # noqa: E402

from codex_harness.domain import progress_activity  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

API = SimpleNamespace(pa=progress_activity, ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("reference", "execution.progress_activity", s4_progress_activity.run(API))
