"""Target driver: `intake.portfolio` on the target tree (S8 pilot 63: `intake.application.portfolio` and
`intake.adapters.portfolio`).

The API mirrors the reference driver's names over the target homes: the bucket and research constants from
`intake.domain.portfolio` (R-p1/R-p2), the Fleet status constants as intake publishes them (R-p3, pinned equal to
coordination's by test_s8_portfolio_move) and `BUCKET_JOBS` from `intake.application.portfolio_lineage`. The scenario
reads the kernel's default system clock in a few places (`reconcile(store)`), as M7 read `utcnow`; so the harness's scripted
clock is installed exactly as the reference driver installs it (`determinism.install`), over the target's loaded modules."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_portfolio  # noqa: E402
from codex_harness.intake.adapters import portfolio as adapter  # noqa: E402
from codex_harness.intake.application import portfolio as application  # noqa: E402
from codex_harness.intake.application.portfolio_lineage import BUCKET_JOBS  # noqa: E402
from codex_harness.intake.domain import backlog as fleet_constants  # noqa: E402
from codex_harness.intake.domain.portfolio import FAILURE_KIND, PROGRESS_KIND  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

names = ("Portfolio", "PortfolioRefused", "validate_definitions", "validate_evidence", "family_id", "classified_failure",
         "failure_families", "reconcile", "job_entry", "follow_up_view", "project_activity", "activity_mode", "status_projection",
         "inherit_binding", "BUCKET_BINDINGS", "BUCKET_ACCEPTANCES", "BUCKET_INVESTIGATIONS", "BUCKET_FOLLOWUPS", "LINEAGE_AUTHORITY",
         "FAMILY_MINIMUM", "RESEARCH_REQUIRED", "RESEARCHED", "DEFERRED", "DISPOSITIONS", "FAILURE_STATUSES", "FOLLOWUP_FAILURES",
         "FOLLOWUP_LINKED", "FOLLOWUP_UNKNOWN", "UNCLASSIFIED", "ACTIVITY_COUNTS", "ACTIVITY_MODES", "SAMPLE", "STATUS_SCHEMA",
         "DEFINITIONS_SCHEMA", "MAX_PROJECTS", "MAX_CRITERIA", "MAX_ID", "MAX_TITLE", "MAX_TEXT", "MAX_REF", "MAX_REFS")

API = SimpleNamespace(
    MemoryStore=MemoryStore, BUCKET_JOBS=BUCKET_JOBS, FAILURE_KIND=FAILURE_KIND, PROGRESS_KIND=PROGRESS_KIND,
    ContractError=ContractError, digest=digest, ALL=list(application.__all__),
    JOB_STATUS=SimpleNamespace(ACCEPTED=fleet_constants.ACCEPTED, DISPATCHING=fleet_constants.DISPATCHING,
                               EXHAUSTED=fleet_constants.EXHAUSTED, FAILED=fleet_constants.FAILED,
                               QUEUED=fleet_constants.QUEUED, REJECTED=fleet_constants.REJECTED),
    packaged_definitions=adapter.packaged_definitions, portfolio=adapter.portfolio,
    portfolio_reconciler=adapter.portfolio_reconciler, DEFINITIONS=adapter.DEFINITIONS, ADAPTER_ALL=list(adapter.__all__),
    **{name: getattr(application, name) for name in names})

if __name__ == "__main__":
    driver.finish("target", "intake.portfolio", s8_portfolio.run(API))
