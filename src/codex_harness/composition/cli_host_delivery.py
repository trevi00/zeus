"""The `zeus host-delivery` composition: the production coordinator, the lane routing and the run loop (INV-HOST-DELIVERY-001).

Layer: composition
Owns: host_delivery_owners (the builder of the S7 split), maintenance_controller, maintenance_fleet, build_canary_executor and the private _invocation_environment, _maintenance_fleet_class (PR-3 arm/bind, G1-14b), read_document (S2R, G1-13 batch b), controller, controller_ports, release_verifier, resolve_lane, lane_git, run_loop, load_plan, configured_enabled, read_json and the private _host_settings, _settings, _control_schema, _lane_observer, _git, _observer
Does not own: the argument shape and the command bodies (entry.cli.host_delivery), the core adapters (delivery.adapters.host_delivery), `host_ports` (composition.delivery_hosts) and the launched service (entry.processes.delivery_service)
Entry points: host_delivery_owners, controller, controller_ports, release_verifier, resolve_lane, lane_git, run_loop
Contracts: INV-HOST-DELIVERY-001, INV-HOST-DELIVERY-VERIFY-001, INV-HOST-DELIVERY-FIRST-ACTIVATION-001, INV-HOST-DELIVERY-MAINTENANCE-001

Moved from M7 `adapters/host_delivery.py` (SOURCE e38aa722) by named rule R-c31 (S10 unit C8b-4), the documented S10 carry of S7's move of the core: `_host_settings` (:352-360), `release_verifier` (:1149-1169), `controller` (:1172-1198),
`_control_schema` (:1202-1215), `resolve_lane` (:1218-1262), `lane_git` (:1265-1272), `_lane_observer` (:1275-1280), `_git` (:1283-1287), `_settings` (:1348-1351), `_observer` (:1354-1357) and `run_loop` (:1360-1407).
The statements are M7's verbatim except the builder calls, the import homes and the split routing. `refusal` (:1140-1146) and `execute` (:1290-1345) are `entry.cli.host_delivery._refusal` and `_execute`.

M7's one `HostDelivery(store, org, **ports)` is the S7 split `delivery.application.host_delivery`. `host_delivery_owners` builds it exactly as `tests/ported/m7_delivery.HostDelivery` and `compare/drivers/target/s7_delivery_composition.py` do (the sixteen
objects in construction order, each constructor's parameters taken from its signature, the shared ports and the objects built before it), with the defaults M7's class built itself: `Releases` and `ReleaseQueue` over the store with the SYSTEM
clock and ids and `clock=utcnow`. It returns the objects as attributes of one namespace; there is no facade. Each M7 method call is routed to the owner that the shim's `ROUTES` names:

    M7 HostDelivery method (call site)                                   split owner (attribute)   class (delivery.application.host_delivery)
    register_targets (entry `register-targets`), status (entry `status`)  registry                  registry.DeliveryRegistry
    register (entry `register`)                                            registry                  registry.DeliveryRegistry
    tick (entry `tick`, run_loop)                                          controller                controller.DeliveryController
    withdraw (entry `withdraw`)                                            withdrawal                withdrawal.Withdrawal
    resume (entry `resume` without a document)                             resumption                resumption.Resumption
    resume_first_activation, resume_consumption_retry,
        resume_consumption_rearm, resume_generation_restart (entry `resume --document`)   recovery   recovery.Recovery
    status of the collect canary (`canary_checks`: M7 `monitoring.host_delivery_facts`)   registry    registry.DeliveryRegistry
    `delivery.verifier` (run_loop: the stop boundary)                      verification.verifier     stages.verify.Verification

The other objects of the namespace (state, publication, ci, merging, preparation, draining, switching, rollback, consumption, migration) are the controller's collaborators and the migration owner's; this module routes none of M7's CLI calls to
them and needs none of the shim's private routing (`_emit`, `_deadline`, `_now`, the class-level `_restart_state`/`_reservation_in`). M7's `Fleet(store)` is the S5 split: `registered` is `FleetRegistry` (`resolve_lane`) and the activation gate of the
managed targets (`activation_gate`) is `FleetPause` over the CONTROL store (`tests/ported/m7_coordination.Fleet`, `ROUTES`: registry, pause).

Other homes: `GitWorkspace` is `host_os.adapters.git_workspace`, `build_executor` is `composition.operation`, `build_observer` is `composition.observation`, `settings`, `codex_auth` and `runtime_dir` are `composition.configuration`, `lane_stores` is
`composition.continuation` (C8b-1), `lane_dsn` and `verify_lane_schema` are `coordination.adapters.fleet_runtime`, `host_ports` is `composition.delivery_hosts`, M7 `ReleaseVerifier` is `composition.release_verifier` (V34b) and M7 `ReleaseRunner` is
`delivery.adapters.deployment` through `composition.release_verification.release_runner` with the carries wired as `composition.cli_executor.release_runner` wires them (the same collaborators, with this verifier's `auto_merge`, `fence` and `verification_root`).
Seams M7 had no need for: `load_plan` (M7 `adapters.host_delivery.load_plan` over `GitSource`, bound to `backlog_blobs.read_blob` as `composition.owner_action_adapters` binds it), `configured_enabled` and `read_json` (M7's two module functions, which the entry
layer may not import from an adapter) and `controller_ports` (the ports `controller` hands the builder, so that a test can build the facade over the same wiring). Imports sit inside the functions, so importing this module stays light.
"""
from __future__ import annotations

