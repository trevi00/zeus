"""Target composition for the S7 delivery families (harness only, never shipped).

`HostDelivery` composes the split objects of `delivery.application.host_delivery` (DESIGN-s7 V8) and routes the M7
public surface to their owners, as S6's Continuation composition did. There is no facade in the product's application
layer; production composition is S10. The collaborators are the M7 constructor's. Review's `Releases` and
`ReleaseQueue` are wired as composition will wire them (DESIGN-s7 V3/V4): the queue object serves both the
ReleaseClaims and ReleaseSettlement ports, with intake's ticket_binding, coordination's execution fence and event
journal, research's hook rollback, and the scripted clock/id ports.

M7's `HostDelivery` held ONE value per collaborator, so a case that replaces one (`delivery.github = None`,
`delivery.hosts = {}`, `delivery._emit = racing`) replaces it in every object that holds it; `hosts` and `canaries`
are normalized once, so every object shares the same mapping, as M7's one attribute did.
"""

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import determinism
from codex_harness.coordination.application import execution_fence
from codex_harness.coordination.application.events import EventJournal
from codex_harness.delivery.application.host_delivery import state as delivery_state
from codex_harness.delivery.application.host_delivery.controller import DeliveryController
from codex_harness.delivery.application.host_delivery.migration import DeliveryMigration
from codex_harness.delivery.application.host_delivery.recovery import Recovery
from codex_harness.delivery.application.host_delivery.registry import DeliveryRegistry
from codex_harness.delivery.application.host_delivery.resumption import Resumption
from codex_harness.delivery.application.host_delivery.stages.ci import CiObservation
from codex_harness.delivery.application.host_delivery.stages.consume import Consumption
from codex_harness.delivery.application.host_delivery.stages.drain import Drain
from codex_harness.delivery.application.host_delivery.stages.merge import Merge
from codex_harness.delivery.application.host_delivery.stages.prepare import SwitchPreparation
from codex_harness.delivery.application.host_delivery.stages.publish import Publication
from codex_harness.delivery.application.host_delivery.stages.rollback import Rollback
from codex_harness.delivery.application.host_delivery.stages.switch import Switch
from codex_harness.delivery.application.host_delivery.stages.verify import Verification
from codex_harness.delivery.application.host_delivery.state import DeliveryState
from codex_harness.delivery.application.host_delivery.withdrawal import Withdrawal
from codex_harness.delivery.domain import host_delivery as domain
from codex_harness.delivery.domain.managed_runtime import EnvironmentUnqualified
from codex_harness.host_os.adapters.git_workspace import MergeRefused
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import utcnow
from codex_harness.kernel.policy import POLICY
from codex_harness.research.application.hook_rollback import HookRollback
from codex_harness.review.application.release_queue import ReleaseQueue
from codex_harness.review.application.releases import Releases
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore
from s1_target import PortClock, PortIds

# The M7 tests' START; one timeline for the controller clock and the review ports (see s7_delivery).
CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
PORT, IDPORT = PortClock(CLOCK), PortIds(IDS)

# key -> class, in construction order (each object's collaborators are built before it)
OBJECTS = (("state", DeliveryState), ("registry", DeliveryRegistry), ("verification", Verification),
           ("publication", Publication), ("ci", CiObservation), ("merging", Merge),
           ("preparation", SwitchPreparation), ("draining", Drain), ("switching", Switch), ("rollback", Rollback),
           ("consumption", Consumption), ("controller", DeliveryController), ("withdrawal", Withdrawal),
           ("resumption", Resumption), ("recovery", Recovery), ("migration", DeliveryMigration))
ROUTES = {"register_targets": "registry", "register": "registry", "approval": "registry", "plan": "registry",
          "status": "registry", "tick": "controller", "withdraw": "withdrawal", "resume": "resumption",
          "resume_first_activation": "recovery", "resume_consumption_retry": "recovery",
          "resume_consumption_rearm": "recovery", "resume_generation_restart": "recovery",
          "stage_migration": "migration", "require_controller_code": "migration",
          "register_migration_plan": "migration", "finalize_migration": "migration"}
# The M7 private helpers the common cases use (`_emit` is also replaced by a race case): their DeliveryState names.
PRIVATE = {"_emit": "emit", "_deadline": "deadline"}
# M7 attribute -> the objects' parameter names holding it
SHARED = {"github": ("github",), "hosts": ("hosts",), "canaries": ("canaries",), "verifier": ("verifier",),
          "releases": ("releases",), "queue": ("claims", "settlement"), "observer": ("observer",),
          "enabled": ("enabled",), "clock": ("clock",), "first_activation": ("first_activation",),
          "evaluator_pins": ("evaluator_pins",), "controller_code": ("controller_code",),
          "resume_seconds": ("resume_seconds",), "org": ("org",), "store": ("store",)}


