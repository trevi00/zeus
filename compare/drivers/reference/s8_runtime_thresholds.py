"""Reference driver: `research.runtime_thresholds` (M7 `adapters/runtime_thresholds.py`: `resolve_policy`, `effective_policy`).

The API holds the plain M7 objects (`NATIVE_DEFAULTS`, `POLICY_FILE` get/set, `REGISTRY`). The clock for the records' `created_at` is the harness's (`determinism.install`).
Artifacts, the policy provider and the native evaluator are the scenario's LABELLED fakes."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_thresholds_a as common  # noqa: E402

from codex_harness.adapters import runtime_thresholds as module  # noqa: E402
from codex_harness.domain.threshold_proposals import REGISTRY  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

def set_policy_file(path):
    module.POLICY_FILE = path


API = SimpleNamespace(resolve_policy=module.resolve_policy, effective_policy=module.effective_policy, NATIVE_DEFAULTS=module.NATIVE_DEFAULTS,
                      REGISTRY=REGISTRY, get_policy_file=lambda: module.POLICY_FILE, set_policy_file=set_policy_file)

if __name__ == "__main__":
    driver.finish("reference", "research.runtime_thresholds", common.runtime_thresholds(API))
