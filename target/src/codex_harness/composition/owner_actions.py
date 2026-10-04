"""The `zeus owner-actions` composition: the policy load, the production coordinator, the tick and run loop and the guarded assessment (INV-OWNER-ACTIONS-001).

Layer: composition
Owns: owner_action_owners (the builder of the S6 split), delivery_port, continuation_port, load_policy, register_policy, assessment_ceilings, assess, coordinator, tick_policy, tick_policies, policy_list, run_loop and the private _resolve_provider
Does not own: the argument shape and the command bodies (entry.cli.owner_actions), the families (coordination.application.owner_actions), the plan publisher (composition.owner_action_adapters), the guarded launches (coordination.adapters.owner_launches) and the target files (delivery.adapters.target_files)
Entry points: owner_action_owners, load_policy, register_policy, assess, coordinator, tick_policy, tick_policies, policy_list, run_loop
Contracts: INV-OWNER-ACTIONS-001, INV-OWNER-ACTIONS-MIGRATION-001, INV-HOST-DELIVERY-FIRST-ACTIVATION-001, INV-RELEASE-EVALUATOR-MIGRATION-001, INV-RELEASE-ENVIRONMENT-REVERIFY-001

Moved from M7 `adapters/owner_actions.py` (SOURCE e38aa722) by named rule R-c32 (S10 unit C8b-3), the documented S10 carry of S6/S7's moves: `load_policy` (:86-93), `register_policy` (:96-99), `_resolve_provider` (:310-313), `assessment_ceilings` (:316-336),
`assess` (:339-367), `coordinator` (:371-432), `tick_policy` (:435-448), `tick_policies` (:451-464), `policy_list` (:467-472) and `run_loop` (:475-505). The statements are M7's verbatim except the builder calls, the import homes and the split routing.
`execute` (:540-577) and `refusal` (:580-583) are `entry.cli.owner_actions._execute` and `_refusal`; `add_parser` is already `entry.cli.owner_actions`.

M7's one `OwnerActions(store, **ports)` is the S6 split `coordination.application.owner_actions`. `owner_action_owners` builds it exactly as `tests/ported/m7_coordination.OwnerActions.__init__` does (the eight objects in construction order, the shared
`ActionStore`, the SYSTEM clock `utcnow` and the SYSTEM clock and ids for the research-acceptance decision envelope; `compare/drivers/target/s6_owner_actions_composition.py` is the harness variant with SCRIPTED ports and is not used here). It returns the
objects as attributes of one namespace, with `store` and `assessments` (the two M7 attributes `tick_policy` and `execute` read); there is no facade. Each M7 method call is routed to the owner that the shim's PUBLIC `OWNER_ROUTES` names:

    M7 OwnerActions member (call site)                        split owner (attribute)   class (coordination.application.owner_actions)
    status (entry `status`)                                    scheduler                 scheduler.OwnerActionScheduler
    register (register_policy)                                 scheduler                 scheduler.OwnerActionScheduler
    tick (tick_policy)                                         scheduler                 scheduler.OwnerActionScheduler
    request_migration (entry `migrate`)                        migration                 migration.MigrationRequestFamily
    recover_canary (entry `canary-recover`)                    canary                    canary.CanaryFamily
    store (tick_policy)                                        the store handed to the builder
    assessments (entry `tick`: `join`)                         the assessments port handed to the builder (coordination.adapters.owner_launches.Assessments)

No call site needs the shim's PRIVATE routing (`OWNER_PRIVATE`: `_advance_canary`, `_plan_binding`, `_discover`, `_recovery_lane`, `_take_slot`). The families call a delivery through the `deliveries(lane)` port and `withdrawals(lane)`: M7's one
`HostDelivery(store, org, **ports)` is `delivery_port`, the namespace of `composition.cli_host_delivery.host_delivery_owners` (the S7 split) with the PUBLIC names the families call routed to the owners the S7 shim's `ROUTES` names:

    HostDelivery member (the families' call)        split owner (attribute)   class (delivery.application.host_delivery)
    register                                        registry                  registry.DeliveryRegistry
    register_migration_plan, stage_migration,
        finalize_migration, require_controller_code migration                 migration.DeliveryMigration
    withdraw (withdrawals(lane))                    withdrawal                withdrawal.Withdrawal
    store                                           the lane store handed to the builder

The families call M7's one `Continuation` through `continuation_port`: the `composition.continuation.continuation_owners` split with the three public names they call routed by `CONTINUATION_ROUTES`:

    Continuation member (the families' call)        split owner (attribute)   class (coordination.application.continuation)
    policy                                          frames                    frames.PolicyFrames
    research_facts, accept_research                 research                  research.ResearchAcceptance

Other homes: `Fleet(store).registered()` is `coordination.application.fleet.registry.FleetRegistry` (S5), and the `fleet` port (`enqueue`) is `composition.continuation.fleet_port`; `GitSource` is `host_os.adapters.git_source`; `GitHubDelivery` is `delivery.adapters.host_delivery` (run through the `process_groups.run_process` runner, as
`composition.cli_host_delivery.controller_ports` builds it); `lane_git` is `composition.cli_host_delivery.lane_git` (C8b-4); `lane_stores`, `validator`, `research_evidence`, `LaneMainline`, `requalify_delivery` and the Continuation owners are
`composition.continuation` (C8b-1); `_parse` is `composition.fleet_backlog._parse` (C8b-2) over `intake.adapters.backlog_blobs.read_blob`; M7 `continuation_process.spawn_guardian` is `composition.guarded_launch.guarded_spawn()`; M7 `TargetFiles` is
`delivery.adapters.target_files`; `Assessments` and `ResearchLaunches` are `coordination.adapters.owner_launches` (with the guarded spawn, and for the research probe `resolve=_resolve_provider` and `run=process_groups.run`, M7's `subprocess.run` at the
chokepoint); `GitPlanPublisher` is `composition.owner_action_adapters.git_plan_publisher`; M7 `deployment.resolve_evaluator_pin` and `controller_code_revision` are `delivery.adapters.deployment`; `first_activation_facts` is
`delivery.adapters.host_delivery` (with the `run`, `source` and `profiles` seams `controller_ports` binds); `CallBudget` is `execution.adapters.call_budget`; `FileArtifacts` is `storage.adapters.file_artifacts`; `build_executor` is
`composition.operation`, `build_observer` is `composition.observation`, `runtime_dir` is `composition.configuration`; `resolve_codex` is `execution.adapters.providers.codex_app_server`; M7 `usage_policy.validate_budget` is `kernel.usage`.
An absent `ZEUS_COMPOSITION_PROFILE` refuses in `build_executor` (`composition_profile_unknown`, OWNER-DECISIONS-S10 #10), which `assess` reaches. Imports sit inside the functions, so importing this module stays light.
"""
from __future__ import annotations