import functools
import json
import os
import signal
import stat
import time
from pathlib import Path
from types import SimpleNamespace

from codex_harness.delivery.domain.host_delivery import DeliveryRefused


def host_delivery_owners(store, org=None, *, github=None, hosts=None, canaries=None, clock=None, observer=None, enabled=False,
                         releases=None, queue=None, resume_seconds=None, verifier=None, evaluator_pins=None,
                         controller_code=None, first_activation=None, authorities=None, artifacts=None, canary_records=None,
                         credentials=None, maintenance_fleet=None, canary_executor=None,
                         qualification_deadline=None) -> SimpleNamespace:
    """The S7 split of M7's `HostDelivery(store, org, **ports)`: the objects by key, as the module docstring tables."""
    import inspect

    from codex_harness.coordination.application import execution_fence
    from codex_harness.coordination.application.events import EventJournal
    from codex_harness.delivery.application.host_delivery import state as delivery_state
    from codex_harness.delivery.application.host_delivery.controller import DeliveryController
    from codex_harness.delivery.application.host_delivery.maintenance import DeliveryMaintenance
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
    from codex_harness.intake.application import tickets
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, utcnow
    from codex_harness.research.application.hook_rollback import HookRollback
    from codex_harness.review.application.release_queue import ReleaseQueue
    from codex_harness.review.application.releases import Releases

    # key -> class, in construction order (each object's collaborators are built before it)
    objects_in_order = (("state", DeliveryState), ("registry", DeliveryRegistry), ("verification", Verification),
                        ("publication", Publication), ("ci", CiObservation), ("merging", Merge),
                        ("preparation", SwitchPreparation), ("draining", Drain), ("switching", Switch),
                        ("rollback", Rollback), ("consumption", Consumption), ("controller", DeliveryController),
                        ("withdrawal", Withdrawal), ("resumption", Resumption), ("recovery", Recovery),
                        ("migration", DeliveryMigration),
                        ("maintenance", DeliveryMaintenance))
    queue = queue if queue is not None else ReleaseQueue(store, ticket_binding=tickets.ticket_binding,
                                                         fences=execution_fence, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
    values = {"store": store, "org": org, "github": github, "hosts": hosts or {}, "canaries": canaries or {},
              "clock": utcnow if clock is None else clock, "observer": observer, "enabled": enabled,
              "releases": releases if releases is not None else Releases(
                  store, org, ticket_binding=tickets.ticket_binding, ticket_superseded=tickets.TicketSuperseded,
                  events=EventJournal(), hooks=HookRollback(), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS),
              "claims": queue, "settlement": queue, "lease": queue,
              "resume_seconds": delivery_state.RESUME_SECONDS if resume_seconds is None else resume_seconds,
              "verifier": verifier, "evaluator_pins": evaluator_pins, "controller_code": controller_code,
              "first_activation": first_activation, "ticket_binding": tickets.ticket_binding,
              "authorities": authorities, "artifacts": artifacts, "canary_records": canary_records,
              "credentials": credentials, "maintenance_fleet": maintenance_fleet, "canary_executor": canary_executor,
              "qualification_deadline": qualification_deadline}
    objects: dict = {}
    for key, cls in objects_in_order:
        params = [p for p in inspect.signature(cls.__init__).parameters if p not in ("self", "store")]
        objects[key] = cls(store, **{p: objects[p] if p in objects else values[p] for p in params})
    return SimpleNamespace(**objects)


def _host_settings() -> dict:
    from codex_harness.composition.configuration import settings

    try:
        return settings()
    except Exception:
        # A malformed host configuration is not a reason to invent one; the receipt that follows
        # simply carries no effective image and is refused rather than accepted.
        return {}


def configured_enabled(host: dict) -> bool:
    """M7 `configured_enabled`: the host opt-in (an adapter function, so the entry layer reads it here)."""
    from codex_harness.delivery.adapters.host_delivery import configured_enabled as enabled

    return enabled(host)


def read_json(path: Path):
    """M7 `_read_json(path)`: a bounded JSON file, or None (an adapter function, so the entry layer reads it here)."""
    from codex_harness.delivery.adapters.host_delivery import _read_json

    return _read_json(path)


def load_plan(repository, revision: str, path: str) -> dict:
    """M7 `load_plan(GitSource(repository), revision, path)`: the pinned plan, read through `backlog_blobs.read_blob`."""
    from codex_harness.composition.cli_research import git_source
    from codex_harness.delivery.adapters import host_delivery
    from codex_harness.intake.adapters import backlog_blobs

    return host_delivery.load_plan(git_source(repository), revision, path, read_blob=backlog_blobs.read_blob)


def _canary_facts(store) -> dict:
    """M7 `monitoring.host_delivery_facts`: the status projection of a HostDelivery over the store (the registry owner)."""
    return host_delivery_owners(store, None).registry.status()


def release_verifier(service, store, git):
    """INV-HOST-DELIVERY-VERIFY-001: the owned-attempt port over the existing `ReleaseRunner`.

    The runner gets this delivery's store and the lane's own Git workspace, and never merges or
    promotes (only `evaluate` is driven). Nothing is created here: the artifact store and the
    verification root are touched only when an attempt actually runs.
    """
    from codex_harness.composition.configuration import codex_auth, runtime_dir
    from codex_harness.composition.release_verifier import ReleaseVerifier
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts

    runtime = runtime_dir()
    root = runtime / "verification"
    owner = SimpleNamespace(store=store, org=service.org)
    return ReleaseVerifier(
        lambda fence: _release_runner(owner, git, FileArtifacts(str(runtime / "artifacts")), str(codex_auth()),
                                      auto_merge=False, fence=fence, verification_root=root),
        root=root, artifacts=lambda: FileArtifacts(str(runtime / "artifacts")))


def _release_runner(owner, git, artifacts, auth, *, auto_merge, fence, verification_root):
    """M7 `ReleaseRunner(owner, git, artifacts, auth, auto_merge=, fence=, verification_root=)`, with the production carries wired as
    `composition.cli_executor.release_runner` wires them (that function fixes `auto_merge`, `fence` and `verification_root`)."""
    import sys

    from codex_harness.composition import cli
    from codex_harness.composition.release_verification import release_runner as runner_for
    from codex_harness.execution.adapters.providers.native_hooks import HookCandidates, HostHooks
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.host_os.adapters.verification import VerificationServices
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.observation.domain.observation import redact_text, redact_value
    from codex_harness.research.domain.recurrence import hook_apply
    from codex_harness.review.adapters.release_suite import ReleaseSuite

    def release_suite(artifacts, fence):
        return ReleaseSuite(artifacts, fence, run_logged_process=process_groups.run_logged_process, redact=redact_text,
                            redact_value=redact_value)

    def hooks(service, git, artifacts):
        units = cli.hook_units(service)
        show = lambda spec, strip=True: git._git("show", spec, strip=strip)  # noqa: E731 - read at call time
        return HookCandidates(units, service.store, show, HostHooks(units, show, artifacts, sys.executable),
                              validate=hook_apply, runner=process_groups.run_process,
                              channel_environment=process_groups.python_channel_environment, interpreter=sys.executable)

    return runner_for(owner, git, artifacts, auth, auto_merge, fence, verification_root, runner=process_groups.run_process,
                      release_suite=release_suite, verification_services=VerificationServices, hooks=hooks,
                      request_rebase=cli.messages(owner).request_rebase, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


def controller_ports(service, *, enabled=None, observer=None, git=None, store=None) -> tuple:
    """`(store, ports)` of `controller`: the store this delivery's records live in and the ports `host_delivery_owners` takes."""
    from codex_harness.composition.configuration import settings
    from codex_harness.composition.delivery_hosts import host_ports
    from codex_harness.context.adapters import worker_profile
    from codex_harness.coordination.application.fleet.pause import FleetPause
    from codex_harness.delivery.adapters import host_delivery
    from codex_harness.delivery.adapters.host_delivery import (
        GitHubDelivery,
        canary_checks,
        configured_enabled,
        systemd_control_dir,
    )
    from codex_harness.host_os.adapters.git_source import GitSource
    from codex_harness.host_os.adapters.process_groups import run_process

    store = service.store if store is None else store
    if enabled is None:
        enabled = configured_enabled(settings())
    github = None if git is None else GitHubDelivery(git, runner=run_process)
    verifier = release_verifier(service, store, git) if enabled and git is not None else None
    # INV-HOST-DELIVERY-FIRST-ACTIVATION-001: the trusted port over THIS workspace's repository (the
    # lane's own for a `--lane` route) and the host settings SSOT, read only when a binding is resumed.
    first_activation = None if git is None else (
        lambda revision: host_delivery.first_activation_facts(
            {"repository": str(git.repository)}, settings(), revision, run=run_process,
            source=GitSource(str(git.repository)), profiles=worker_profile))
    return store, {"github": github,
                   "hosts": host_ports(fleet=FleetPause(service.store), systemd_control=systemd_control_dir(settings())),
                   "canaries": canary_checks(store, facts=_canary_facts), "observer": observer, "enabled": enabled,
                   "verifier": verifier, "first_activation": first_activation}


def controller(service, *, enabled=None, observer=None, git=None, store=None) -> SimpleNamespace:
    """The coordinator with its existing owners and this host's real ports wired.

    `store` is where this delivery's records live: the control store by default, or the store of
    the one lane `resolve_lane` selected. Releases, the ReleaseQueue fence, targets, descriptors and
    the collect canary all read it. The managed target's activation gate does NOT: it is always
    the ACTUAL Fleet of the control store (`service.store`), because that is where admission, the
    reserving jobs and the held execution units are. A lane store has no Fleet registry of its own,
    so gating on it would hide the real debt instead of reading it.
    """
    store, ports = controller_ports(service, enabled=enabled, observer=observer, git=git, store=store)
    return host_delivery_owners(store, service.org, **ports)


def read_document(path: Path):
    """S2R `_read_document(path)` (INV-HOST-DELIVERY-MAINTENANCE-001): the operator's maintenance document, one bounded regular JSON
    file, or None.

    Opened without blocking and checked to be a regular file by `fstat`, so a FIFO or a device named as the document is refused
    instead of waiting forever; malformed, oversized or unreadable is None."""
    from codex_harness.delivery.adapters.host_delivery import MAX_STATE_BYTES

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(MAX_STATE_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    if len(data) > MAX_STATE_BYTES:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        return None


@functools.cache
def _maintenance_fleet_class():
    """The control-store Fleet's maintenance seam as ONE object (`delivery.ports.MaintenanceFleet`): coordination's `FleetPause`
    (readiness and the activation gate, so the managed target keeps using it) plus the permit and job methods of its
    `FleetMaintenance` (PR-3's one `Fleet`). Built lazily: coordination is imported only when a maintenance is wired."""
    from codex_harness.coordination.application.fleet.maintenance import FleetMaintenance
    from codex_harness.coordination.application.fleet.pause import FleetPause
    from codex_harness.coordination.application.fleet.registry import FleetRegistry

    class MaintenanceFleet(FleetPause):
        @property
        def maintenance(self):
            return FleetMaintenance(self.store, clock=self.clock, token=self.token)

        @property
        def registry(self):
            return FleetRegistry(self.store, clock=self.clock, token=self.token)

        def registered(self):
            return self.registry.registered()

        def grant_maintenance_canary(self, permit):
            return self.maintenance.grant_maintenance_canary(permit)

        def admit_maintenance_canary(self, maintenance_id, **kwargs):
            return self.maintenance.admit_maintenance_canary(maintenance_id, **kwargs)

        def close_maintenance_canary(self, permit, reason):
            return self.maintenance.close_maintenance_canary(permit, reason)

        def maintenance_permit(self, maintenance_id):
            return self.maintenance.maintenance_permit(maintenance_id)

        def job(self, job_id):
            return self.maintenance.job(job_id)

    return MaintenanceFleet


def _lane_launcher(config, settings):
    from codex_harness.composition.fleet import lane_launcher

    return lane_launcher(config, settings)


def maintenance_fleet(store):
    return _maintenance_fleet_class()(store)


def build_canary_executor(fleet, launcher):
    """PR-3 `LazyCanaryExecutor`'s executor: coordination's `MaintenanceCanaryExecutor` over the Fleet objects of `fleet`'s
    control store (G1-14a)."""
    from codex_harness.coordination.application.fleet.admission import AdmissionControl
    from codex_harness.coordination.application.fleet.runner import MaintenanceCanaryExecutor

    return MaintenanceCanaryExecutor(fleet.registry, fleet.maintenance, AdmissionControl(fleet.store), fleet, launcher)


def _invocation_environment() -> dict:
    """The maintenance inputs the CLI invocation itself carries (G1-03 ruling (c)): exactly these process
    environment variables, never the persisted configuration file."""
    from codex_harness.delivery.adapters.maintenance_evidence import (
        HELPER_SETTING,
        HELPER_SHA256_SETTING,
        QUALIFICATION_DEADLINE_SETTING,
    )

    names = (HELPER_SETTING, HELPER_SHA256_SETTING, QUALIFICATION_DEADLINE_SETTING)
    return {name: os.environ[name] for name in names if name in os.environ}


def maintenance_controller(service, *, store, check: bool) -> SimpleNamespace:
    """The coordinator of INV-HOST-DELIVERY-MAINTENANCE-001 with exactly its ports (S2R `maintenance_controller`, PR-3).

    `store` holds this delivery's records (the control store, or the `--lane` store). The Fleet, the owner-action rows and the
    credential, authority and artifact ports are the CONTROL runtime's, as for the activation gate: the Fleet is
    `maintenance_fleet(service.store)`, which is both the managed target's activation gate and the maintenance seam. No tick
    observer, Git workspace, verifier or GitHub port is built, and `--check` builds no artifact store and no canary executor: it
    can create nothing. Nothing here prints a DSN or accepts a token; every import is lazy. The maintenance use case is the
    `maintenance` attribute of the returned owners (S2R's one `HostDelivery.maintain`).
    """
    from codex_harness.composition import delivery_hosts
    from codex_harness.composition.configuration import runtime_dir
    from codex_harness.composition.delivery_hosts import host_ports
    from codex_harness.delivery.adapters.host_delivery import (
        canary_checks,
        configured_enabled,
        systemd_control_dir,
    )
    from codex_harness.delivery.adapters.maintenance_evidence import (
        LazyArtifacts,
        LazyCanaryExecutor,
        control_action_reader,
        credential_observer,
        qualification_deadline,
        trusted_authority_reader,
    )
    from codex_harness.host_os.adapters import process_groups

    def file_artifacts(root):
        from codex_harness.storage.adapters.file_artifacts import FileArtifacts

        return FileArtifacts(root)

    host = _settings()
    # G1-03 ruling (c): the credential helper's path and pin and the qualification bound come from THIS invocation's
    # environment only, never from the persisted configuration file `_settings()` also reads.
    invocation = _invocation_environment()
    fleet = maintenance_fleet(service.store)
    root = runtime_dir() / "artifacts"
    return host_delivery_owners(store, service.org,
                                hosts=host_ports(fleet=fleet, systemd_control=systemd_control_dir(host)),
                                canaries=canary_checks(store, facts=_canary_facts), observer=None,
                                enabled=configured_enabled(host), authorities=trusted_authority_reader(root),
                                artifacts=None if check else LazyArtifacts(root, file_artifacts),
                                canary_records=control_action_reader(service.store),
                                credentials=credential_observer(invocation, delivery_hosts.process_reader(),
                                                               process_groups.popen),
                                maintenance_fleet=fleet,
                                canary_executor=(None if check else LazyCanaryExecutor(fleet, host, _lane_launcher, build_canary_executor)),
                                qualification_deadline=qualification_deadline(invocation))


# ----- explicit lane routing -----------------------------------------------------------------------
def _control_schema(store):
    """The schema the control store's own connection selects, or None for a store without a DSN.

    A lane that resolves to this same schema IS the control store, not a lane, and is refused."""
    dsn = getattr(store, "dsn", None)
    if dsn is None:
        return None
    import psycopg

    try:
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            return connection.execute("SELECT current_schema()").fetchone()[0]
    except Exception as exc:
        raise DeliveryRefused("lane_control_unidentified", "lane") from exc


def resolve_lane(service, lane_id, *, host=None, store_factory=None, verify=None,
                 control_schema=_control_schema) -> dict:
    """The ONE registered Fleet lane a `--lane` command acts on, or a named refusal. No fallback.

    The lane comes from the Fleet registry of the CONTROL store, through the same `lane_of`,
    `lane_dsn`, `verify_lane_schema` and `lane_stores` the Fleet launcher and the owner actions
    already use, so this command and `owner-actions` reach the same lane store. A registry that is
    missing or unreadable, an unknown or duplicated lane id, a lane schema that is not provisioned
    or does not select itself, and a lane that is the control schema all refuse before any store,
    Git or host effect; nothing is ever routed back to the control store instead.

    No process environment is changed: the lane DSN exists only inside the returned store, so every
    child this controller starts (the managed launcher, the systemd unit) keeps the control env.
    """
    from codex_harness.composition.continuation import lane_stores
    from codex_harness.coordination.adapters.fleet_runtime import lane_dsn, verify_lane_schema
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.domain.fleet import FleetRefused

    if not (type(lane_id) is str and lane_id):
        raise DeliveryRefused("lane_invalid", "lane")
    try:
        config = FleetRegistry(service.store).registered()["config"]
    except FleetRefused as exc:
        code = "lane_registry_unregistered" if exc.reason_code == "unregistered" else "lane_registry_invalid"
        raise DeliveryRefused(code, "lane") from exc
    except Exception as exc:
        raise DeliveryRefused("lane_registry_unavailable", "lane") from exc
    matches = [lane for lane in config.get("lanes") or [] if lane.get("id") == lane_id]
    if not matches:
        raise DeliveryRefused("lane_unknown", "lane")
    if len(matches) > 1:
        raise DeliveryRefused("lane_ambiguous", "lane")
    lane = matches[0]
    host = _settings() if host is None else host
    try:
        (verify or verify_lane_schema)(lane_dsn(host.get("HARNESS_DATABASE_URL"), lane["schema"]),
                                       lane["schema"])
    except FleetRefused as exc:
        code = exc.reason_code if exc.reason_code.startswith("lane_") else "lane_" + exc.reason_code
        raise DeliveryRefused(code, "lane") from exc
    if control_schema is not None and control_schema(service.store) == lane["schema"]:
        raise DeliveryRefused("lane_is_control", "lane")
    store = lane_stores(config, host, store_factory)(lane_id).store
    return {"lane": lane, "store": store}


def lane_git(lane: dict, host: dict):
    """The lane's OWN registered repository as the Git/GitHub workspace, with its workspaces under
    the lane runtime - where the lane's own candidates were cut - and the host's GitHub setting
    that the Fleet launcher forwards into every lane child (`lane_environment`)."""
    from codex_harness.host_os.adapters.git_workspace import GitWorkspace

    return GitWorkspace(lane["repository"], str(Path(lane["runtime"]) / "workspaces"),
                        host.get("HARNESS_GITHUB_REPO"))


def _lane_observer(route: dict):
    """The tick observer of a lane delivery: the lane store, the lane runtime's own spool."""
    from codex_harness.composition.observation import build_observer

    return build_observer(route["store"], "cli.host-delivery",
                          root=Path(route["lane"]["runtime"]) / "observations")


def _git(service):
    """The existing configured workspace; built only for the commands that need Git or GitHub."""
    from codex_harness.composition.operation import build_executor

    return build_executor(service).git


def _settings() -> dict:
    from codex_harness.composition.configuration import settings

    return settings()


def _observer(service):
    from codex_harness.composition.observation import build_observer

    return build_observer(service.store, "cli.host-delivery")


def run_loop(delivery, *, verifier=None, once: bool = False, interval: int = 15,
             max_ticks: int = 0, sleep=time.sleep) -> dict:
    """Bounded tick loop. An idle queue sleeps; it calls no provider and starts no model.

    A stop is graceful: the signal sets a flag, the tick in flight finishes, and the loop returns
    its counts. Nothing here kills a service or a lease. The one exception is an owned verification
    evaluation in flight (INV-HOST-DELIVERY-VERIFY-001): the FIRST signal also raises
    `EvaluationCancelled` into it, once, so its own children and containers are ended and its
    cleanup is proven before the tick records `verification_interrupted`; later signals only set
    the flag and never interrupt that cleanup.

    `delivery` is the object whose `tick()` runs (the controller owner) and `verifier` the one whose stop boundary
    is signalled (the verification owner's); when `verifier` is not given it is read from `delivery`, as M7 read it.
    """
    stopping = {"stop": False}
    boundary = getattr(getattr(delivery, "verifier", None) if verifier is None else verifier, "boundary", None)
    if boundary is not None:
        boundary.reset()

    def stop(*_):
        stopping["stop"] = True
        if boundary is not None:
            boundary.signal()

    installed = []
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        handler = getattr(signal, name, None)
        if handler is None:
            continue
        try:
            installed.append((handler, signal.signal(handler, stop)))
        except (ValueError, OSError):
            pass
    counts: dict[str, int] = {}
    ticks = 0
    try:
        while not stopping["stop"]:
            result = delivery.tick()
            ticks += 1
            counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
            if once or (max_ticks and ticks >= max_ticks):
                break
            sleep(max(1, int(interval)))
    finally:
        for handler, previous in installed:
            try:
                signal.signal(handler, previous)
            except (ValueError, OSError):
                pass
    return {"schema": "urn:zeus:host-delivery-run:1", "ticks": ticks, "outcomes": counts,
            "stopped": stopping["stop"]}
