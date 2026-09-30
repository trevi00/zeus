"""Reference driver: `delivery.migration` (the lane half of an M7 release migration: `HostDelivery.stage_migration` with
review's `Releases.request_evaluator_migration` / `request_environment_reverification` behind it, `register_migration_plan`,
`finalize_migration`, `require_controller_code` and the migration projection of `status`).

The API is the `delivery.registry` reference API (see `s7_registry`: `MemoryStore`, `HostDelivery`, `organization`,
`releases`, `queue`, `AmbiguousEffect`, the M7 bucket names, the M7 `domain.host_delivery` names, `ContractError`,
`MergeRefused`, `POLICY`, `now` and `advance` over the ONE fake clock) plus the M7 names the migration cases need:
- from `domain.host_delivery`: `WITHDRAWN`, `migration_lineage_digest`, `migration_request_id`, `new_intent`;
- from `domain.model`: `digest`;
- from `application.releases`: `evaluator_successor_id`, `environment_successor_id`, `expected_evaluator_pin`.
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
import s7_migration  # noqa: E402

from codex_harness.adapters.git import MergeRefused  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import host_delivery as application  # noqa: E402
from codex_harness.application import releases as review_releases  # noqa: E402
from codex_harness.application.host_delivery import HostDelivery  # noqa: E402
from codex_harness.application.release_queue import ReleaseQueue  # noqa: E402
from codex_harness.application.releases import Releases  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import host_delivery as domain  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402
from codex_harness.domain.policy import POLICY  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)
NAMES = ("PLAN_SCHEMA", "REGISTRY_SCHEMA", "REGISTERED", "AWAITING_REVIEW", "VERIFYING", "PUBLISHING", "AWAITING_CI",
         "MERGE_INTENDED", "MERGED", "DRAIN_INTENDED", "SWITCHING", "AWAITING_CONSUMPTION", "ACTIVE", "BLOCKED",
         "ROLLING_BACK", "ROLLED_BACK", "CANARY_STARTUP", "CANARY_FLEET", "DeliveryRefused", "LifecycleInterrupted",
         "plan_digest", "descriptor_digest", "receipt_identity", "instance_authority", "REPLACEABLE_INSTANCES",
         "INSTANCE_INTENDED", "validate_plan", "validate_targets", "WITHDRAWN", "migration_lineage_digest",
         "migration_request_id", "new_intent")
API = SimpleNamespace(
    MemoryStore=MemoryStore, HostDelivery=lambda store, org, **ports: HostDelivery(store, org, **ports),
    organization=organization, releases=lambda store: Releases(store, organization()),
    queue=lambda store: ReleaseQueue(store), AmbiguousEffect=application.AmbiguousEffect,
    BUCKET_TARGETS=application.BUCKET_TARGETS, BUCKET_PLANS=application.BUCKET_PLANS,
    BUCKET_INTENTS=application.BUCKET_INTENTS, BUCKET_DESCRIPTORS=application.BUCKET_DESCRIPTORS,
    BUCKET_MIGRATIONS=application.BUCKET_MIGRATIONS,
    ContractError=ContractError, MergeRefused=MergeRefused, POLICY=POLICY,
    now=lambda: CLOCK.now(timezone.utc), advance=CLOCK.advance, digest=digest,
    evaluator_successor_id=review_releases.evaluator_successor_id,
    environment_successor_id=review_releases.environment_successor_id,
    expected_evaluator_pin=review_releases.expected_evaluator_pin,
    **{name: getattr(domain, name) for name in NAMES})

if __name__ == "__main__":
    driver.finish("reference", "delivery.migration", s7_migration.run(API))
