"""Reference driver: `kernel.values` on SOURCE M7 (REBUILD-DESIGN-v2 §5.3 S1, R-C first).

M7 `domain.model` (canonical/digest/envelope/errors), `domain.policy`, `domain.usage_policy` and the
six-W schema check in `adapters.contracts`. Clock and ids are the scripted fakes, patched into the
driver process only; the reference files stay untouched.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s1_kernel  # noqa: E402

from codex_harness.adapters.contracts import validate_message  # noqa: E402
from codex_harness.domain import model, usage_policy  # noqa: E402
from codex_harness.domain.policy import POLICY  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(canonical=model.canonical, digest=model.digest, envelope=model.envelope,
                      validate_message=validate_message, ContractError=model.ContractError,
                      ExecutionFailure=model.ExecutionFailure, require=model.require, usage=usage_policy,
                      POLICY=POLICY)

if __name__ == "__main__":
    driver.finish("reference", "kernel.values", s1_kernel.run(API, CLOCK, IDS))