import hashlib
import shutil
import signal
import time
from types import SimpleNamespace

from codex_harness.coordination.domain.fleet import lane_of
from codex_harness.coordination.domain.owner_actions import (
    ASSESSOR,
    TICK_SCHEMA,
    OwnerActionRefused,
    validate_policy,
)
from codex_harness.host_os.adapters.git_source import GitSource
from codex_harness.intake.domain.backlog import BacklogRefused
from codex_harness.kernel.errors import ContractError

MAX_POLICY_BYTES = 64 * 1024


def owner_action_owners(store, *, continuation=None, org=None, lanes=None, deliveries=None, publisher=None,
                        assessments=None, targets=None, fleet=None, validate=None, first_activation=None, clock=None,
                        withdrawals=None, mainline=None, requalify=None, artifacts=None, research=None,
                        ledger=None, observer=None) -> SimpleNamespace:
    """The S6 split of M7's `OwnerActions(store, **ports)`: the objects by key, as the module docstring tables."""
    from codex_harness.coordination.application.owner_actions.actions import ActionStore
    from codex_harness.coordination.application.owner_actions.canary import CanaryFamily
    from codex_harness.coordination.application.owner_actions.delivery_plan import (
        DeliveryRegistrationFamily,
    )
    from codex_harness.coordination.application.owner_actions.migration import (
        MigrationRequestFamily,
    )
    from codex_harness.coordination.application.owner_actions.requalify import RequalifyFamily
    from codex_harness.coordination.application.owner_actions.research_acceptance import (
        ResearchAcceptanceFamily,
    )
    from codex_harness.coordination.application.owner_actions.research_dispatch import (
        ResearchLaunchFamily,
    )
    from codex_harness.coordination.application.owner_actions.scheduler import OwnerActionScheduler
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, utcnow
    from codex_harness.research.application.program_state import ProgramState

    clock = utcnow if clock is None else clock
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
                                     research_dispatch=research_dispatch, observer=observer)
    return SimpleNamespace(store=store, assessments=assessments, actions=actions,
                           research_acceptance=research_acceptance, delivery_plan=delivery_plan, canary=canary,
                           migration=migration, requalify_family=requalify_family,
                           research_dispatch=research_dispatch, scheduler=scheduler)


