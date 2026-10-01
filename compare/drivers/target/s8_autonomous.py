"""Target driver: `research.autonomous` on the target tree (S8 pilot 68: `coordination.application.autonomous`, V12).

The API mirrors the reference driver's names over the target homes. M7's `Harness` is the S5 composition's `Service` (store,
organization, outbox flusher, incident use case) and M7's `Workflow` its `WorkflowAndMessages`; the autonomous run gets its four
injected ports (R-a1, R-a3): research's `DebateSessions` factory, evidence's `EvidenceRecords`, knowledge's promotion module and
the S5 `Operation` composition (as `s5_operation.py` builds it, plus the observer and research's design gate). The scenario reads
the kernel's default clock where M7 read `utcnow`; the harness's scripted clock (the composition's, set to the scenario's start)
reaches it through the kernel `Clock` port, and the scripted ids through the `IdSource` default of `envelope`. The module's `time` name is replaced by the scripted clock's monotonic (see below). `EvidenceUnavailable` is the scenario's LABELLED stand-in for the adapter's refusal
(`adapters/autonomous_evidence` is a later family): a `ContractError` with the adapter's message and `reason_code`."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_autonomous  # noqa: E402
from codex_harness.coordination.application import autonomous as application  # noqa: E402
from codex_harness.coordination.application.operation import Operation  # noqa: E402
from codex_harness.evidence.application.inspections import EvidenceRecords  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import canonical  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.knowledge.application import promotion as knowledge_promotion  # noqa: E402
from codex_harness.research.application import dge  # noqa: E402
from codex_harness.research.domain import autonomous as domain  # noqa: E402
from codex_harness.routing.adapters.provider_policy import packaged_policy  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.ports import MessageDeliveryError  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
ids.SYSTEM_CLOCK = composition.PORT
# The default id source: `envelope` (the module draws one per role message even though it replaces the id; the scenario's
# doubles build envelopes too) reads `kernel.message.SYSTEM_IDS`; the driver sets that module global, never the stdlib.
message.SYSTEM_IDS = composition.IDPORT
EVIDENCE_RECORDS = EvidenceRecords()
# The module reads `time.monotonic()` for the `durations` it records; M7's reference run had the stdlib clock patched. The target's
# standard library is never patched, so the driver substitutes the module's `time` name with the scripted clock's monotonic reading.
application.time = SimpleNamespace(monotonic=composition.CLOCK.monotonic)


class EvidenceUnavailable(ContractError):
    """LABELLED stand-in for `adapters.autonomous_evidence.EvidenceUnavailable` (the adapter is a later family)."""

    def __init__(self, reason_code: str):
        super().__init__("execution evidence " + reason_code)
        self.reason_code = reason_code


def autonomous_run(service, *args, **kwargs):
    def operation_factory(executor, bus, workflow, budget, collector, observer=None):
        return Operation(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                         executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector, observer=observer,
                         design_gate=SimpleNamespace(check=dge.design_gate), evidence_records=EVIDENCE_RECORDS,
                         clock=composition.PORT, ids=composition.IDPORT)

    return application.AutonomousRun(service, *args, sessions_factory=dge.DebateSessions, evidence_records=EVIDENCE_RECORDS,
                                     promotion=knowledge_promotion, operation_factory=operation_factory, **kwargs)


API = SimpleNamespace(
    MemoryStore=MemoryStore, AutonomousRun=autonomous_run, AutonomousRefused=application.AutonomousRefused,
    BUCKET=application.BUCKET, OUTCOME_BY_REASON=application.OUTCOME_BY_REASON, provider_labels=application.provider_labels,
    bus_view=application.bus_view, safe_binding=application._safe_binding, row_digest=application.row_digest,
    DebateSessions=dge.DebateSessions, DgeRefused=dge.DgeRefused, promote=knowledge_promotion.promote,
    PromotionRefused=knowledge_promotion.PromotionRefused, Harness=lambda store, org: composition.Service(store),
    Workflow=lambda store, org: composition.WorkflowAndMessages(store), organization=lambda: composition.ORG,
    packaged_policy=packaged_policy, EvidenceUnavailable=EvidenceUnavailable,
    AutonomousManifestError=domain.AutonomousManifestError, validate_autonomous_manifest=domain.validate_autonomous_manifest,
    verified_graph=domain.verified_graph, role_message_id=domain.role_message_id, ContractError=ContractError, canonical=canonical,
    envelope=envelope, MessageDeliveryError=MessageDeliveryError)

if __name__ == "__main__":
    driver.finish("target", "research.autonomous", s8_autonomous.run(API))
