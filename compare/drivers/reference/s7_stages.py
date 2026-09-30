"""Reference driver: `delivery.stages` (every stage handler of one M7 `HostDelivery.tick`: `_verify`, `_publish`, `_observe_ci`,
`_merge`, `_prepare_switch`, `_drain`, `_switch`, `_consume`, `_begin_rollback`/`_rollback`, the `_settle` mapping onto
review's `ReleaseQueue` and the four `AmbiguousEffect` raise sites).

The API holds plain M7 objects or lambdas over them:
- `MemoryStore` (`adapters.store`); `HostDelivery(store, org, **ports)` (`application.host_delivery`);
  `organization()` (`bootstrap`); `releases(store)` = `Releases(store, organization())` and `queue(store)` =
  `ReleaseQueue(store)`;
- the M7 `application.host_delivery` bucket names (`BUCKET_TARGETS`, `BUCKET_PLANS`, `BUCKET_INTENTS`,
  `BUCKET_DESCRIPTORS`, `BUCKET_MIGRATIONS`), `AmbiguousEffect`;
- the M7 `domain.host_delivery` names the cases use: `PLAN_SCHEMA`, `REGISTRY_SCHEMA`, the stage constants (`REGISTERED`,
  `AWAITING_REVIEW`, `VERIFYING`, `PUBLISHING`, `AWAITING_CI`, `MERGE_INTENDED`, `MERGED`, `DRAIN_INTENDED`, `SWITCHING`,
  `AWAITING_CONSUMPTION`, `ACTIVE`, `BLOCKED`, `ROLLING_BACK`, `ROLLED_BACK`), `CANARY_STARTUP`, `CANARY_FLEET`,
  `DeliveryRefused`, `LifecycleInterrupted`, `plan_digest`, `descriptor_digest`, `receipt_identity`, `instance_authority`,
  `REPLACEABLE_INSTANCES`, `INSTANCE_INTENDED`, `validate_plan`, `validate_targets`, and, for `delivery.stages`,
  `ACTIVATION_GATE_CODES`, `RECOVERY_CONSUMPTION_RETRY`, `EVENT_SWITCHED`, `FAILED`, `MAX_STAGE_ATTEMPTS`;
- `ContractError` (`domain.model`), `EnvironmentUnqualified` (`domain.managed_runtime`), `MergeRefused` (`adapters.git`, the exception type only), `POLICY` (`domain.policy`);
- `now` and `advance`: the ONE fake clock (`determinism.FakeClock`, starting at the M7 tests' START, 2026-09-22), whose time
  `Releases`/`ReleaseQueue` read through the installed `datetime` and the controller reads through `now()`.
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
import s7_stages  # noqa: E402

from codex_harness.adapters.git import MergeRefused  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import host_delivery as application  # noqa: E402
from codex_harness.application.host_delivery import HostDelivery  # noqa: E402
from codex_harness.application.release_queue import ReleaseQueue  # noqa: E402
from codex_harness.application.releases import Releases  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import host_delivery as domain  # noqa: E402
from codex_harness.domain.managed_runtime import EnvironmentUnqualified  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402
from codex_harness.domain.policy import POLICY  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)
NAMES = ("PLAN_SCHEMA", "REGISTRY_SCHEMA", "REGISTERED", "AWAITING_REVIEW", "VERIFYING", "PUBLISHING", "AWAITING_CI",
         "MERGE_INTENDED", "MERGED", "DRAIN_INTENDED", "SWITCHING", "AWAITING_CONSUMPTION", "ACTIVE", "BLOCKED",
         "ROLLING_BACK", "ROLLED_BACK", "CANARY_STARTUP", "CANARY_FLEET", "DeliveryRefused", "LifecycleInterrupted",
         "plan_digest", "descriptor_digest", "receipt_identity", "instance_authority", "REPLACEABLE_INSTANCES",
         "INSTANCE_INTENDED", "validate_plan", "validate_targets", "ACTIVATION_GATE_CODES",
         "RECOVERY_CONSUMPTION_RETRY", "EVENT_SWITCHED", "FAILED", "MAX_STAGE_ATTEMPTS")
API = SimpleNamespace(
    MemoryStore=MemoryStore, HostDelivery=lambda store, org, **ports: HostDelivery(store, org, **ports),
    organization=organization, releases=lambda store: Releases(store, organization()),
    queue=lambda store: ReleaseQueue(store), AmbiguousEffect=application.AmbiguousEffect,
    BUCKET_TARGETS=application.BUCKET_TARGETS, BUCKET_PLANS=application.BUCKET_PLANS,
    BUCKET_INTENTS=application.BUCKET_INTENTS, BUCKET_DESCRIPTORS=application.BUCKET_DESCRIPTORS,
    BUCKET_MIGRATIONS=application.BUCKET_MIGRATIONS,
    ContractError=ContractError, EnvironmentUnqualified=EnvironmentUnqualified, MergeRefused=MergeRefused, POLICY=POLICY,
    now=lambda: CLOCK.now(timezone.utc), advance=CLOCK.advance,
    **{name: getattr(domain, name) for name in NAMES})

if __name__ == "__main__":
    driver.finish("reference", "delivery.stages", s7_stages.run(API))
