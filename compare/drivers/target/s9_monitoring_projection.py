"""Target driver: `observation.monitoring_projection` on the target tree (`observation.application.monitoring`)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s9_monitoring_projection  # noqa: E402
from codex_harness.kernel.policy import POLICY  # noqa: E402
from codex_harness.observation.application import monitoring as mon  # noqa: E402

API = SimpleNamespace(mon=mon, POLICY=POLICY)

if __name__ == "__main__":
    driver.finish("target", "observation.monitoring_projection", s9_monitoring_projection.run(API))
