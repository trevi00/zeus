"""Reference driver: `delivery.owner_commands` (M7 `HostDelivery` owner commands: `withdraw`, `resume`,
`resume_first_activation`, `resume_consumption_retry`, `resume_consumption_rearm` and `resume_generation_restart`, each
with its refusal ladder, the cached replay, the conflicting document and one successful path driven on to its next stage).

The API holds plain M7 objects or lambdas over them (the `s7_registry` reference API plus the names the cases need):
- `MemoryStore` (`adapters.store`); `HostDelivery(store, org, **ports)` (`application.host_delivery`);
  `organization()` (`bootstrap`); `releases(store)` = `Releases(store, organization())` and `queue(store)` =
  `ReleaseQueue(store)`;
- the M7 `application.host_delivery` bucket names (`BUCKET_TARGETS`, `BUCKET_PLANS`, `BUCKET_INTENTS`,
  `BUCKET_DESCRIPTORS`, `BUCKET_MIGRATIONS`), `AmbiguousEffect`;
- the M7 `domain.host_delivery` names the cases use: `PLAN_SCHEMA`, `REGISTRY_SCHEMA`, the stage constants (`REGISTERED`,
  `AWAITING_REVIEW`, `VERIFYING`, `PUBLISHING`, `AWAITING_CI`, `MERGE_INTENDED`, `MERGED`, `DRAIN_INTENDED`, `SWITCHING`,
  `AWAITING_CONSUMPTION`, `ACTIVE`, `BLOCKED`, `ROLLING_BACK`, `ROLLED_BACK`), `CANARY_STARTUP`, `CANARY_FLEET`,
  `DeliveryRefused`, `LifecycleInterrupted`, `plan_digest`, `descriptor_digest`, `receipt_identity`, `instance_authority`,
  `REPLACEABLE_INSTANCES`, `INSTANCE_INTENDED`, `validate_plan`, `validate_targets`, and, for the owner commands,
  `WITHDRAWN`, `FAILED`, `UNCHANGED`, `new_intent`, `WITHDRAW_REASONS`, the recovery kinds and document schemas
  (`RECOVERY_VERIFICATION_MISSING`, `RECOVERY_FIRST_ACTIVATION`, `RECOVERY_CONSUMPTION_RETRY`,
  `RECOVERY_CONSUMPTION_REARM`, `RECOVERY_GENERATION_RESTART`, `FIRST_ACTIVATION_SCHEMA`, `CONSUMPTION_RETRY_SCHEMA`,
  `CONSUMPTION_REARM_SCHEMA`, `GENERATION_RESTART_SCHEMA`, `CONSUMPTION_RETRY_RESTART_FIELD`,
  `CONSUMPTION_REARM_MAX_SECONDS`, `GENERATION_RESTART_REASONS`, `RESTART_REQUESTED`, `RESTART_LAUNCHED`, `RESTART_STARTED`),
  the document validators (`validate_first_activation`, `validate_consumption_retry`, `validate_consumption_rearm`,
  `validate_generation_restart`), the shape predicates (`resumable`, `first_activation_resumable`,
  `first_activation_unbound`, `consumption_retryable`, `consumption_retry_exhausted`, `consumption_rearmable`,
  `consumption_rearm_exhausted`, `generation_restartable`) and `resolve_descriptor`;
- `ContractError` and `digest` (`domain.model`), `MergeRefused` (`adapters.git`, the exception type only), `POLICY`
  (`domain.policy`);
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
import s7_owner_commands  # noqa: E402

from codex_harness.adapters.git import MergeRefused  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import host_delivery as application  # noqa: E402
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
         "INSTANCE_INTENDED", "validate_plan", "validate_targets", "WITHDRAWN", "FAILED", "UNCHANGED", "new_intent",
         "WITHDRAW_REASONS", "RECOVERY_VERIFICATION_MISSING", "RECOVERY_FIRST_ACTIVATION",
         "RECOVERY_CONSUMPTION_RETRY", "RECOVERY_CONSUMPTION_REARM", "RECOVERY_GENERATION_RESTART",
         "FIRST_ACTIVATION_SCHEMA", "CONSUMPTION_RETRY_SCHEMA", "CONSUMPTION_REARM_SCHEMA",
         "GENERATION_RESTART_SCHEMA", "CONSUMPTION_RETRY_RESTART_FIELD", "CONSUMPTION_REARM_MAX_SECONDS",
         "GENERATION_RESTART_REASONS", "RESTART_REQUESTED", "RESTART_LAUNCHED", "RESTART_STARTED",
         "validate_first_activation", "validate_consumption_retry", "validate_consumption_rearm",
         "validate_generation_restart", "resumable", "first_activation_resumable", "first_activation_unbound",
         "consumption_retryable", "consumption_retry_exhausted", "consumption_rearmable",
         "consumption_rearm_exhausted", "generation_restartable", "resolve_descriptor")
API = SimpleNamespace(
    MemoryStore=MemoryStore, HostDelivery=lambda store, org, **ports: HostDelivery(store, org, **ports),
    organization=organization, releases=lambda store: Releases(store, organization()),
    queue=lambda store: ReleaseQueue(store), AmbiguousEffect=application.AmbiguousEffect,
    BUCKET_TARGETS=application.BUCKET_TARGETS, BUCKET_PLANS=application.BUCKET_PLANS,
    BUCKET_INTENTS=application.BUCKET_INTENTS, BUCKET_DESCRIPTORS=application.BUCKET_DESCRIPTORS,
    BUCKET_MIGRATIONS=application.BUCKET_MIGRATIONS,
    ContractError=ContractError, digest=digest, MergeRefused=MergeRefused, POLICY=POLICY,
    now=lambda: CLOCK.now(timezone.utc), advance=CLOCK.advance,
    **{name: getattr(domain, name) for name in NAMES})

if __name__ == "__main__":
    driver.finish("reference", "delivery.owner_commands", s7_owner_commands.run(API))
