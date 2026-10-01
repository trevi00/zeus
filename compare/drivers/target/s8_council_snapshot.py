"""Target driver: `research.council_snapshot` on the target tree (S8 pilot 79: `research.adapters.council_snapshot`).

The API mirrors the reference driver's names over the target homes: the module and its two classes from
`research.adapters.council_snapshot`, `psycopg.connect` (the constructor's default), `AutonomousManifestError` from
`research.domain.autonomous` and `ContractError`/`digest` from the kernel. The scenario reads the kernel's default clock where M7 read
`utcnow`; the harness's scripted clock reaches it through the kernel `Clock` port: the driver sets `kernel.ids.SYSTEM_CLOCK`, the one
default `utcnow` reads (the target's standard library is never patched). The connection and the `connect` are the scenario's LABELLED
fakes."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import psycopg  # noqa: E402
import s8_council_snapshot  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.research.adapters import council_snapshot as module  # noqa: E402
from codex_harness.research.domain.autonomous import AutonomousManifestError  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)

API = SimpleNamespace(
    module=module, ReadOnlySnapshot=module.ReadOnlySnapshot, SnapshotUnavailable=module.SnapshotUnavailable, default_connect=psycopg.connect,
    AutonomousManifestError=AutonomousManifestError, ContractError=ContractError, digest=digest)

if __name__ == "__main__":
    driver.finish("target", "research.council_snapshot", s8_council_snapshot.run(API))
