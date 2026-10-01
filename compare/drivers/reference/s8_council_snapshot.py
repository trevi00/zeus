"""Reference driver: `research.council_snapshot` (M7 `adapters/council_snapshot.py`: `SnapshotUnavailable`, `ReadOnlySnapshot`).

The API holds plain M7 objects:
- `adapters.council_snapshot`: the module, `ReadOnlySnapshot`, `SnapshotUnavailable`; `psycopg.connect` (the constructor's default);
- `domain.autonomous.AutonomousManifestError`; `domain.model`: `ContractError`, `digest` (the endpoint identity is a digest of it).
The connection and the `connect` are the scenario's LABELLED fakes (as M7 `tests/test_council.py` drives the port). The clock is the
harness's (`determinism.install`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import psycopg  # noqa: E402
import s8_council_snapshot  # noqa: E402

from codex_harness.adapters import council_snapshot as module  # noqa: E402
from codex_harness.domain.autonomous import AutonomousManifestError  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    module=module, ReadOnlySnapshot=module.ReadOnlySnapshot, SnapshotUnavailable=module.SnapshotUnavailable, default_connect=psycopg.connect,
    AutonomousManifestError=AutonomousManifestError, ContractError=ContractError, digest=digest)

if __name__ == "__main__":
    driver.finish("reference", "research.council_snapshot", s8_council_snapshot.run(API))
