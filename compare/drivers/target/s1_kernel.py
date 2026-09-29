"""Target driver: `kernel.values` on the target tree (codex_harness.kernel, storage.message_schema).

The scripted clock/id source are injected through the kernel ports; nothing is patched.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s1_kernel  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

from codex_harness.kernel import errors, ids, message, usage  # noqa: E402
from codex_harness.kernel.policy import POLICY  # noqa: E402
from codex_harness.storage.adapters.message_schema import validate_message  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
CLOCK_PORT, IDS_PORT = PortClock(CLOCK), PortIds(IDS)

API = SimpleNamespace(
    canonical=ids.canonical, digest=ids.digest,
    envelope=lambda *a, **k: message.envelope(*a, clock=CLOCK_PORT, ids=IDS_PORT, **k),
    validate_message=validate_message, ContractError=errors.ContractError,
    ExecutionFailure=errors.ExecutionFailure, require=errors.require, usage=usage, POLICY=POLICY)

if __name__ == "__main__":
    driver.finish("target", "kernel.values", s1_kernel.run(API, CLOCK, IDS))
