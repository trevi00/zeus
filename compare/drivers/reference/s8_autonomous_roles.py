"""Reference driver: `research.autonomous_roles` (M7 `adapters/autonomous_roles.py`: the `dge_role` executor action).

The API is the plain M7 module `adapters.autonomous_roles` (every public and private name it defines or imports) plus `domain.model.ContractError`.
The executor, its git and its `_run` are the scenario's LABELLED fakes; the harness clock and ids are installed but unused."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_autonomous_roles  # noqa: E402

from codex_harness.adapters import autonomous_roles as module  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

determinism.install(determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc)), determinism.FakeIds())

API = SimpleNamespace(**{k: v for k, v in vars(module).items() if not k.startswith("__")}, module=module, ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("reference", "research.autonomous_roles", s8_autonomous_roles.run(API))
