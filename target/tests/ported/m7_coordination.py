"""M7 `Fleet`, `FleetRunner` and `Workflow` surface over the S5 target, for the ported M7 coordination suites.

Layer: harness (never shipped). A TEST shim: it lets M7 `tests/test_fleet.py` and `tests/test_workflow.py` run, with
their assertions unchanged, against the objects DESIGN-s5 §F/§M built from them. The wiring mirrors
`compare/drivers/target/s5_fleet_composition.py` (Fleet) and `s5_coordination_composition.py` (Workflow); ids and
clocks are NOT scripted here: as in M7 the real clock and uuid4 are used (kernel `utcnow`, SYSTEM_CLOCK/SYSTEM_IDS).

Named adaptations (each is a construction/import adaptation, never a behaviour change):
- `Fleet(store, clock=utcnow, token=lambda: uuid4().hex)` is a facade over `FleetRegistry`, `AdmissionControl`,
  `FleetPause` and `FleetRecovery`. It routes each M7 method to its owning object with the golden composition's
  route table and to nothing else (an unrouted name raises AttributeError, never a fallback). It exposes `.store`
  (so `.store.data` reads as in M7) and the four owners as `.registry`, `.admission`, `.pause_control`,
  `.recovery_control`. Its `pause` and `resume` routes are the `FleetPause` methods of the same names.
- `FleetRunner(fleet, launcher, sleep=time.sleep, interval=5.0, **ports)` builds the target
  `fleet.runner.FleetRunner(fleet.registry, fleet.admission, fleet.pause_control, launcher, ...)`: M7's runner held
  one `Fleet`, the target's holds the three objects it drives.
- `LaunchRefused` is re-exported from `coordination.domain.fleet` (M7 `application.fleet.LaunchRefused`).
- `Workflow(store, organization)` is a facade over the target S4 `Workflow` built with intake's
  `tickets.ticket_binding`/`TicketSuperseded`, research's `require_adoption`, `operation_finalization.park` as the
  terminal park and the system clock/ids. `handle`, `cancel`, `request_rebase` and `context` route to the S5
  `MessageHandler` over it (M7 had them on `Workflow`); everything else routes to the S4 Workflow.
- `Harness(store, org)` stands for what M7's `Harness` gave the outbox, cycle and operation suites: `.store`, `.org`,
  `flush_outbox` (an `OutboxFlusher` with observation's `HealthRecords().record`) and `record_incident` (a unit
  opened around research's `HookLifecycle.record_incident`, or joined when a `transaction` is passed).
- `LocalCycle(service, executor=None, bus=None, workflow=None, observer=None)` subclasses the S5 `LocalCycle` over the
  service's store, organization, flusher and `record_incident`; `Operation(service, executor=None, bus=None,
  workflow=None, budget=None, collector=None, observer=None)` likewise (so M7's `Operation._assignment` resolves), with `EvidenceRecords()` and no design gate.
- `relay` is `outbox_relay.relay` with observation's `HealthRecords().record` and the system clock/ids, and
  `pin_route`, `_prepare` and `_publish` are `outbox_relay`'s (M7 `application.outbox`).
- `ExecutionRecovery(store, org, artifacts)` is the S5 `ExecutionRecovery` with intake's `ticket_binding` injected
  and no audit binding or threshold-review port (both are research's, S8).
- `Continuation(store, fleet=None, lanes=None, conductor=None, validate=None, observer=None, clock=utcnow,
  evidence=None)` is a facade over the split objects of `coordination.application.continuation` (DESIGN-s6 §3), built as
  `compare/drivers/target/s6_continuation_composition.py` builds it: the golden composition's route table, and an
  unrouted name raises AttributeError. M7 exposed seven private methods on the one class, and the suites call or
  override them (`_move`, `_create`, `_note`, `_emit`, `_successor_plan`, `_research_handoff`, `_verify_evidence`);
  the facade routes each to the method of its owner (`intents.move|create|note|emit`,
  `successors.successor_plan|research_handoff`, `research.verify_evidence`). A subclass override of one of them, and
  an assignment to `_verify_evidence`, is installed on that owner object, which is what M7's `self._move(...)`
  reached: the sibling objects call the owner, never the facade. `super()._move(...)` reaches the owner's own method.
  The restart table's `Continuation._resume_<action>` methods are the tick object's, exposed as class attributes.
  `LaneEvidence` is `coordination.application.continuation.lanes.LaneEvidence` (the M7 constructor).
- `Fleet`'s routed methods are class attributes (each delegates to its owner at call time), so a subclass can
  override one and call `super().enqueue(...)` as M7 tests do; an unrouted name still raises AttributeError.
- `ResearchEvidence(root, max_bytes)` is the body of M7 `adapters.continuation.ResearchEvidence`, verbatim, over the
  target `FileArtifacts` and the domain's `ContinuationRefused`; its target owner (`coordination.adapters.continuation`,
  the production wiring) is not implemented yet, so the suites' one evidence reader lives here as a labelled copy.
- `OwnerActions(store, **ports)` is a facade over the split objects of `coordination.application.owner_actions`
  (DESIGN-s6 §4), built as `s6_owner_actions_composition.py` builds it, with the SYSTEM clock and ids the M7 class used
  (the composition's scripted G1 ports are the golden's; a suite must never see them).
- The `continuation_process` names of the guardian suite are `coordination.adapters.guarded_launch` (`observe`,
  `launch_directory`), the composition's process-tree bindings `composition.guarded_launch` (`guard`, `main`,
  `spawn_guardian` = `guarded_spawn()`), and `ConductorProcesses` = `coordination.adapters.conductor_launch` with `spawn`
  defaulting to `spawn_guardian` (M7's default spawn). The lane environment is the caller's `environment=`, as in M7.
- `OwnerActions` also routes M7's private `_advance_canary`, `_plan_binding`, `_discover`, `_recovery_lane` and `_take_slot` (read, and assignment
  on the owner that calls it) and the one `clock` (read from the scheduler; an assignment replaces it in every split
  object that holds one) to their split homes (the
  canary family's `advance` and `_recovery_lane`, the migration family's `delivery_plan.plan_binding`, the scheduler's `_discover`, the requalify family's `_take_slot`), as the
  `coordination.owner_actions_canary`/`_migration` target drivers' accessors do. The delivery routes (the S7 suites'
  `deliveries=HostDelivery(...)`) are `m7_delivery.HostDelivery`, passed as the `deliveries` port.
- `unavailable(slice_, name)` stands for a name whose owner is in a later slice (a Portfolio, a research program, a CLI):
  it imports as a placeholder class (subclassable at import) that raises on any use, and only skipped tests name it.
- `organization()` is `routing.adapters.organization_source.packaged_organization` (M7 `bootstrap.organization`) and
  `packaged_policy` is `routing.adapters.provider_policy.packaged_policy` (M7 `adapters.providers.packaged_policy`).

Batch P10 (earlier coordination) adds, each a construction/import adaptation:
- `schedule_research(service, now=None)` is `research.application.scheduling.schedule_research` with the `Outbox` and the
  bound `reconcile_audits` of `m7_delivery.Releases` wired, exactly as `m7_research.schedule_audits` wires them (as
  `s8_scheduling.py` does); `Releases` is imported at call time because `m7_delivery` imports this shim.
- `flush_outbox(service, bus, observer=None, correlation_id=None)` is `coordination.application.local_cycle.flush_outbox`
  over the service's `flusher` (M7's function took the service and called its `flush_outbox`; the target takes the
  flusher).
- `ResearchLaunches(root, repository, *, spawn=spawn_guardian, run=subprocess.run, **kwargs)` is
  `coordination.adapters.owner_launches.ResearchLaunches` with M7's two defaults (the target requires `spawn` at `start`
  and `run` at `probe`, the seams M7 defaulted to `spawn_guardian` and `subprocess.run`); `DEFAULT_ARGV` is the guarded
  launch's (M7 `adapters.owner_actions.DEFAULT_ARGV`).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from uuid import uuid4

from codex_harness.composition import guarded_launch as _guarded_composition
from codex_harness.coordination.adapters import conductor_launch as _conductor_launch
from codex_harness.coordination.adapters import guarded_launch as _guarded_launch
from codex_harness.coordination.adapters import owner_launches as _owner_launches
from codex_harness.coordination.application import execution_recovery as _execution_recovery
from codex_harness.coordination.application import local_cycle as _local_cycle
from codex_harness.coordination.application import operation_finalization, outbox_relay
from codex_harness.coordination.application.continuation.frames import PolicyFrames
from codex_harness.coordination.application.continuation.grants import CapacityGrants
from codex_harness.coordination.application.continuation.intents import IntentStore
from codex_harness.coordination.application.continuation.lanes import LaneEvidence
from codex_harness.coordination.application.continuation.ownership import OwnershipReconciliation
from codex_harness.coordination.application.continuation.requalification import Requalification
from codex_harness.coordination.application.continuation.research import ResearchAcceptance
from codex_harness.coordination.application.continuation.settlement import LaunchSettlement
from codex_harness.coordination.application.continuation.successors import Successors
from codex_harness.coordination.application.continuation.tick import ContinuationTick
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.fleet.admission import AdmissionControl
from codex_harness.coordination.application.fleet.pause import FleetPause
from codex_harness.coordination.application.fleet.recovery import FleetRecovery
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.application.fleet.runner import FleetRunner as _FleetRunner
from codex_harness.coordination.application.local_cycle import LocalCycle as _LocalCycle
from codex_harness.coordination.application.messages import MessageHandler
from codex_harness.coordination.application.operation import Operation as _Operation
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.outbox_relay import OutboxFlusher, _prepare, _publish, pin_route
from codex_harness.coordination.application.owner_actions.actions import ActionStore
from codex_harness.coordination.application.owner_actions.canary import CanaryFamily
from codex_harness.coordination.application.owner_actions.delivery_plan import DeliveryRegistrationFamily
from codex_harness.coordination.application.owner_actions.migration import MigrationRequestFamily
from codex_harness.coordination.application.owner_actions.requalify import RequalifyFamily
from codex_harness.coordination.application.owner_actions.research_acceptance import ResearchAcceptanceFamily
from codex_harness.coordination.application.owner_actions.research_dispatch import ResearchLaunchFamily
from codex_harness.coordination.application.owner_actions.scheduler import OwnerActionScheduler
from codex_harness.coordination.application.workflow import Workflow as _Workflow
from codex_harness.coordination.domain.continuation import RESEARCH, ROUTE_OWNERS, ContinuationRefused
from codex_harness.coordination.domain.fleet import LaunchRefused
from codex_harness.evidence.application.inspections import EvidenceRecords
from codex_harness.intake.application import tickets
from codex_harness.intake.application.portfolio_lineage import PortfolioLineage
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, utcnow
from codex_harness.observation.application.health import HealthRecords
from codex_harness.research.application import scheduling as _scheduling
from codex_harness.research.application.audit_gate import require_adoption
from codex_harness.research.application.hooks import HookLifecycle
from codex_harness.research.application.program_state import ProgramState
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.routing.adapters.provider_policy import packaged_policy
from codex_harness.storage.adapters.file_artifacts import FileArtifacts

__all__ = ["ConductorProcesses", "Continuation", "DEFAULT_ARGV", "ExecutionRecovery", "Fleet", "FleetRunner", "Harness",
           "LaneEvidence", "LaunchRefused", "LocalCycle", "Operation", "OwnerActions", "ResearchEvidence",
           "ResearchLaunches", "Workflow", "_prepare", "_publish", "flush_outbox", "guard", "launch_directory", "main",
           "observe", "organization", "packaged_policy", "pin_route", "relay", "schedule_research", "spawn_guardian",
           "unavailable"]

ROUTES = {
    "registry": ("register", "registered", "enqueue", "record_delivery", "delivery", "reconciliation_required",
                 "status"),
    "admission": ("admit_one", "reserve_unit", "settle_unit", "units", "held_units", "finalize"),
    "pause": ("pause", "resume", "activation_gate", "release_activation_hold", "authorize_budget", "budget_grants"),
    "recovery": ("reconcile_interrupted", "recovery", "relocate", "migrate_host", "relocations"),
}
OWNER = {method: owner for owner, methods in ROUTES.items() for method in methods}


class Fleet:
    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex):
        self.store = store
        self.registry = FleetRegistry(store, clock=clock, token=token)
        self.admission = AdmissionControl(store, clock=clock, token=token)
        self.pause_control = FleetPause(store, clock=clock, token=token)
        self.recovery_control = FleetRecovery(store, clock=clock, token=token)

    def __getattr__(self, name):  # an unrouted name is never a fallback (every routed one is a class attribute)
        raise AttributeError(name)


def _routed(name):
    owner = {"registry": "registry", "admission": "admission", "pause": "pause_control",
             "recovery": "recovery_control"}[OWNER[name]]

    def method(self, *args, **kwargs):
        return getattr(getattr(self, owner), name)(*args, **kwargs)
    method.__name__ = name
    return method


for _name in OWNER:
    setattr(Fleet, _name, _routed(_name))


def FleetRunner(fleet, launcher, sleep=time.sleep, interval=5.0, **ports):  # noqa: N802 - the M7 constructor name
    return _FleetRunner(fleet.registry, fleet.admission, fleet.pause_control, launcher, sleep=sleep,
                        interval=interval, **ports)


class Workflow:
    """Task ownership from the S4 Workflow, messages from the MessageHandler over it."""

    MESSAGE_METHODS = ("handle", "cancel", "request_rebase", "context")

    def __init__(self, store, organization):
        self.workflow = _Workflow(store, organization, ticket_binding=tickets.ticket_binding,
                                  TicketSuperseded=tickets.TicketSuperseded, adoption=require_adoption,
                                  park_terminal=operation_finalization.park, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
        self.messages = MessageHandler(self.workflow)

    def __getattr__(self, name):
        return getattr(self.messages if name in self.MESSAGE_METHODS else self.workflow, name)


def organization():
    return packaged_organization()


class Harness:
    """The carrier of `.store` and `.org` with the outbox flush and incident use case M7's `Harness` had."""

    def __init__(self, store, org):
        self.store, self.org = store, org
        self.flusher = OutboxFlusher(store, org, health=HealthRecords().record, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
        self.hooks = HookLifecycle(org, outbox=Outbox(), events=EventJournal(), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)

    def flush_outbox(self, bus, limit=100, audit=None, correlation_id=None):
        return self.flusher.flush(bus, limit, audit, correlation_id)

    def record_incident(self, message, independent_occurrence=None, transaction=None):
        if transaction is not None:
            return self.hooks.record_incident(message, independent_occurrence=independent_occurrence,
                                              transaction=transaction)
        with self.store.transaction() as tx:  # M7 Harness.record_incident opened this unit itself
            return self.hooks.record_incident(message, independent_occurrence=independent_occurrence,
                                              transaction=tx)


def relay(store, org, bus, limit=100, audit=None, correlation_id=None):
    return outbox_relay.relay(store, org, bus, limit, audit, correlation_id, health=HealthRecords().record,
                              clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


class LocalCycle(_LocalCycle):
    def __init__(self, service, executor=None, bus=None, workflow=None, observer=None):
        super().__init__(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                         executor=executor, bus=bus, workflow=workflow, observer=observer, clock=SYSTEM_CLOCK)


class Operation(_Operation):
    def __init__(self, service, executor=None, bus=None, workflow=None, budget=None, collector=None, observer=None):
        super().__init__(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                         executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector,
                         observer=observer, evidence_records=EvidenceRecords(), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


def ExecutionRecovery(store, org, artifacts):  # noqa: N802 - the M7 constructor name
    return _execution_recovery.ExecutionRecovery(store, org, artifacts, ticket_binding=tickets.ticket_binding,
                                                 clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


# ---- S6: continuation, research evidence, owner actions, the guarded child launch ------------------------------
CONTINUATION_ROUTES = {"register": "frames", "policy": "frames", "status": "frames", "unresolved": "frames",
                       "accept_research": "research", "supplement_research_scope": "research",
                       "research_facts": "research", "tick": "tick", "drain": "settlement",
                       "reconcile_ownership": "ownership", "grant_capacity": "grants",
                       "requalify_delivery": "requalification"}
PRIVATE_ROUTES = {"_move": ("intents", "move"), "_create": ("intents", "create"), "_note": ("intents", "note"),
                  "_emit": ("intents", "emit"), "_successor_plan": ("successors", "successor_plan"),
                  "_research_handoff": ("successors", "research_handoff"),
                  "_verify_evidence": ("research", "verify_evidence")}


def _private(name):
    def method(self, *args, **kwargs):  # the owner's own method: what `super()._move(...)` reaches
        return self.originals[name](*args, **kwargs)
    method.__name__ = name
    return method


class Continuation:
    def __init__(self, store, fleet=None, lanes=None, conductor=None, validate=None, observer=None, clock=utcnow,
                 evidence=None):
        self.store = store
        intents = IntentStore(store, clock=clock, observer=observer)
        successors = Successors(store, clock=clock, validate=validate, portfolio=PortfolioLineage())
        research = ResearchAcceptance(store, clock=clock, evidence=evidence, lanes=lanes)
        grants = CapacityGrants(store, clock=clock, lanes=lanes, intents=intents, research=research,
                                successors=successors)
        requalification = Requalification(store, clock=clock, lanes=lanes, validate=validate, intents=intents,
                                          research=research)
        frames = PolicyFrames(store, clock=clock, grants=grants, intents=intents, requalification=requalification)
        settlement = LaunchSettlement(store, conductor=conductor, fleet=fleet, lanes=lanes, frames=frames,
                                      intents=intents)
        tick = ContinuationTick(store, conductor=conductor, fleet=fleet, lanes=lanes, frames=frames, intents=intents,
                                research=research, settlement=settlement, successors=successors)
        self.objects = {"intents": intents, "frames": frames, "research": research, "successors": successors,
                        "grants": grants, "requalification": requalification, "settlement": settlement,
                        "tick": tick, "ownership": OwnershipReconciliation(store, successors=successors)}
        self.originals = {name: getattr(self.objects[owner], target) for name, (owner, target) in
                          PRIVATE_ROUTES.items()}
        for name, (owner, target) in PRIVATE_ROUTES.items():
            override = getattr(type(self), name)
            if override is not getattr(Continuation, name):  # a subclass replaced it, as M7's `self._move` was
                setattr(self.objects[owner], target, getattr(self, name))

    def __setattr__(self, name, value):
        if name in PRIVATE_ROUTES and "objects" in self.__dict__:
            owner, target = PRIVATE_ROUTES[name]
            setattr(self.objects[owner], target, value)
        else:
            object.__setattr__(self, name, value)

    def __getattr__(self, name):
        owner = CONTINUATION_ROUTES.get(name)
        if owner is None:
            raise AttributeError(name)
        return getattr(self.objects[owner], name)


for _name in PRIVATE_ROUTES:
    setattr(Continuation, _name, _private(_name))


def _resume(name):
    def method(self, *args, **kwargs):
        return getattr(self.objects["tick"], name)(*args, **kwargs)
    method.__name__ = name
    return method


for _name in vars(ContinuationTick):  # M7's restart table names `Continuation._resume_<action>` (RESUME)
    if _name.startswith("_resume_"):
        setattr(Continuation, _name, _resume(_name))


MAX_RESEARCH_EVIDENCE_BYTES = 1024 * 1024  # the FileArtifacts.text ceiling


class ResearchEvidence:
    """The research evidence port over ONE trusted content-addressed store (`FileArtifacts`): `verify`
    reads at most `max_bytes` of the reference's actual bytes and checks their SHA-256. Refusals are
    fixed codes (`research_evidence_missing|unreadable|oversized|corrupt|invalid`); no path, raw error
    or content leaves. The root is fixed by configuration; it is never created, searched or
    supplied by a caller, and nothing is fetched. Integrity holds at the observed read only."""

    def __init__(self, root, max_bytes: int = MAX_RESEARCH_EVIDENCE_BYTES):
        self.root, self.max_bytes, self.store = Path(root), max_bytes, None

    def verify(self, reference) -> None:
        code = None
        try:
            if self.store is None:
                if not self.root.is_dir():
                    raise FileNotFoundError
                self.store = FileArtifacts(str(self.root))
            self.store.text(reference, self.max_bytes)
        except FileNotFoundError:
            code = "research_evidence_missing"
        except UnicodeDecodeError:
            code = "research_evidence_invalid"  # digest matched, but not the text the store writes
        except OSError:
            code = "research_evidence_unreadable"
        except ContractError as exc:
            code = {"Artifact exceeds text budget": "research_evidence_oversized",
                    "Artifact modified": "research_evidence_corrupt"}.get(str(exc), "research_evidence_invalid")
        if code is not None:
            raise ContinuationRefused(code, ROUTE_OWNERS[RESEARCH], "evidence_refs")


OWNER_ROUTES = {"register": "scheduler", "status": "scheduler", "tick": "scheduler", "recover_canary": "canary",
                "request_migration": "migration", "migration": "migration"}
# M7's private methods the S7 suites call, at their split homes (as the `coordination.owner_actions_*` target drivers'
# accessors do): name -> (the owner object's key, a path of attributes from it, the method).
OWNER_PRIVATE = {"_advance_canary": ("canary", (), "advance"),
                 "_plan_binding": ("migration", ("delivery_plan",), "plan_binding"),
                 "_discover": ("scheduler", (), "_discover"),
                 "_recovery_lane": ("canary", (), "_recovery_lane"),
                 "_take_slot": ("scheduler", ("requalify_family",), "_take_slot")}


class OwnerActions:
    def __init__(self, store, *, continuation=None, org=None, lanes=None, deliveries=None, publisher=None,
                 assessments=None, targets=None, fleet=None, validate=None, first_activation=None, clock=utcnow,
                 withdrawals=None, mainline=None, requalify=None, artifacts=None, research=None, ledger=None):
        actions = ActionStore(store, clock=clock)
        research_acceptance = ResearchAcceptanceFamily(store, assessments=assessments, continuation=continuation,
                                                       lanes=lanes, org=org, message_clock=SYSTEM_CLOCK,
                                                       ids=SYSTEM_IDS, actions=actions)
        delivery_plan = DeliveryRegistrationFamily(store, deliveries=deliveries, first_activation=first_activation,
                                                   publisher=publisher, targets=targets, actions=actions)
        canary = CanaryFamily(store, clock=clock, deliveries=deliveries, fleet=fleet, lanes=lanes, org=org,
                              targets=targets, validate=validate, actions=actions)
        migration = MigrationRequestFamily(store, clock=clock, deliveries=deliveries, publisher=publisher,
                                           targets=targets, delivery_plan=delivery_plan)
        requalify_family = RequalifyFamily(store, artifacts=artifacts, clock=clock, continuation=continuation,
                                           deliveries=deliveries, mainline=mainline, requalify=requalify,
                                           withdrawals=withdrawals, actions=actions)
        research_dispatch = ResearchLaunchFamily(store, clock=clock, ledger=ledger, research=research,
                                                 programs=ProgramState(store, clock=clock), actions=actions)
        scheduler = OwnerActionScheduler(store, clock=clock, continuation=continuation, actions=actions, canary=canary,
                                         delivery_plan=delivery_plan, migration=migration,
                                         requalify_family=requalify_family, research_acceptance=research_acceptance,
                                         research_dispatch=research_dispatch)
        self.objects = {"scheduler": scheduler, "canary": canary, "migration": migration}
        self.holders = [actions, research_acceptance, delivery_plan, canary, migration, requalify_family,
                        research_dispatch, scheduler]

    def _owner_of(self, name):
        key, path, method = OWNER_PRIVATE[name]
        target = self.objects[key]
        for step in path:
            target = getattr(target, step)
        return target, method

    def __setattr__(self, name, value):
        # a case that replaces a private method (`owner._recovery_lane = racing`) replaces it on the owner that calls it
        if name in OWNER_PRIVATE:
            target, method = self._owner_of(name)
            setattr(target, method, value)
        elif name == "clock":
            # M7's one object held ONE clock (`owner.clock = ...`): replace it in every split object that holds one
            for holder in self.holders:
                if "clock" in vars(holder):
                    holder.clock = value
        else:
            super().__setattr__(name, value)

    def __getattr__(self, name):
        if name == "clock":
            return self.objects["scheduler"].clock
        if name in OWNER_PRIVATE:
            target, method = self._owner_of(name)
            return getattr(target, method)
        owner = OWNER_ROUTES.get(name)
        if owner is None:
            raise AttributeError(name)
        return getattr(self.objects[owner], name)


spawn_guardian = _guarded_composition.guarded_spawn()
guard = _guarded_composition.guard_function()
main = _guarded_composition.guardian_command()
observe = _guarded_launch.observe
launch_directory = _guarded_launch.launch_directory


DEFAULT_ARGV = _guarded_launch.DEFAULT_ARGV


def ResearchLaunches(root, repository, *, spawn=spawn_guardian, run=subprocess.run, **kwargs):  # noqa: N802 - M7 name
    return _owner_launches.ResearchLaunches(root, repository, spawn=spawn, run=run, **kwargs)


def ConductorProcesses(config, host, **kwargs):  # noqa: N802 - the M7 constructor name
    kwargs.setdefault("spawn", spawn_guardian)
    return _conductor_launch.ConductorProcesses(config, host, **kwargs)


def flush_outbox(service, bus, observer=None, correlation_id=None):
    return _local_cycle.flush_outbox(service.flusher, bus, observer, correlation_id)


def schedule_research(service, now=None):
    from m7_delivery import Releases  # at call time: m7_delivery imports this shim
    releases = Releases(service.store, service.org)
    return _scheduling.schedule_research(service, now, outbox=Outbox(), reconcile_audits=releases.reconcile_audits)


class _UnavailableMeta(type):
    def __getattr__(cls, attribute):
        raise NotImplementedError("%s: %s is not on the S6 target" % cls.owner)


def unavailable(slice_, name):
    """A class placeholder: it can be subclassed at import, and any use (instantiation, call, attribute) raises."""
    def refuse(self, *args, **kwargs):
        raise NotImplementedError("%s: %s is not on the S6 target" % (slice_, name))
    return _UnavailableMeta(name.rsplit(".", 1)[-1], (), {"__init__": refuse, "owner": (slice_, name)})
