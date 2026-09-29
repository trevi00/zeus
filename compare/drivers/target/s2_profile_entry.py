"""Target driver: `context.worker_profile_entry` on the target distribution.

The exact metadata command runs from `target/` (the checkout root of the target distribution, whose
`src/codex_harness/resources` hold the packaged profile) with the target venv's interpreter, through
the permanent shim `codex_harness.adapters.worker_profile_metadata`.
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import provider_guard  # noqa: E402
import s2_profile_entry  # noqa: E402

if __name__ == "__main__":
    root = Path(os.environ["ZEUS_REBUILD_TARGET_SRC"]).resolve().parent
    with tempfile.TemporaryDirectory(prefix="zeus-s2-profile-") as raw:
        work = Path(raw).resolve()
        env = provider_guard.child_environment(work / "child")
        result = s2_profile_entry.run_all(sys.executable, root, work, env)
    import codex_harness.adapters.worker_profile_metadata  # noqa: E402,F401  (origin check covers the shim)
    driver.finish("target", "context.worker_profile_entry", result)
