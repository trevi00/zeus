"""Target driver: `coordination.operation` on the target tree (DESIGN-s5 §Op; composed by s5_coordination_composition:
the Operation over the shared service, the MessageHandler-backed workflow, evidence's moved-ahead EvidenceRecords
read, no design gate - the golden's manifests carry no `design`)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s5_operation  # noqa: E402
from codex_harness.coordination.application.operation import Operation  # noqa: E402
from codex_harness.coordination.domain import operation as operation_domain  # noqa: E402
from codex_harness.evidence.application.inspections import EvidenceRecords  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.routing.adapters.provider_policy import packaged_policy  # noqa: E402

POLICY = packaged_policy()


def operation(service, executor, bus, workflow, budget, collector):
    return Operation(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                     executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector,
                     evidence_records=EvidenceRecords(), clock=composition.PORT, ids=composition.IDPORT)


API = composition.api(Operation=operation, ContractError=ContractError,
                      validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY),
                      assignment_message_id=operation_domain.assignment_message_id)

if __name__ == "__main__":
    driver.finish("target", "coordination.operation", s5_operation.run(API))
