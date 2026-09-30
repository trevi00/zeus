"""Reference driver: `coordination.local_cycle` (M7 LocalCycle over M7's Harness, Workflow and ports)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s5_cycle  # noqa: E402

from codex_harness.adapters.contracts import validate_message  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import execution_time, local_cycle, workflow  # noqa: E402,F401
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import envelope  # noqa: E402
from codex_harness.ports import MessageDeliveryError  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000e5e5"}})
ORG = organization()
API = SimpleNamespace(MemoryStore=MemoryStore, service=lambda store: Harness(store, ORG),
                      workflow=lambda store: workflow.Workflow(store, ORG), LocalCycle=local_cycle.LocalCycle,
                      ClaimGuardRefused=workflow.ClaimGuardRefused, validate_message=validate_message,
                      MessageDeliveryError=MessageDeliveryError, envelope=envelope, advance=CLOCK.advance, org=ORG)

if __name__ == "__main__":
    driver.finish("reference", "coordination.local_cycle", s5_cycle.run(API))
