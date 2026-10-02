"""Reference driver: `observation.monitoring_readiness` (M7 `adapters/monitoring_readiness.py`: the readiness assessment of one snapshot file).

The API is the plain M7 module `adapters.monitoring_readiness` (functions `readiness`, `snapshot_state`, `envelope_state`, `source_states`,
`elapsed`, `parse`, `state` and the constants). Snapshot files live in the scenario's own temp directory (normalized by the common driver's
documented rule); the harness clock is deliberately NOT installed: `determinism.install` replaces `datetime.datetime` in the module with a subclass, so the module's
`isinstance(now, datetime)` check would refuse the scenario's real datetimes. Every case passes `now` explicitly except the one default-shape
case, which records the shape of `checked_at` only (never its value)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_monitoring_readiness  # noqa: E402

from codex_harness.adapters import monitoring_readiness as API  # noqa: E402

if __name__ == "__main__":
    driver.finish("reference", "observation.monitoring_readiness", s8_monitoring_readiness.run(API))
