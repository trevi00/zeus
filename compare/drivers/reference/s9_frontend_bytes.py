"""Reference driver: `observation.frontend_bytes` (the SOURCE-tracked `frontend/monitor/**` and the packaged `resources/monitor.html`,
`resources/observatory/**`, read from the SOURCE archive tree)."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_frontend_bytes  # noqa: E402

SOURCE = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve()
API = SimpleNamespace(frontend=SOURCE / "frontend" / "monitor", resources=SOURCE / "src" / "codex_harness" / "resources")

if __name__ == "__main__":
    driver.finish("reference", "observation.frontend_bytes", s9_frontend_bytes.run(API))
