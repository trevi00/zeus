"""Reference driver: `research.threshold_approvals` (M7 `application.threshold_approvals`: `ThresholdApprovals`, `parse_applied_policy`).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `application.threshold_approvals`: `ThresholdApprovals`, `parse_applied_policy`, `_time`, `BUCKET`, `EVENTS`,
  `STATES`, `ENVIRONMENT`, `REVISION`, `MAX_TTL_SECONDS`; `domain.threshold_proposals.REGISTRY`;
- `domain.model`: `ContractError`, `digest`.
The artifacts store is the scenario's LABELLED fake (M7's is `FileArtifacts`). `issue` and `consume` read the real clock only when no `now` is
passed: the scenario always passes it. The clock for the events' `at` is the harness's (`determinism.install`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_threshold_approvals  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import threshold_approvals as application  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402
from codex_harness.domain.threshold_proposals import REGISTRY  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    MemoryStore=MemoryStore, ThresholdApprovals=application.ThresholdApprovals, parse_applied_policy=application.parse_applied_policy,
    _time=application._time, BUCKET=application.BUCKET, EVENTS=application.EVENTS, STATES=application.STATES, ENVIRONMENT=application.ENVIRONMENT,
    REVISION=application.REVISION, MAX_TTL_SECONDS=application.MAX_TTL_SECONDS, REGISTRY=REGISTRY, ContractError=ContractError, digest=digest)

if __name__ == "__main__":
    driver.finish("reference", "research.threshold_approvals", s8_threshold_approvals.run(API))
