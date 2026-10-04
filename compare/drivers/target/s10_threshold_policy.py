"""Target driver: `research.threshold_policy` on the target tree (`research.adapters.threshold_policy.current_policy`, S10 unit T1/T2).

The fake git serves the target `POLICY_PATHS` files' texts under `GIT_PREFIX`. `sources` and `revision` are not recorded (declared `absent`, V20 §18.3)."""

import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s10_threshold_policy as common  # noqa: E402
from codex_harness.research.adapters import threshold_policy as module  # noqa: E402

ROOT = Path(module.__file__).resolve().parents[3]


def tree():
    return {module.GIT_PREFIX + entry: (ROOT / entry).read_text(encoding="utf-8") for entry in module.POLICY_PATHS}


@contextlib.contextmanager
def patched_effective_policy(policy):
    with mock.patch.object(module, "effective_policy", lambda: policy):
        yield


API = SimpleNamespace(current_policy=module.current_policy, tree=tree, patched_effective_policy=patched_effective_policy,
                      record_source_fields=False)

if __name__ == "__main__":
    driver.finish("target", "research.threshold_policy", common.policy_cases(API))
