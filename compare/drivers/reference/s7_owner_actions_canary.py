"""Reference driver: `coordination.owner_actions_canary` (M7 `OwnerActions` owner canary: `_canary_binding`,
`_advance_canary`, `_canary_still_bound`, `recover_canary` for both kinds with its `_recovery_*` checks, and the M7
`domain.owner_actions` canary names), over the REAL M7 `HostDelivery` of a lane store where the case needs a lane.

The API is the `coordination.owner_actions_delivery` reference API (the `delivery.registry` API plus `OwnerActions`,
`Continuation`, `validate_manifest`, `repository_identity`, `owner_domain`, `dc`, `UNCHANGED`, `WITHDRAWN`,
`migration_lineage_digest`, `migration_request_id`, `new_intent`, `digest`) plus:
- from `domain.host_delivery`, the owner-command names the real lane chain uses (`s7_owner_commands`: the recovery kinds
  and document schemas, the validators and the shape predicates of the first activation, the consumption retry and re-arm);
- `advance_canary(owner, policy_row, continuation, action)`, `canary_binding_of(owner, plan_action)` and
  `canary_still_bound(owner, plan_action, action)`: lambdas over the M7 private `OwnerActions._advance_canary`,
  `._canary_binding` and `._canary_still_bound` (the seam DESIGN-s7 names; the M7 recovery tests call the first directly).
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
import s7_owner_actions_canary  # noqa: E402

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
         "migration_lineage_digest", "migration_request_id", "new_intent", "FAILED", "WITHDRAW_REASONS",
         "RECOVERY_VERIFICATION_MISSING", "RECOVERY_FIRST_ACTIVATION", "RECOVERY_CONSUMPTION_RETRY",
         "RECOVERY_CONSUMPTION_REARM", "RECOVERY_GENERATION_RESTART", "FIRST_ACTIVATION_SCHEMA",
         "CONSUMPTION_RETRY_SCHEMA", "CONSUMPTION_REARM_SCHEMA", "GENERATION_RESTART_SCHEMA",
         "CONSUMPTION_RETRY_RESTART_FIELD", "CONSUMPTION_REARM_MAX_SECONDS", "GENERATION_RESTART_REASONS",
         "RESTART_REQUESTED", "RESTART_LAUNCHED", "RESTART_STARTED", "validate_first_activation",
         "validate_consumption_retry", "validate_consumption_rearm", "validate_generation_restart", "resumable",
         "first_activation_resumable", "first_activation_unbound", "consumption_retryable",
         "consumption_retry_exhausted", "consumption_rearmable", "consumption_rearm_exhausted",
         "generation_restartable", "resolve_descriptor")
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
    advance_canary=lambda owner, policy_row, continuation, action: owner._advance_canary(policy_row, continuation, action),
    canary_binding_of=lambda owner, plan_action: owner._canary_binding(plan_action),
    canary_still_bound=lambda owner, plan_action, action: owner._canary_still_bound(plan_action, action),
    **{name: getattr(domain, name) for name in NAMES})

if __name__ == "__main__":
    driver.finish("reference", "coordination.owner_actions_canary", s7_owner_actions_canary.run(API))
