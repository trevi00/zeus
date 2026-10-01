"""Reference driver: `research.audit_progress` (M7 `application.audit_progress`: `AuditProgress`, `packaged_policy`, `status_view`).

The API holds plain M7 objects:
- `adapters.store`: `MemoryStore`, `MemoryTransaction`; `adapters.artifacts.FileArtifacts` (over a run-scoped directory);
  `application.audit_progress`: `AuditProgress`, `BUCKET_STATE`, `BUCKET_WINDOWS`, `packaged_policy`, `status_view`;
  `application.portfolio`: `BUCKET_INVESTIGATIONS`, `RESEARCH_REQUIRED`, `Portfolio` (the owner's disposition of a candidate);
- `domain.audit_progress`: `KIND`, `candidate_identity`, `candidate_label`, `eligible_candidates`, `policy_digest`, `validate_policy`,
  `validate_source` (the functions `tests/test_audit_progress.py` calls beside the module);
- `domain.research`: `SourceIdentity`, `InventoryEntry`, `PartitionCheckpoint`, `PathDisposition`, `SubsystemAnalysis`, `ObservedAsset`,
  `ExecutionReceipt`, `AuditDraftRejected`; `domain.model`: `ContractError`, `canonical`, `digest`, `envelope`, `utcnow`;
  `application.research.ResearchAudits`, `application.workflow.Workflow`, `bootstrap.organization` (the owners g8 runs).
The clock is the harness's (`determinism.install`); `advance` ticks the fake clock. The audit rows of g1-g7 are PLANTED, LABELLED
records in the shape their owners write (see `s8_audit_progress`); g8 runs the owners."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_audit_progress  # noqa: E402

from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.store import MemoryStore, MemoryTransaction  # noqa: E402
from codex_harness.application import audit_progress as application  # noqa: E402
from codex_harness.application.portfolio import (  # noqa: E402
    BUCKET_INVESTIGATIONS,
    RESEARCH_REQUIRED,
    Portfolio,
)
from codex_harness.application.research import ResearchAudits  # noqa: E402
from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import audit_progress as domain  # noqa: E402
from codex_harness.domain import research as research  # noqa: E402
from codex_harness.domain.model import (  # noqa: E402
    ContractError,
    canonical,
    digest,
    envelope,
    utcnow,
)

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000a0d1"}})

API = SimpleNamespace(
    MemoryStore=MemoryStore, MemoryTransaction=MemoryTransaction, FileArtifacts=FileArtifacts, Workflow=Workflow,
    organization=organization, ResearchAudits=ResearchAudits, AuditProgress=application.AuditProgress,
    BUCKET_STATE=application.BUCKET_STATE, BUCKET_WINDOWS=application.BUCKET_WINDOWS, packaged_policy=application.packaged_policy,
    status_view=application.status_view, BUCKET_INVESTIGATIONS=BUCKET_INVESTIGATIONS, RESEARCH_REQUIRED=RESEARCH_REQUIRED,
    Portfolio=Portfolio, KIND=domain.KIND, candidate_identity=domain.candidate_identity, candidate_label=domain.candidate_label,
    eligible_candidates=domain.eligible_candidates, policy_digest=domain.policy_digest, validate_policy=domain.validate_policy,
    validate_source=domain.validate_source, SourceIdentity=research.SourceIdentity, InventoryEntry=research.InventoryEntry,
    PartitionCheckpoint=research.PartitionCheckpoint, PathDisposition=research.PathDisposition,
    SubsystemAnalysis=research.SubsystemAnalysis, ObservedAsset=research.ObservedAsset, ExecutionReceipt=research.ExecutionReceipt,
    AuditDraftRejected=research.AuditDraftRejected, ContractError=ContractError, canonical=canonical, digest=digest,
    envelope=envelope, utcnow=utcnow, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "research.audit_progress", s8_audit_progress.run(API))
