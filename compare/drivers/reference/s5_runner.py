"""Reference driver: `coordination.fleet_runner` (M7 FleetRunner over a fixture launcher)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s5_runner  # noqa: E402

from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.fleet import Fleet, FleetRunner, LaunchRefused  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
POLICY = packaged_policy()
API = SimpleNamespace(
    MemoryStore=MemoryStore, Fleet=lambda store, clock, token: Fleet(store, clock=clock, token=token),
    FleetRunner=lambda fleet, launcher, sleep, interval, **ports: FleetRunner(fleet, launcher, sleep=sleep,
                                                                           interval=interval, **ports),
    LaunchRefused=LaunchRefused,
    validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY))

if __name__ == "__main__":
    driver.finish("reference", "coordination.fleet_runner", s5_runner.run(API))