def releases_for(store, org):
    return Releases(store, org, ticket_binding=tickets.ticket_binding, clock=PORT,
                    ticket_superseded=tickets.TicketSuperseded, events=EventJournal(), hooks=HookRollback(),
                    ids=IDPORT)


def queue_for(store):
    return ReleaseQueue(store, ticket_binding=tickets.ticket_binding, fences=execution_fence, clock=PORT, ids=IDPORT)


class HostDelivery:
    def __init__(self, store, org=None, *, github=None, hosts=None, canaries=None, clock=utcnow, observer=None,
                 enabled=False, releases=None, queue=None, resume_seconds=delivery_state.RESUME_SECONDS,
                 verifier=None, evaluator_pins=None, controller_code=None, first_activation=None):
        queue = queue if queue is not None else queue_for(store)
        values = {"store": store, "org": org, "github": github, "hosts": hosts or {}, "canaries": canaries or {},
                  "clock": clock, "observer": observer, "enabled": enabled,
                  "releases": releases if releases is not None else releases_for(store, org),
                  "claims": queue, "settlement": queue, "resume_seconds": resume_seconds, "verifier": verifier,
                  "evaluator_pins": evaluator_pins, "controller_code": controller_code,
                  "first_activation": first_activation, "ticket_binding": tickets.ticket_binding}
        objects = {}
        for key, cls in OBJECTS:
            params = [p for p in inspect.signature(cls.__init__).parameters if p not in ("self", "store")]
            objects[key] = cls(store, **{p: objects[p] if p in objects else values[p] for p in params})
        object.__setattr__(self, "objects", objects)

    def _holders(self, name):
        params = SHARED[name]
        return [(obj, p) for obj in self.objects.values() for p in params if p in vars(obj)]

    def __getattr__(self, name):
        if name in PRIVATE:  # an M7 private helper a case reads, at its split home
            return getattr(self.objects["state"], PRIVATE[name])
        if name in ROUTES:
            return getattr(self.objects[ROUTES[name]], name)
        if name in SHARED:
            obj, param = self._holders(name)[0]
            return getattr(obj, param)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name == "_emit":
            self.objects["state"].emit = value
            return
        holders = self._holders(name) if name in SHARED else []
        if not holders:
            raise AttributeError(name)
        for obj, param in holders:
            setattr(obj, param, value)


NAMES = ("PLAN_SCHEMA", "REGISTRY_SCHEMA", "REGISTERED", "AWAITING_REVIEW", "VERIFYING", "PUBLISHING", "AWAITING_CI",
         "MERGE_INTENDED", "MERGED", "DRAIN_INTENDED", "SWITCHING", "AWAITING_CONSUMPTION", "ACTIVE", "BLOCKED",
         "ROLLING_BACK", "ROLLED_BACK", "CANARY_STARTUP", "CANARY_FLEET", "DeliveryRefused", "LifecycleInterrupted",
         "plan_digest", "descriptor_digest", "receipt_identity", "instance_authority", "REPLACEABLE_INSTANCES",
         "INSTANCE_INTENDED", "validate_plan", "validate_targets", "ACTIVATION_GATE_CODES",
         "RECOVERY_CONSUMPTION_RETRY", "EVENT_SWITCHED", "FAILED", "MAX_STAGE_ATTEMPTS")


def api(**extra) -> SimpleNamespace:
    """The s7 delivery API over the target tree: the reference drivers' names from their target homes."""
    return SimpleNamespace(
        MemoryStore=MemoryStore, HostDelivery=lambda store, org, **ports: HostDelivery(store, org, **ports),
        organization=packaged_organization, releases=lambda store: releases_for(store, packaged_organization()),
        queue=queue_for, AmbiguousEffect=delivery_state.AmbiguousEffect,
        BUCKET_TARGETS=delivery_state.BUCKET_TARGETS, BUCKET_PLANS=delivery_state.BUCKET_PLANS,
        BUCKET_INTENTS=delivery_state.BUCKET_INTENTS, BUCKET_DESCRIPTORS=delivery_state.BUCKET_DESCRIPTORS,
        BUCKET_MIGRATIONS=delivery_state.BUCKET_MIGRATIONS, ContractError=ContractError,
        EnvironmentUnqualified=EnvironmentUnqualified, MergeRefused=MergeRefused, POLICY=POLICY,
        now=lambda: CLOCK.now(timezone.utc), advance=CLOCK.advance,
        **{name: getattr(domain, name) for name in NAMES}, **extra)
