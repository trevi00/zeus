"""Reference driver: `observation.viewer` (M7 `adapters/monitoring_web.py`, the loopback read-only HTTP viewer)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_viewer  # noqa: E402

from codex_harness.adapters import monitoring_web as web  # noqa: E402

API = SimpleNamespace(web=web)

if __name__ == "__main__":
    driver.finish("reference", "observation.viewer", s9_viewer.run(API))
