"""Target driver: `research.audit_execution` on the target tree (S8 batch B3: `research.adapters.audit_execution`, V24 R-ae1..R-ae5).

The API mirrors the reference driver's names over the target homes. M7 builds the `ResearchAudits` inside its constructor; the target takes it
injected (R-ae1), so `audit_execution` builds it exactly as pilot 70's target driver does (its three ports: coordination's `ExecutionRecovery` as
`decision_validation`, `Outbox` and `PendingDecisions`) and passes it with the two other ports of the adapter: coordination's `execution_notices`
MODULE as `notices` (R-ae3, structural: `record`) and the EXISTING `DecisionOwnership` as `decisions` (R-ae4, its `record`). M7's `Workflow` is the
S5 composition's `WorkflowAndMessages`; the artifacts are the target `FileArtifacts` over the run-scoped directory the scenario hands out. The
LABELLED executor has no `service` and no `workflow` (the target `RunTask` has neither; R-ae2), only `store` and `artifacts`. The scenario reads
the kernel's default clock where M7 read `utcnow` and `envelope`; the harness's scripted clock and ids (the composition's) reach them through
`kernel.ids.SYSTEM_CLOCK` and `kernel.message.SYSTEM_IDS`. The import-time execution domain is pinned as the reference run pinned it."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_audit_execution  # noqa: E402
from codex_harness.coordination.application import (  # noqa: E402
    execution_notices,
    execution_recovery,
    execution_time,
)
from codex_harness.coordination.application.decisions import (  # noqa: E402
    DecisionOwnership,
    PendingDecisions,
)
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.research.adapters import audit_execution as module  # noqa: E402
from codex_harness.research.application import audit_gate  # noqa: E402
from codex_harness.research.application import research as application  # noqa: E402
from codex_harness.research.domain import research as domain  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000a0d1"  # the reference run's pinned clock-domain identity


def audit_execution(executor, runner, store, artifacts, workflow):
    validation = execution_recovery.ExecutionRecovery(store, workflow.org, artifacts, audit_binding=audit_gate.binding, clock=composition.PORT,
                                                      ids=composition.IDPORT)
    audits = application.ResearchAudits(store, None, artifacts, workflow, runner, decision_validation=validation, outbox=Outbox(),
                                        pending_decisions=PendingDecisions())
    return module.AuditExecution(executor, runner, audits=audits, notices=execution_notices,
                                 decisions=DecisionOwnership(workflow, validation, workflow.org, clock=composition.PORT, ids=composition.IDPORT))


API = SimpleNamespace(
    m7_executor=False, module=module, audit_execution=audit_execution, MemoryStore=MemoryStore, FileArtifacts=FileArtifacts,
    Workflow=lambda store, org: composition.WorkflowAndMessages(store), organization=lambda: composition.ORG,
    SourceIdentity=domain.SourceIdentity, InventoryEntry=domain.InventoryEntry, PathDisposition=domain.PathDisposition,
    SubsystemAnalysis=domain.SubsystemAnalysis, ExecutionReceipt=domain.ExecutionReceipt, PartitionCheckpoint=domain.PartitionCheckpoint,
    AdaptationProposal=domain.AdaptationProposal, IndependentReview=domain.IndependentReview, AuditDraftRejected=domain.AuditDraftRejected,
    ContractError=ContractError, canonical=canonical, digest=digest, envelope=envelope, advance=composition.CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "research.audit_execution", s8_audit_execution.run(API))
