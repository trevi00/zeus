"""Reference driver: `coordination.owner_actions_delivery` (M7 `OwnerActions` G2 plan publication and registration, the
first-activation binding and C1 requalify/withdraw, over the REAL M7 `HostDelivery` of a lane store).

The API is the `delivery.registry` reference API (see `s7_registry`: `MemoryStore`, `HostDelivery`, `organization`,
`releases`, `queue`, `AmbiguousEffect`, the M7 bucket names, the M7 `domain.host_delivery` names, `ContractError`,
`MergeRefused`, `POLICY`, `now` and `advance` over the ONE fake clock) plus:
- `OwnerActions`, a lambda over the M7 `application.owner_actions.OwnerActions` that passes its ports as keywords;
- `Continuation` (M7 `application.continuation.Continuation`, its `policy` port only), `validate_manifest` (bound to the
  packaged provider policy) and `repository_identity` (M7 `domain.fleet`), the `s6_tick` API;
- `owner_domain` (M7 `domain.owner_actions`) and `dc` (M7 `domain.continuation`), whose names the cases use;
- from `domain.host_delivery`: `UNCHANGED`, `WITHDRAWN`, `migration_lineage_digest`, `migration_request_id`, `new_intent`;
- from `domain.model`: `digest`.
Plain M7 objects or lambdas over them only."""

import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_owner_actions_delivery  # noqa: E402

from codex_harness.adapters.git import MergeRefused  # noqa: E402
from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import host_delivery as application  # noqa: E402
from codex_harness.application.continuation import Continuation  # noqa: E402
from codex_harness.application.host_delivery import HostDelivery  # noqa: E402
from codex_harness.application.owner_actions import OwnerActions  # noqa: E402
from codex_harness.application.release_queue import ReleaseQueue  # noqa: E402
from codex_harness.application.releases import Releases  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import continuation as continuation_domain  # noqa: E402
from codex_harness.domain import host_delivery as domain  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402
from codex_harness.domain import owner_actions as owner_domain  # noqa: E402
from codex_harness.domain.fleet import repository_identity  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402
from codex_harness.domain.policy import POLICY  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)
PROVIDER = packaged_policy()
NAMES = ("PLAN_SCHEMA", "REGISTRY_SCHEMA", "REGISTERED", "AWAITING_REVIEW", "VERIFYING", "PUBLISHING", "AWAITING_CI",
         "MERGE_INTENDED", "MERGED", "DRAIN_INTENDED", "SWITCHING", "AWAITING_CONSUMPTION", "ACTIVE", "BLOCKED",
         "ROLLING_BACK", "ROLLED_BACK", "CANARY_STARTUP", "CANARY_FLEET", "DeliveryRefused", "LifecycleInterrupted",
         "plan_digest", "descriptor_digest", "receipt_identity", "instance_authority", "REPLACEABLE_INSTANCES",
         "INSTANCE_INTENDED", "validate_plan", "validate_targets", "UNCHANGED", "WITHDRAWN",
         "migration_lineage_digest", "migration_request_id", "new_intent")
API = SimpleNamespace(
    MemoryStore=MemoryStore, HostDelivery=lambda store, org, **ports: HostDelivery(store, org, **ports),
    organization=organization, releases=lambda store: Releases(store, organization()),
    queue=lambda store: ReleaseQueue(store), AmbiguousEffect=application.AmbiguousEffect,
    BUCKET_TARGETS=application.BUCKET_TARGETS, BUCKET_PLANS=application.BUCKET_PLANS,
    BUCKET_INTENTS=application.BUCKET_INTENTS, BUCKET_DESCRIPTORS=application.BUCKET_DESCRIPTORS,
    BUCKET_MIGRATIONS=application.BUCKET_MIGRATIONS,
    ContractError=ContractError, MergeRefused=MergeRefused, POLICY=POLICY,
    now=lambda: CLOCK.now(timezone.utc), advance=CLOCK.advance, digest=digest,
    OwnerActions=lambda store, **ports: OwnerActions(store, **ports),
    Continuation=lambda store, *, fleet, lanes, conductor, validate, clock, evidence=None: Continuation(
        store, fleet=fleet, lanes=lanes, conductor=conductor, validate=validate, clock=clock, evidence=evidence),
    validate_manifest=lambda document: operation_domain.validate_manifest(document, PROVIDER),
    repository_identity=repository_identity, owner_domain=owner_domain, dc=continuation_domain,
    **{name: getattr(domain, name) for name in NAMES})

if __name__ == "__main__":
    driver.finish("reference", "coordination.owner_actions_delivery", s7_owner_actions_delivery.run(API))
