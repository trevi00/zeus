"""Reference driver: `observation.monitoring_projection` (M7 `application/monitoring.py`: `age_seconds`, `Monitoring`, `initiatives`)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_monitoring_projection  # noqa: E402

from codex_harness.application import monitoring as mon  # noqa: E402
from codex_harness.domain.policy import POLICY  # noqa: E402

API = SimpleNamespace(mon=mon, POLICY=POLICY)

if __name__ == "__main__":
    driver.finish("reference", "observation.monitoring_projection", s9_monitoring_projection.run(API))
