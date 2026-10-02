"""Reference driver: `research.audit_repair_replay` (M7 `adapters.audit_repair`: `replay_decode`).

The API holds the plain M7 function (`adapters.audit_repair.replay_decode`, which imports `AuditExecution` lazily from M7's own `adapters.audit_execution`)
and `domain.model`: `canonical`, `digest`. The function is pure: no store, clock or id source is involved."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_audit_repair_replay  # noqa: E402

from codex_harness.adapters.audit_repair import replay_decode  # noqa: E402
from codex_harness.domain.model import canonical, digest  # noqa: E402

determinism.install(determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc)), determinism.FakeIds())

API = SimpleNamespace(replay_decode=replay_decode, canonical=canonical, digest=digest)

if __name__ == "__main__":
    driver.finish("reference", "research.audit_repair_replay", s8_audit_repair_replay.run(API))
