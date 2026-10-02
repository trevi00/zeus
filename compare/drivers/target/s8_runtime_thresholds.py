"""Target driver: `research.runtime_thresholds` on the target tree (S8 pilot 92: `research.adapters.runtime_thresholds`).

The API mirrors the reference driver over the target homes (`REGISTRY` from `research.domain.threshold_proposals`).
The events' clock reaches the kernel through the `Clock` port (`kernel.ids.SYSTEM_CLOCK`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_thresholds_a as common  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.research.adapters import runtime_thresholds as module  # noqa: E402
from codex_harness.research.domain.threshold_proposals import REGISTRY  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)

def set_policy_file(path):
    module.POLICY_FILE = path


API = SimpleNamespace(resolve_policy=module.resolve_policy, effective_policy=module.effective_policy, NATIVE_DEFAULTS=module.NATIVE_DEFAULTS,
                      REGISTRY=REGISTRY, get_policy_file=lambda: module.POLICY_FILE, set_policy_file=set_policy_file)

if __name__ == "__main__":
    driver.finish("target", "research.runtime_thresholds", common.runtime_thresholds(API))
