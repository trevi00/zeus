"""Reference driver: `coordination.continuation_research` (M7 owner research paths: research receipts, the owner scope
supplement and the owner capacity grant, over the recorded, labelled research-held rows of
`compare/fixtures/s6/research.json`).

The API is the s6_tick one plus: a `Continuation` lambda that also passes `evidence=` (the research-evidence port), and
`domain`, the M7 `domain.continuation` module whose names the M7 helpers use to build documents
(`RESEARCH_RECEIPT_SCHEMA`, `SUPPLEMENT_SCHEMA`, `CAPACITY_GRANT_SCHEMA`, `EVIDENCE_REPAIR`, `observed_attempt`,
`successor_id`). Plain M7 objects or lambdas over them only."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s6_research  # noqa: E402

from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.continuation import Continuation, LaneEvidence  # noqa: E402
from codex_harness.application.fleet import Fleet  # noqa: E402
from codex_harness.domain import continuation as continuation_domain  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402
from codex_harness.domain.fleet import repository_identity  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
POLICY = packaged_policy()
API = SimpleNamespace(
    MemoryStore=MemoryStore, Fleet=lambda store, clock, token: Fleet(store, clock=clock, token=token),
    LaneEvidence=LaneEvidence,
    Continuation=lambda store, *, fleet, lanes, conductor, validate, clock, evidence=None: Continuation(
        store, fleet=fleet, lanes=lanes, conductor=conductor, validate=validate, clock=clock, evidence=evidence),
    validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY),
    repository_identity=repository_identity, domain=continuation_domain)

if __name__ == "__main__":
    driver.finish("reference", "coordination.continuation_research", s6_research.run(API))
