"""Target driver: `intake.goal_progress` on the target tree (S8 batch B1: `intake.application.goal_progress`).

The API mirrors the reference driver's names over the target homes: the module's names from `intake.application.goal_progress`, `transition` from
`intake.application.ticket_lifecycle` (pilot 98), the memory store from storage, the kernel's `ContractError` and `digest`. The scripted clock reaches
the target through the kernel `Clock` port (`kernel.ids.SYSTEM_CLOCK`: `utcnow`, which `transition` stamps its events with); the target's standard
library is never patched."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_goal_progress  # noqa: E402
from codex_harness.intake.application import goal_progress as module  # noqa: E402
from codex_harness.intake.application.ticket_lifecycle import transition  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)

API = SimpleNamespace(
    clock=CLOCK, MemoryStore=MemoryStore, transition=transition, ContractError=ContractError, digest=digest,
    SCHEMA=module.SCHEMA, MANIFEST_FIELDS=module.MANIFEST_FIELDS, CRITERION_FIELDS=module.CRITERION_FIELDS, REPORT_FIELDS=module.REPORT_FIELDS,
    STATUSES=module.STATUSES, COUNTED=module.COUNTED, validate_manifest=module.validate_manifest, definition_hash=module.definition_hash,
    evaluate_criterion=module.evaluate_criterion, admit_dispatch=module.admit_dispatch, GoalProgress=module.GoalProgress,
    compare_reports=module.compare_reports)

if __name__ == "__main__":
    driver.finish("target", "intake.goal_progress", s8_goal_progress.run(API))
