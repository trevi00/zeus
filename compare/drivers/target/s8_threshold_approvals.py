"""Target driver: `research.threshold_approvals` on the target tree (S8 pilot 86: `research.application.threshold_approvals`).

The API mirrors the reference driver's names over the target homes: the use case and its constants from
`research.application.threshold_approvals`, `REGISTRY` from `research.domain.threshold_proposals`, the memory store from storage,
`ContractError`/`digest` from the kernel. The events' `at` is the kernel's default clock where M7 read `utcnow`; the harness's scripted clock
reaches it through the kernel `Clock` port: the driver sets `kernel.ids.SYSTEM_CLOCK`, the one default `utcnow` reads (the target's standard
library is never patched). The artifacts store is the scenario's LABELLED fake."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_threshold_approvals  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.research.application import threshold_approvals as application  # noqa: E402
from codex_harness.research.domain.threshold_proposals import REGISTRY  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)

API = SimpleNamespace(
    MemoryStore=MemoryStore, ThresholdApprovals=application.ThresholdApprovals, parse_applied_policy=application.parse_applied_policy,
    _time=application._time, BUCKET=application.BUCKET, EVENTS=application.EVENTS, STATES=application.STATES, ENVIRONMENT=application.ENVIRONMENT,
    REVISION=application.REVISION, MAX_TTL_SECONDS=application.MAX_TTL_SECONDS, REGISTRY=REGISTRY, ContractError=ContractError, digest=digest)

if __name__ == "__main__":
    driver.finish("target", "research.threshold_approvals", s8_threshold_approvals.run(API))
