"""Reference driver: `coordination.operation` (M7 Operation over M7's Harness, Workflow, LocalCycle, evidence
inspections and the packaged provider policy)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s5_operation  # noqa: E402

from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import execution_time, operation, workflow  # noqa: E402,F401
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402
from codex_harness.domain.model import ContractError, envelope  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000e5e5"}})
ORG = organization()
POLICY = packaged_policy()
API = SimpleNamespace(
    MemoryStore=MemoryStore, service=lambda store: Harness(store, ORG),
    workflow=lambda store: workflow.Workflow(store, ORG),
    Operation=lambda svc, executor, bus, wf, budget, collector: operation.Operation(svc, executor, bus, wf, budget,
                                                                                   collector),
    validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY),
    assignment_message_id=operation_domain.assignment_message_id, ContractError=ContractError,
    envelope=envelope, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "coordination.operation", s5_operation.run(API))
