"""Reference driver: `coordination.owner_actions_migration` (M7 `OwnerActions` migration request lifecycle: `request_migration`,
`migration`, `_advance_migrations`/`_advance_migration`, `_plan_successor`, `_bind_successor`, `_finalize`, `_observe_pin`,
`_observe_request`, `_lane_refused` and the `_complete` unit with the resume of the recorded source intent, and the M7
`domain.owner_actions` names), over the REAL M7 `HostDelivery` of a lane store and the REAL `Continuation`/`Fleet` of the paused
source.

The API is the `coordination.owner_actions_delivery` reference API (see `s7_owner_actions_delivery`: the `delivery.registry`
API plus `OwnerActions`, `Continuation`, `validate_manifest`, `repository_identity`, `owner_domain`, `dc`, `UNCHANGED`,
`WITHDRAWN`, `migration_lineage_digest`, `migration_request_id`, `new_intent`, `digest`) plus:
- `Fleet(store, clock, token)` (M7 `application.fleet.Fleet`) and `LaneEvidence` (M7 `application.continuation`), the `s6_tick` API;
- `plan_binding_of(owner, policy_row, intent)`: a lambda over the M7 private `OwnerActions._plan_binding` (the M7 test calls it
  for the target-reservation cases);
- `migrated_delivery(tx, deliveries, target, release_id, revision, release)`: M7 `application.continuation._migrated_delivery`
  (the M7 test calls it on crafted lane rows).
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
import s7_owner_actions_migration  # noqa: E402

from codex_harness.adapters.git import MergeRefused  # noqa: E402
from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import continuation as continuation_application  # noqa: E402
from codex_harness.application import host_delivery as application  # noqa: E402
from codex_harness.application.continuation import Continuation, LaneEvidence  # noqa: E402
from codex_harness.application.fleet import Fleet  # noqa: E402
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
    Fleet=lambda store, clock, token: Fleet(store, clock=clock, token=token), LaneEvidence=LaneEvidence,
    Continuation=lambda store, *, fleet, lanes, conductor, validate, clock, evidence=None: Continuation(
        store, fleet=fleet, lanes=lanes, conductor=conductor, validate=validate, clock=clock, evidence=evidence),
    validate_manifest=lambda document: operation_domain.validate_manifest(document, PROVIDER),
    repository_identity=repository_identity, owner_domain=owner_domain, dc=continuation_domain,
    plan_binding_of=lambda owner, policy_row, intent: owner._plan_binding(policy_row, intent),
    migrated_delivery=continuation_application._migrated_delivery,
    **{name: getattr(domain, name) for name in NAMES})

if __name__ == "__main__":
    driver.finish("reference", "coordination.owner_actions_migration", s7_owner_actions_migration.run(API))
