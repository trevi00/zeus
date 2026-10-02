"""Reference driver: `review.releases_audits` (M7 `Releases.reconcile_audits` and `Releases.request_reverification`).

The API holds plain M7 objects: `adapters.store.MemoryStore`, `bootstrap.organization` (the packaged organization), `domain.model.digest`,
`application.releases`: `Releases` (built as `Releases(store, org)`, as M7's tests build it) and the three successor-id functions.
The clock is the harness's (`determinism.install`); `advance` ticks the fake clock."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_releases_audits  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import releases  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import digest  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

ORG = organization()
API = SimpleNamespace(MemoryStore=MemoryStore, releases=lambda store: releases.Releases(store, ORG), digest=digest,
                      reverification_successor_id=releases.reverification_successor_id,
                      evaluator_successor_id=releases.evaluator_successor_id,
                      environment_successor_id=releases.environment_successor_id, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "review.releases_audits", s8_releases_audits.run(API))
