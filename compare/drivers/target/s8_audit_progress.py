"""Target driver: `research.audit_progress` on the target tree (S8 pilot 72: `research.application.audit_progress`, V11).

The API mirrors the reference driver's names over the target homes. `AuditProgress` gets its one injected port (R-ap1): intake's
`ProgressCandidates`. M7's `Workflow` is the S5 composition's `WorkflowAndMessages`, the artifacts are the target `FileArtifacts` over the
run-scoped directory the scenario hands out, and `ResearchAudits` (g8 runs the owners) is wired as the `research.audit_core` target driver
wires it (coordination's `ExecutionRecovery`, `Outbox`, `PendingDecisions`). The scenario reads the kernel's default clock where M7 read
`utcnow`; the harness's scripted clock (the composition's) reaches it through the kernel `Clock` port and `kernel.message.SYSTEM_IDS`. The
import-time execution domain is pinned as the reference run pinned it."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_audit_progress  # noqa: E402
from codex_harness.coordination.application import execution_recovery, execution_time  # noqa: E402
from codex_harness.coordination.application.decisions import PendingDecisions  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.intake.application.portfolio import Portfolio  # noqa: E402
from codex_harness.intake.application.progress_candidates import ProgressCandidates  # noqa: E402
from codex_harness.intake.domain.portfolio import BUCKET_INVESTIGATIONS, RESEARCH_REQUIRED  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import canonical, digest, utcnow  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.research.application import audit_gate  # noqa: E402
from codex_harness.research.application import audit_progress as application  # noqa: E402
from codex_harness.research.application.research import ResearchAudits  # noqa: E402
from codex_harness.research.domain import audit_progress as domain  # noqa: E402
from codex_harness.research.domain import research as research  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore, MemoryTransaction  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000a0d1"  # the reference run's pinned clock-domain identity


def audit_progress(store, artifacts, **kwargs):
    return application.AuditProgress(store, artifacts, investigations=ProgressCandidates(), **kwargs)


def research_audits(store, verifier, artifacts, workflow, runner=None):
    recovery = execution_recovery.ExecutionRecovery(store, workflow.org, artifacts, audit_binding=audit_gate.binding,
                                                    clock=composition.PORT, ids=composition.IDPORT)
    return ResearchAudits(store, verifier, artifacts, workflow, runner, decision_validation=recovery, outbox=Outbox(),
                          pending_decisions=PendingDecisions())


API = SimpleNamespace(
    MemoryStore=MemoryStore, MemoryTransaction=MemoryTransaction, FileArtifacts=FileArtifacts,
    Workflow=lambda store, org: composition.WorkflowAndMessages(store), organization=lambda: composition.ORG,
    ResearchAudits=research_audits, AuditProgress=audit_progress,
    BUCKET_STATE=application.BUCKET_STATE, BUCKET_WINDOWS=application.BUCKET_WINDOWS, packaged_policy=application.packaged_policy,
    status_view=application.status_view, BUCKET_INVESTIGATIONS=BUCKET_INVESTIGATIONS, RESEARCH_REQUIRED=RESEARCH_REQUIRED,
    Portfolio=Portfolio, KIND=domain.KIND, candidate_identity=domain.candidate_identity, candidate_label=domain.candidate_label,
    eligible_candidates=domain.eligible_candidates, policy_digest=domain.policy_digest, validate_policy=domain.validate_policy,
    validate_source=domain.validate_source, SourceIdentity=research.SourceIdentity, InventoryEntry=research.InventoryEntry,
    PartitionCheckpoint=research.PartitionCheckpoint, PathDisposition=research.PathDisposition,
    SubsystemAnalysis=research.SubsystemAnalysis, ObservedAsset=research.ObservedAsset, ExecutionReceipt=research.ExecutionReceipt,
    AuditDraftRejected=research.AuditDraftRejected, ContractError=ContractError, canonical=canonical, digest=digest,
    envelope=envelope, utcnow=utcnow, advance=composition.CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "research.audit_progress", s8_audit_progress.run(API))
