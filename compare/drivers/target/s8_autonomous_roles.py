"""Target driver: `research.autonomous_roles` on the target tree (S8 pilot 81: `research.adapters.autonomous_roles`).

The API mirrors the reference driver's names: every name the moved module defines or imports, plus the kernel `ContractError`. The executor, its
git and its `_run` are the scenario's LABELLED fakes."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_autonomous_roles  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.research.adapters import autonomous_roles as module  # noqa: E402

API = SimpleNamespace(**{k: v for k, v in vars(module).items() if not k.startswith("__")}, module=module, ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("target", "research.autonomous_roles", s8_autonomous_roles.run(API))
