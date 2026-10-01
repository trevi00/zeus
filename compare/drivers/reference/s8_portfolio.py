"""Reference driver: `intake.portfolio` (M7 `application.portfolio`: `Portfolio` and its module functions, and
`adapters.portfolio`).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `adapters.portfolio`: `packaged_definitions`, `portfolio` (`portfolio`), `portfolio_reconciler`,
  `DEFINITIONS`, `__all__` (`ADAPTER_ALL`);
- `application.portfolio`: `Portfolio`, `PortfolioRefused`, `validate_definitions`, `validate_evidence`, `family_id`,
  `classified_failure`, `failure_families`, `reconcile`, `job_entry`, `follow_up_view`, `project_activity`, `activity_mode`,
  `status_projection`, `inherit_binding`, the bucket names (`BUCKET_BINDINGS`, `BUCKET_ACCEPTANCES`, `BUCKET_INVESTIGATIONS`,
  `BUCKET_FOLLOWUPS`), `LINEAGE_AUTHORITY`, `FAMILY_MINIMUM`, `RESEARCH_REQUIRED`, `RESEARCHED`, `DEFERRED`, `DISPOSITIONS`,
  `FAILURE_STATUSES`, `FOLLOWUP_FAILURES`, `FOLLOWUP_LINKED`, `FOLLOWUP_UNKNOWN`, `UNCLASSIFIED`, `ACTIVITY_COUNTS`,
  `ACTIVITY_MODES`, `SAMPLE`, `STATUS_SCHEMA`, `DEFINITIONS_SCHEMA`, the `MAX_*` limits, `__all__` (`ALL`);
- `application.fleet.BUCKET_JOBS`; `domain.fleet` statuses `ACCEPTED`, `DISPATCHING`, `EXHAUSTED`, `FAILED`, `QUEUED`, `REJECTED`
  (`JOB_STATUS`); `domain.research_investigations.KIND` (`FAILURE_KIND`); `domain.audit_progress.KIND` (`PROGRESS_KIND`);
  `domain.model.ContractError`, `digest`.
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
import s8_portfolio  # noqa: E402

from codex_harness.adapters import portfolio as adapter  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import portfolio as application  # noqa: E402
from codex_harness.application.fleet import BUCKET_JOBS  # noqa: E402
from codex_harness.domain import fleet as fleet_domain  # noqa: E402
from codex_harness.domain.audit_progress import KIND as PROGRESS_KIND  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402
from codex_harness.domain.research_investigations import KIND as FAILURE_KIND  # noqa: E402

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
    JOB_STATUS=SimpleNamespace(ACCEPTED=fleet_domain.ACCEPTED, DISPATCHING=fleet_domain.DISPATCHING,
                               EXHAUSTED=fleet_domain.EXHAUSTED, FAILED=fleet_domain.FAILED, QUEUED=fleet_domain.QUEUED,
                               REJECTED=fleet_domain.REJECTED),
    packaged_definitions=adapter.packaged_definitions, portfolio=adapter.portfolio,
    portfolio_reconciler=adapter.portfolio_reconciler, DEFINITIONS=adapter.DEFINITIONS, ADAPTER_ALL=list(adapter.__all__),
    **{name: getattr(application, name) for name in names})

if __name__ == "__main__":
    driver.finish("reference", "intake.portfolio", s8_portfolio.run(API))
