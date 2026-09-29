"""Reference driver: `context.worker_profile_entry` on SOURCE M7 (REBUILD-DESIGN-v2 §5.2a, §5.3 S2).

The exact metadata command runs from the SOURCE archive root (the checkout root of the reference
distribution) with this reference venv's interpreter; the hook runs as its packaged module. Children
get the R-P child environment (fake providers first on PATH, empty homes, no credential names).
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import provider_guard  # noqa: E402
import s2_profile_entry  # noqa: E402

if __name__ == "__main__":
    root = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve()
    with tempfile.TemporaryDirectory(prefix="zeus-s2-profile-") as raw:
        work = Path(raw).resolve()
        env = provider_guard.child_environment(work / "child")
        result = s2_profile_entry.run_all(sys.executable, root, work, env)
    driver.finish("reference", "context.worker_profile_entry", result)