def delivery_port(store, org=None, **ports) -> SimpleNamespace:
    """M7 `HostDelivery(store, org, **ports)` as the owner-action families call it: the S7 split of
    `composition.cli_host_delivery.host_delivery_owners` with the public names routed to their owners."""
    from codex_harness.composition.cli_host_delivery import host_delivery_owners

    owners = host_delivery_owners(store, org, **ports)
    return SimpleNamespace(**vars(owners), store=store, register=owners.registry.register,
                           register_migration_plan=owners.migration.register_migration_plan,
                           stage_migration=owners.migration.stage_migration,
                           finalize_migration=owners.migration.finalize_migration,
                           require_controller_code=owners.migration.require_controller_code,
                           withdraw=owners.withdrawal.withdraw)


def continuation_port(store, fleet=None, lanes=None, validate=None, evidence=None) -> SimpleNamespace:
    """M7 `Continuation(store, Fleet(store), lanes, None, validate=, evidence=)` as the owner-action families call it."""
    from codex_harness.composition.continuation import continuation_owners

    owners = continuation_owners(store, fleet, lanes, None, validate=validate, evidence=evidence)
    return SimpleNamespace(**vars(owners), policy=owners.frames.policy, research_facts=owners.research.research_facts,
                           accept_research=owners.research.accept_research)


# ----- the owner's policy ----------------------------------------------------------------------------
def load_policy(source, revision: str, path: str) -> dict:
    from codex_harness.composition.fleet_backlog import _parse
    from codex_harness.intake.adapters.backlog_blobs import read_blob

    try:
        data = read_blob(source, revision, path, MAX_POLICY_BYTES, "policy")
        document = _parse(data, "policy_not_json")
    except BacklogRefused as exc:
        raise OwnerActionRefused(exc.reason_code, "policy") from exc
    return {"policy": validate_policy(document),
            "pin": {"revision": revision, "path": path, "sha256": hashlib.sha256(data).hexdigest()}}


def register_policy(store, config: dict, lane_id: str, revision: str, path: str, source_factory=GitSource) -> dict:
    lane = lane_of(config, lane_id)
    loaded = load_policy(source_factory(lane["repository"]), revision, path)
    return owner_action_owners(store).scheduler.register(loaded["policy"], {**loaded["pin"], "lane": lane_id})


# ----- the independent assessor ------------------------------------------------------------------------
def _resolve_provider() -> dict:
    from codex_harness.execution.adapters.providers.codex_app_server import resolve_codex

    return {"codex": resolve_codex(), "node": shutil.which("node")}


def assessment_ceilings(store) -> dict:
    """The accounting the independent assessment is budgeted under: the Fleet's CURRENT effective budget
    (`Fleet.registered`, the registered config with any owner grant, including its accounting `mode`),
    i.e. the same authority every Fleet worker and continuation start is admitted against. Finite keeps
    that finite ceiling; subscription counts every reservation and settlement without a lifetime ceiling
    and still needs a readable ledger (`CallBudget.reserve`). No Fleet registry or an unreadable one is a
    named refusal BEFORE any executor, reservation or provider entry - never a guessed default."""
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.domain.fleet import FleetRefused
    from codex_harness.kernel.usage import UsagePolicyError, validate_budget

    try:
        budget = FleetRegistry(store).registered()["config"]["budget"]
    except FleetRefused as exc:
        raise OwnerActionRefused("assessment_budget_unregistered", "budget") from exc
    except Exception as exc:
        raise OwnerActionRefused("assessment_budget_unreadable", "budget") from exc
    try:
        return validate_budget(budget)
    except UsagePolicyError as exc:
        raise OwnerActionRefused("assessment_budget_invalid", "budget") from exc


