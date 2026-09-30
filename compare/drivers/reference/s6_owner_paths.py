"""Reference driver: `coordination.continuation_owner_paths` (M7 owner-triggered continuation paths: delivery
requalification, the migrated-delivery chain of `LaneEvidence.read`, the pure migration rules and explicit ownership
reconciliation, over labelled lane rows).

The API is the s6_tick one plus: a `Continuation` lambda that also passes `evidence=` (the research-evidence port),
`migration_source`/`migration_resume` (M7 `domain.continuation`) and `MAX_MIGRATION_HOPS` (M7
`application.continuation`). Plain M7 objects or lambdas over them only."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s6_owner_paths  # noqa: E402

from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.continuation import (  # noqa: E402
    MAX_MIGRATION_HOPS,
    Continuation,
    LaneEvidence,
)
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
    repository_identity=repository_identity,
    migration_source=continuation_domain.migration_source, migration_resume=continuation_domain.migration_resume,
    MAX_MIGRATION_HOPS=MAX_MIGRATION_HOPS)

if __name__ == "__main__":
    driver.finish("reference", "coordination.continuation_owner_paths", s6_owner_paths.run(API))
