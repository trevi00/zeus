"""Reference driver: `research.threshold_policy` (M7 `adapters/threshold_policy.py`: `current_policy`) over a fake git serving the SOURCE files' texts."""

import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s10_threshold_policy as common  # noqa: E402

from codex_harness.adapters import threshold_policy as module  # noqa: E402

ROOT = Path(module.__file__).resolve().parents[1]


def tree():
    return {path: (ROOT / path.removeprefix("src/codex_harness/")).read_text(encoding="utf-8") for path in module.POLICY_PATHS}


@contextlib.contextmanager
def patched_effective_policy(policy):
    with mock.patch.object(module, "effective_policy", lambda: policy):
        yield


API = SimpleNamespace(current_policy=module.current_policy, tree=tree, patched_effective_policy=patched_effective_policy,
                      record_source_fields=True)

if __name__ == "__main__":
    driver.finish("reference", "research.threshold_policy", common.policy_cases(API))