def assess(service, decision_id: str, correlation_id: str, model_label: str, *, executor=None, budget=None,
           ceilings=None) -> dict:
    """The guardian's child: the existing guarded `decide_one` of the independent assessor for EXACTLY
    this pending owner-assessment row, under the machine call ledger and the Fleet's effective accounting
    (`assessment_ceilings`). ONE decision call per launch; a second dispatcher claims nothing."""
    from codex_harness.coordination.application.operation import BudgetedExecutor

    ceilings = assessment_ceilings(service.store) if ceilings is None else ceilings
    if executor is None:
        from codex_harness.composition.observation import build_observer
        from codex_harness.composition.operation import build_executor
        from codex_harness.execution.adapters.call_budget import CallBudget

        executor = build_executor(service, observer=build_observer(service.store, "cli.owner-actions"),
                                  knowledge=False)
        budget = CallBudget()
    expected = {"id": decision_id, "correlation_id": correlation_id, "statuses": {"pending", "retry"}}
    wrapped = BudgetedExecutor(executor, budget, ceilings, "owner-assessment:" + decision_id, model_label)
    result = wrapped.decide_one(ASSESSOR, expected=expected)
    with service.store.transaction() as tx:
        decision = tx.get("decisions_pending", decision_id) or {}
    accepted = (decision.get("result") or {}).get("accepted")
    calls = {"reserved": len(wrapped.slots), "settled": sum(s["settled"] for s in wrapped.slots),
             "accounting_mode": wrapped.mode}
    # The exit code is the launch's bound execution outcome the coordinator promotes on (R1): THIS
    # launch owned the claim, the decision succeeded and every call reservation it took is settled.
    resolved = result is not None and decision.get("status") == "succeeded" and calls["reserved"] == calls["settled"]
    return {"decision_id": decision_id, "claimed": result is not None, "status": decision.get("status"),
            "accepted": accepted if isinstance(accepted, bool) else None, "calls": calls,
            "exit_code": 0 if resolved else 1}


# ----- the coordinator with its real ports -------------------------------------------------------------
def coordinator(service, config: dict, host: dict, *, lanes=None, assessments=None, publisher_factory=None,
                continuation=None, research=None):
    from codex_harness.composition.cli_host_delivery import lane_git
    from codex_harness.composition.configuration import runtime_dir
    from codex_harness.composition.continuation import (
        LaneMainline,
        fleet_port,
        lane_stores,
        requalify_delivery,
        research_evidence,
        validator,
    )
    from codex_harness.composition.guarded_launch import guarded_spawn
    from codex_harness.composition.owner_action_adapters import git_plan_publisher
    from codex_harness.coordination.adapters.owner_launches import Assessments, ResearchLaunches
    from codex_harness.delivery.adapters.host_delivery import GitHubDelivery
    from codex_harness.delivery.adapters.target_files import TargetFiles
    from codex_harness.execution.adapters.call_budget import CallBudget
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts

    lanes = lanes or lane_stores(config, host)
    store = service.store
    continuation = continuation or continuation_port(store, fleet_port(store), lanes, validate=validator(),
                                                     evidence=research_evidence())
    root = runtime_dir()
    artifacts = FileArtifacts(str(root / "artifacts"))
    spawn = guarded_spawn()
    assessments = assessments or Assessments(artifacts, root / "owner-actions", spawn=spawn)
    research = research or ResearchLaunches(root / "owner-actions" / "research",
                                            lambda lane_id: lane_of(config, lane_id)["repository"], spawn=spawn,
                                            resolve=_resolve_provider, run=process_groups.run)
    publisher_factory = publisher_factory or git_plan_publisher

    def evaluator_pins(lane_id):
        # INV-RELEASE-EVALUATOR-MIGRATION-001: the approved E pin is re-derived from the lane's OWN
        # registered repository before any migration write, never taken from the approval's fields.
        from codex_harness.delivery.adapters.deployment import resolve_evaluator_pin

        return lambda revision, base: resolve_evaluator_pin(lane_git(lane_of(config, lane_id), host), revision, base)

    # INV-RELEASE-ENVIRONMENT-REVERIFY-001: the trusted controller-code port is the runtime_revision
    # SSOT of the running harness code (the same resolver the runner's own-code guard uses).
    from codex_harness.delivery.adapters.deployment import controller_code_revision

    def first_activation(lane_id, revision):
        # INV-HOST-DELIVERY-001 first activation: the concrete image/profile of a target without a
        # descriptor come from the lane boundary's trusted facts, the same ports the lane re-derives.
        # Imported at call time: an unavailable resolver is the coordinator's named wait, not a crash.
        from codex_harness.context.adapters import worker_profile
        from codex_harness.delivery.adapters.host_delivery import first_activation_facts

        lane = lane_of(config, lane_id)
        return first_activation_facts(lane, host, revision, run=process_groups.run_process,
                                      source=GitSource(lane["repository"]), profiles=worker_profile)

    def withdrawals(lane_id):
        # The same lane store and GitHub workspace `host-delivery withdraw --lane` uses: one authority.
        return delivery_port(lanes(lane_id).store, service.org,
                             github=GitHubDelivery(lane_git(lane_of(config, lane_id), host),
                                                   runner=process_groups.run_process))

    return owner_action_owners(
        store, continuation=continuation, org=service.org, lanes=lanes,
        deliveries=lambda lane_id: delivery_port(lanes(lane_id).store, service.org,
                                                 evaluator_pins=evaluator_pins(lane_id),
                                                 controller_code=controller_code_revision),
        publisher=lambda lane_id: publisher_factory(lane_of(config, lane_id)["repository"]),
        assessments=assessments, targets=TargetFiles(), fleet=fleet_port(store), validate=validator(),
        first_activation=first_activation,
        withdrawals=withdrawals, mainline=LaneMainline(config, host),
        requalify=lambda document: requalify_delivery(store, config, host, document, lanes=lanes),
        artifacts=artifacts, research=research, ledger=lambda: CallBudget().counts())


