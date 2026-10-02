"""Target driver: `observation.viewer` on the target tree (`observation.adapters.viewer_http`, desk-free: no desk and no `DeskHttp` is injected)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s9_viewer  # noqa: E402
from codex_harness.observation.adapters import viewer_http as web  # noqa: E402

API = SimpleNamespace(web=web)

if __name__ == "__main__":
    driver.finish("target", "observation.viewer", s9_viewer.run(API))
