"""Reference driver: `research.audit_core` (M7 `application.research`: `ResearchAudits`).

The API holds plain M7 objects:
- `adapters.store`: `MemoryStore`, `MemoryTransaction`; `adapters.artifacts.FileArtifacts` (over a run-scoped directory);
  `bootstrap.organization`; `application.workflow.Workflow`; `application.research.ResearchAudits`;
  `application.execution_recovery.ExecutionRecovery` (`validate_decision`, as `review` runs it); `application.audit_gate`:
  `binding`, `require_adoption`, `inspect_approval` (SOURCE gate, read through M7);
- `domain.research` (the names `tests/test_research_audits.py` and `tests/test_audit_checkpoint_outcomes.py` use):
  `SourceIdentity`, `InventoryEntry`, `PathDisposition`, `SubsystemAnalysis`, `ExecutionReceipt`, `PartitionCheckpoint`,
  `AdaptationProposal`, `IndependentReview`, `ObservedAsset`, `AuditDraftRejected`, `parse_record`, `receipt_successful`,
  `reject`; `domain.model`: `ContractError`, `canonical`, `digest`, `envelope`, `require`.
The `SourceVerifier` and the runner are the scenario's LABELLED doubles (the real Git verifier and runners are later families
and never run). `seeds_from` is the labelled seam of M7's `monkeypatch.setattr('codex_harness.application.research.files',
...)` (the packaged backlog resource). Plain M7 objects or lambdas over them only. The clock and the id source are the harness's
(`determinism.install`, with the import-time execution domain pinned); `advance` ticks the fake clock."""

import contextlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_audit_core  # noqa: E402

from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.store import MemoryStore, MemoryTransaction  # noqa: E402
from codex_harness.application import audit_gate  # noqa: E402
from codex_harness.application import research as application  # noqa: E402
from codex_harness.application.execution_recovery import ExecutionRecovery  # noqa: E402
from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import research as domain  # noqa: E402
from codex_harness.domain.model import (  # noqa: E402
    ContractError,
    canonical,
    digest,
    envelope,
    require,
)

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000a0d1"}})


@contextlib.contextmanager
def seeds_from(seeds):
    """LABELLED. M7 `test_backlog_idempotent_and_preserves_legacy`: the packaged `research-backlog.json` is replaced by `seeds`."""
    original = application.files
    application.files = lambda _: SimpleNamespace(joinpath=lambda _: SimpleNamespace(read_text=lambda: json.dumps(seeds)))
    try:
        yield
    finally:
        application.files = original


API = SimpleNamespace(
    MemoryStore=MemoryStore, MemoryTransaction=MemoryTransaction, FileArtifacts=FileArtifacts, Workflow=Workflow,
    organization=organization, ResearchAudits=application.ResearchAudits, ExecutionRecovery=ExecutionRecovery,
    binding=audit_gate.binding, require_adoption=audit_gate.require_adoption, inspect_approval=audit_gate.inspect_approval,
    SourceIdentity=domain.SourceIdentity, InventoryEntry=domain.InventoryEntry, PathDisposition=domain.PathDisposition,
    SubsystemAnalysis=domain.SubsystemAnalysis, ExecutionReceipt=domain.ExecutionReceipt,
    PartitionCheckpoint=domain.PartitionCheckpoint, AdaptationProposal=domain.AdaptationProposal,
    IndependentReview=domain.IndependentReview, ObservedAsset=domain.ObservedAsset,
    AuditDraftRejected=domain.AuditDraftRejected, parse_record=domain.parse_record,
    receipt_successful=domain.receipt_successful, reject=domain.reject, ContractError=ContractError, canonical=canonical,
    digest=digest, envelope=envelope, require=require, seeds_from=seeds_from, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "research.audit_core", s8_audit_core.run(API))
