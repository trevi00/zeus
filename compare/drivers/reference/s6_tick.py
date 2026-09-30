"""Reference driver: `coordination.continuation_tick` (M7 `Continuation.tick`/`drain` over labelled lane rows)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s6_tick  # noqa: E402

from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.continuation import Continuation, LaneEvidence  # noqa: E402
from codex_harness.application.fleet import Fleet  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402
from codex_harness.domain.fleet import repository_identity  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
POLICY = packaged_policy()
API = SimpleNamespace(
    MemoryStore=MemoryStore, Fleet=lambda store, clock, token: Fleet(store, clock=clock, token=token),
    LaneEvidence=LaneEvidence,
    Continuation=lambda store, *, fleet, lanes, conductor, validate, clock: Continuation(
        store, fleet=fleet, lanes=lanes, conductor=conductor, validate=validate, clock=clock),
    validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY),
    repository_identity=repository_identity)

if __name__ == "__main__":
    driver.finish("reference", "coordination.continuation_tick", s6_tick.run(API))
