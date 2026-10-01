"""Reference driver: `research.program_records` (M7 `application.research_program.ResearchProgram`: the record and accounting
surface that `ProgramRunner` and the owner paths use).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `application.research_program`: `ResearchProgram`, the bucket names (`BUCKET_PROGRAMS`,
  `BUCKET_CANDIDATES`, `BUCKET_CYCLES`, `BUCKET_DISPATCHES`, `BUCKET_RECOVERIES`, `BUCKET_SUCCESSORS`, `BUCKET_HEADS`) and the
  module itself (`application`: the labelled fault seam, e.g. `eligible_attempt_scopes`);
- `application.autonomous.BUCKET` (`RUNS`); `application.fleet.BUCKET_JOBS`; `application.portfolio`: `Portfolio`, `family_id`,
  `BUCKET_INVESTIGATIONS`, `RESEARCH_REQUIRED`; `application.audit_progress`: `BUCKET_STATE`, `BUCKET_WINDOWS`;
- `domain.audit_progress`: `LOW_YIELD`, `candidate_row`; `domain.owner_actions` (`owner_actions`: the row constructors a
  research-dispatch launch row is written through); `domain.continuation.attempt_scope_id`; `domain.model.digest`;
- `domain.model.ContractError`; `domain.research_program`: `ProgramRefused`, `validate_config`;
- `POLICY` = `adapters.providers.packaged_policy()` (the `POLICY` of M7's research-program tests).
Plain M7 objects or lambdas over them only. The clock and the id source are the harness's (`determinism.install`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_program_records  # noqa: E402

from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import audit_progress as progress_application  # noqa: E402
from codex_harness.application import research_program as application  # noqa: E402
from codex_harness.application.autonomous import BUCKET as RUNS  # noqa: E402
from codex_harness.application.fleet import BUCKET_JOBS  # noqa: E402
from codex_harness.application.portfolio import (  # noqa: E402
    BUCKET_INVESTIGATIONS,
    RESEARCH_REQUIRED,
    Portfolio,
    family_id,
)
from codex_harness.domain import owner_actions  # noqa: E402
from codex_harness.domain.audit_progress import LOW_YIELD, candidate_row  # noqa: E402
from codex_harness.domain.continuation import attempt_scope_id  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402
from codex_harness.domain.research_program import ProgramRefused, validate_config  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    MemoryStore=MemoryStore, ResearchProgram=application.ResearchProgram, application=application,
    BUCKET_PROGRAMS=application.BUCKET_PROGRAMS, BUCKET_CANDIDATES=application.BUCKET_CANDIDATES,
    BUCKET_CYCLES=application.BUCKET_CYCLES, BUCKET_DISPATCHES=application.BUCKET_DISPATCHES,
    BUCKET_RECOVERIES=application.BUCKET_RECOVERIES, BUCKET_SUCCESSORS=application.BUCKET_SUCCESSORS,
    BUCKET_HEADS=application.BUCKET_HEADS, RUNS=RUNS, BUCKET_INVESTIGATIONS=BUCKET_INVESTIGATIONS, BUCKET_JOBS=BUCKET_JOBS,
    BUCKET_PROGRESS_STATE=progress_application.BUCKET_STATE, BUCKET_PROGRESS_WINDOWS=progress_application.BUCKET_WINDOWS,
    RESEARCH_REQUIRED=RESEARCH_REQUIRED, Portfolio=Portfolio, family_id=family_id, LOW_YIELD=LOW_YIELD,
    progress_candidate_row=candidate_row, owner_actions=owner_actions, attempt_scope_id=attempt_scope_id, digest=digest,
    ContractError=ContractError, ProgramRefused=ProgramRefused, validate_config=validate_config, POLICY=packaged_policy())

if __name__ == "__main__":
    driver.finish("reference", "research.program_records", s8_program_records.run(API))
