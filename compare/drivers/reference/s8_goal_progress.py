"""Reference driver: `intake.goal_progress` (M7 `application/goal_progress.py`: manifest validation, `evaluate_criterion`, `admit_dispatch`, `GoalProgress`,
`compare_reports`).

The API holds plain M7 objects: `adapters.store.MemoryStore`, the module's names, `application.ticket_lifecycle.transition` (the events the tickets are
closed and reopened by) and `domain.model`. The harness clock and ids are installed over every loaded `codex_harness` module, so `utcnow` reads the
scripted clock the scenario advances."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_goal_progress  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import goal_progress as module  # noqa: E402
from codex_harness.application.ticket_lifecycle import transition  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
determinism.install(CLOCK, determinism.FakeIds())

API = SimpleNamespace(
    clock=CLOCK, MemoryStore=MemoryStore, transition=transition, ContractError=ContractError, digest=digest,
    SCHEMA=module.SCHEMA, MANIFEST_FIELDS=module.MANIFEST_FIELDS, CRITERION_FIELDS=module.CRITERION_FIELDS, REPORT_FIELDS=module.REPORT_FIELDS,
    STATUSES=module.STATUSES, COUNTED=module.COUNTED, validate_manifest=module.validate_manifest, definition_hash=module.definition_hash,
    evaluate_criterion=module.evaluate_criterion, admit_dispatch=module.admit_dispatch, GoalProgress=module.GoalProgress,
    compare_reports=module.compare_reports)

if __name__ == "__main__":
    driver.finish("reference", "intake.goal_progress", s8_goal_progress.run(API))