def tick_policy(owner, config: dict, policy_id: str, *, source_factory=GitSource) -> dict:
    """One bounded tick; the registered pin is re-read so a changed policy refuses before any effect."""
    with owner.store.transaction() as tx:
        row = tx.get("owner_action_policies", policy_id)
    if row is None or not row["policy"]["enabled"]:
        return owner.scheduler.tick(policy_id)
    pin = row["pin"]
    try:
        sha = load_policy(source_factory(lane_of(config, pin["lane"])["repository"]), pin["revision"],
                          pin["path"])["pin"]["sha256"]
    except Exception as exc:
        return {"schema": "urn:zeus:owner-actions-tick:1", "policy_id": policy_id, "outcome": "refused",
                "reason_code": "policy_unavailable", "error_type": type(exc).__name__, "actions": []}
    return owner.scheduler.tick(policy_id, pin_sha256=sha)


def tick_policies(owner, config: dict, policy_ids, *, source_factory=GitSource) -> dict:
    """One bounded tick of each named policy in turn, in this one process. A refused read of one policy is
    that policy's named receipt and never stops the others; a research child is only polled, never waited."""
    results = []
    for policy_id in policy_ids:
        try:
            results.append(tick_policy(owner, config, policy_id, source_factory=source_factory))
        except (ContractError, OSError, RuntimeError, ValueError) as exc:
            results.append({"schema": TICK_SCHEMA, "policy_id": policy_id, "outcome": "refused",
                            "reason_code": getattr(exc, "reason_code", None) or "tick_failed",
                            "error_type": type(exc).__name__, "actions": []})
    outcomes = {result["outcome"] for result in results}
    outcome = "progressed" if "progressed" in outcomes else ("refused" if "refused" in outcomes else "idle")
    return {"schema": "urn:zeus:owner-actions-ticks:1", "outcome": outcome, "policies": results}


def policy_list(values) -> list:
    """The `--policy` values of one `run`: at least one, each once."""
    values = list(values or [])
    if not values or len(set(values)) != len(values):
        raise OwnerActionRefused("policy_list_invalid", "policy")
    return values


def run_loop(tick, *, interval: int = 15, max_ticks: int = 0, sleep=time.sleep) -> dict:
    """Gated wakeups: each tick does nothing while idle; a stop finishes the tick in flight."""
    stopping = {"stop": False}

    def stop(*_):
        stopping["stop"] = True

    installed = []
    for name in ("SIGINT", "SIGTERM"):
        handler = getattr(signal, name, None)
        try:
            installed.append((handler, signal.signal(handler, stop)))
        except (ValueError, OSError, TypeError):
            pass
    counts: dict = {}
    ticks = 0
    try:
        while not stopping["stop"]:
            result = tick()
            ticks += 1
            counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
            if max_ticks and ticks >= max_ticks:
                break
            sleep(max(1, int(interval)))
    finally:
        for handler, previous in installed:
            try:
                signal.signal(handler, previous)
            except (ValueError, OSError, TypeError):
                pass
    return {"schema": "urn:zeus:owner-actions-run:1", "ticks": ticks, "outcomes": counts, "stopped": stopping["stop"]}
