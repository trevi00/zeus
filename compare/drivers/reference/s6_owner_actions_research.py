"""Reference driver: `coordination.owner_actions_research` (M7 `OwnerActions`: the scheduler `register`/`status`/`tick`,
G1 scoped research acceptance and C3 research dispatch, over the recorded, labelled research rows of
`compare/fixtures/s6/research.json`).

The API is the s6_research one plus: `OwnerActions`, a lambda over the M7 `application.owner_actions.OwnerActions` that
passes its ports as keywords; `organization`, the M7 `bootstrap.organization` (the authority that authorizes the
assessment decision envelope); `canonical`, the M7 `domain.model.canonical`; and `owner_domain`, the M7
`domain.owner_actions` module whose names the M7 helpers use (`POLICY_SCHEMA`, `POLICY_SCHEMA_V2`, `RESEARCH_RECEIPT`,
`RESEARCH_DISPATCH`, `OWNER_PHASE`, `ASSESSOR`, `reusable_assessment`, `assessment_verdict`, `assessment_launch_id`, the
state names, `research_decision`). Plain M7 objects or lambdas over them only."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s6_owner_actions_research  # noqa: E402

from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.continuation import Continuation, LaneEvidence  # noqa: E402
from codex_harness.application.fleet import Fleet  # noqa: E402
from codex_harness.application.owner_actions import OwnerActions  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import continuation as continuation_domain  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402
from codex_harness.domain import owner_actions as owner_domain  # noqa: E402
from codex_harness.domain.fleet import repository_identity  # noqa: E402
from codex_harness.domain.model import canonical  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
POLICY = packaged_policy()
API = SimpleNamespace(
    MemoryStore=MemoryStore, Fleet=lambda store, clock, token: Fleet(store, clock=clock, token=token),
    LaneEvidence=LaneEvidence,
    Continuation=lambda store, *, fleet, lanes, conductor, validate, clock, evidence=None: Continuation(
        store, fleet=fleet, lanes=lanes, conductor=conductor, validate=validate, clock=clock, evidence=evidence),
    validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY),
    repository_identity=repository_identity, domain=continuation_domain,
    OwnerActions=lambda store, **ports: OwnerActions(store, **ports), organization=organization,
    canonical=canonical, owner_domain=owner_domain)

if __name__ == "__main__":
    driver.finish("reference", "coordination.owner_actions_research", s6_owner_actions_research.run(API))
