"""Target driver: `observation.frontend_bytes` on the head: `frontend/monitor/**` at the repository root and the packaged resources under
`target/src/codex_harness/resources`."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s9_frontend_bytes  # noqa: E402

import codex_harness.resources as resources  # noqa: E402  (the packaged location itself, so the origin audit sees a target module)

ROOT = HERE.parents[1]
API = SimpleNamespace(frontend=ROOT / "frontend" / "monitor", resources=Path(resources.__file__).resolve().parent)

if __name__ == "__main__":
    driver.finish("target", "observation.frontend_bytes", s9_frontend_bytes.run(API))
