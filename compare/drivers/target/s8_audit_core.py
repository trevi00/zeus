"""Target driver: `research.audit_core` on the target tree (S8 pilot 70: `research.application.research`, V11).

The API mirrors the reference driver's names over the target homes. M7's `Workflow` is the S5 composition's
`WorkflowAndMessages` (the target `Workflow` plus the MessageHandler) and the artifacts are the target `FileArtifacts` over the
run-scoped directory the scenario hands out. `ResearchAudits` gets its three injected ports (R-r2..R-r4): coordination's
`ExecutionRecovery` (as the scenario's `validate_decision` step builds it: store, organization, artifacts; M7's imported
`audit_gate.binding` directly, here the injected `audit_binding`), `Outbox` and `PendingDecisions`. The scenario reads the kernel's
default clock and id source where M7 read `utcnow` and `envelope`; the harness's scripted clock and ids (the composition's) reach them
through the kernel `Clock` port and `kernel.message.SYSTEM_IDS`. The import-time execution domain is pinned as the reference run
pinned it. `SourceVerifier` and the runner are the scenario's LABELLED doubles (the real verifier and runners are later families)."""

import contextlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_audit_core  # noqa: E402
from codex_harness.coordination.application import execution_time  # noqa: E402
from codex_harness.coordination.application.decisions import PendingDecisions  # noqa: E402
from codex_harness.coordination.application.execution_recovery import ExecutionRecovery  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.errors import ContractError, require  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.research.application import audit_gate  # noqa: E402
from codex_harness.research.application import research as application  # noqa: E402
from codex_harness.research.domain import research as domain  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore, MemoryTransaction  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000a0d1"  # the reference run's pinned clock-domain identity


@contextlib.contextmanager
def seeds_from(seeds):
    """LABELLED. M7 `test_backlog_idempotent_and_preserves_legacy`: the packaged `research-backlog.json` is replaced by `seeds`."""
    original = application.files
    application.files = lambda _: SimpleNamespace(joinpath=lambda _: SimpleNamespace(read_text=lambda: json.dumps(seeds)))
    try:
        yield
    finally:
        application.files = original


def recovery(store, org, artifacts):
    return ExecutionRecovery(store, org, artifacts, audit_binding=audit_gate.binding, clock=composition.PORT, ids=composition.IDPORT)


def research_audits(store, verifier, artifacts, workflow, runner=None):
    return application.ResearchAudits(store, verifier, artifacts, workflow, runner, decision_validation=recovery(store, workflow.org, artifacts),
                                      outbox=Outbox(), pending_decisions=PendingDecisions())


API = SimpleNamespace(
    MemoryStore=MemoryStore, MemoryTransaction=MemoryTransaction, FileArtifacts=FileArtifacts,
    Workflow=lambda store, org: composition.WorkflowAndMessages(store), organization=lambda: composition.ORG,
    ResearchAudits=research_audits, ExecutionRecovery=recovery,
    binding=audit_gate.binding, require_adoption=audit_gate.require_adoption, inspect_approval=audit_gate.inspect_approval,
    SourceIdentity=domain.SourceIdentity, InventoryEntry=domain.InventoryEntry, PathDisposition=domain.PathDisposition,
    SubsystemAnalysis=domain.SubsystemAnalysis, ExecutionReceipt=domain.ExecutionReceipt,
    PartitionCheckpoint=domain.PartitionCheckpoint, AdaptationProposal=domain.AdaptationProposal,
    IndependentReview=domain.IndependentReview, ObservedAsset=domain.ObservedAsset,
    AuditDraftRejected=domain.AuditDraftRejected, parse_record=domain.parse_record,
    receipt_successful=domain.receipt_successful, reject=domain.reject, ContractError=ContractError, canonical=canonical,
    digest=digest, envelope=envelope, require=require, seeds_from=seeds_from, advance=composition.CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "research.audit_core", s8_audit_core.run(API))
