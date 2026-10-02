"""Reference driver: `research.audit_execution` (M7 `adapters.audit_execution`: `AuditExecution`).

The API holds plain M7 objects:
- `adapters.audit_execution` (the module: `AuditExecution`, `schema`, `assigned_body`, `output_definitions` and the constants);
  `adapters.store`: `MemoryStore`; `adapters.artifacts.FileArtifacts` (over a run-scoped directory); `bootstrap.organization`;
  `application.workflow.Workflow`;
- `domain.research` (the names `tests/test_audit_output_identity.py`, `tests/test_audit_analysis_outcomes.py` and `tests/test_research_audits.py`
  use): `SourceIdentity`, `InventoryEntry`, `PathDisposition`, `SubsystemAnalysis`, `ExecutionReceipt`, `PartitionCheckpoint`,
  `AdaptationProposal`, `IndependentReview`, `AuditDraftRejected`; `domain.model`: `ContractError`, `canonical`, `digest`, `envelope`.
M7 builds the `ResearchAudits` inside its constructor from the executor (`service.store`, `artifacts`, `workflow`) and the runner, so
`audit_execution(executor, runner, store, artifacts, workflow)` is `AuditExecution(executor, runner)`; the LABELLED executor exposes the three
attributes M7 reads (`m7_executor`). The clock and the id source are the harness's (`determinism.install`, with the import-time execution domain
pinned); `advance` ticks the fake clock."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_audit_execution  # noqa: E402

from codex_harness.adapters import audit_execution as module  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import research as domain  # noqa: E402
from codex_harness.domain.model import ContractError, canonical, digest, envelope  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000a0d1"}})


def audit_execution(executor, runner, store, artifacts, workflow):
    return module.AuditExecution(executor, runner)


API = SimpleNamespace(
    m7_executor=True, module=module, audit_execution=audit_execution, MemoryStore=MemoryStore, FileArtifacts=FileArtifacts, Workflow=Workflow,
    organization=organization, SourceIdentity=domain.SourceIdentity, InventoryEntry=domain.InventoryEntry, PathDisposition=domain.PathDisposition,
    SubsystemAnalysis=domain.SubsystemAnalysis, ExecutionReceipt=domain.ExecutionReceipt, PartitionCheckpoint=domain.PartitionCheckpoint,
    AdaptationProposal=domain.AdaptationProposal, IndependentReview=domain.IndependentReview, AuditDraftRejected=domain.AuditDraftRejected,
    ContractError=ContractError, canonical=canonical, digest=digest, envelope=envelope, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "research.audit_execution", s8_audit_execution.run(API))
