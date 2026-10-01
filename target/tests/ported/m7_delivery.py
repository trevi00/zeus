"""M7 `HostDelivery` surface over the S7 target, for the ported M7 HostDelivery suites.

Layer: harness (never shipped). A TEST shim: it lets M7 `tests/test_host_delivery*.py` run, with their assertions
unchanged, against the split objects of `delivery.application.host_delivery` (DESIGN-s7 V8) as composition will build
them (S10). The wiring mirrors `compare/drivers/target/s7_delivery_composition.py` (HostDelivery, `releases_for`,
`queue_for`) and `s7_host_targets.py` (the moved adapters); ids and clocks are NOT scripted here: as in M7 the real
clock and uuid4 are used (kernel `utcnow`, SYSTEM_CLOCK/SYSTEM_IDS).

Named adaptations (each is a construction/import/patch-target adaptation, never a behaviour change):
- `HostDelivery(store, org=None, **ports)` is a facade over the split objects, built as the composition builds them: its
  route table, and an unrouted name raises AttributeError (never a fallback). M7's one object held ONE value per
  collaborator, so a replaced collaborator (`delivery.github = None`, `delivery._emit = racing`) is replaced in every
  object that holds it. The default clock is `utcnow`; the default `releases` and `queue` are built as below.
- `Releases(store, org, **ports)` and `ReleaseQueue(store, **ports)` are the review objects wired as composition wires
  them (`releases_for`/`queue_for`): intake's `ticket_binding`, coordination's execution fence and event journal,
  research's hook rollback, and the SYSTEM clock/ids M7's classes used.
- `ProcessHostTarget(**kwargs)` and `GitHubDelivery(workspace, **kwargs)` are the moved adapters with the production
  injections closed over, as composition passes them: `processes=ChokepointProcesses()` and
  `runner=process_groups.run_process` (a case may still supply its own `runner`). Both stay subclassable.
- `effective_worker_image(config=None)` reads the host settings (`composition.configuration.settings`, an unreadable
  configuration being `{}`) when no config is given, as M7's no-argument form did; `effective_profile_digest()`,
  `committed_profile_digest(source, revision)`, `first_activation_facts(lane, host, revision, run=, source=)`, `serve`
  and `startup_receipt` pass the worker profile module / the effective image and profile digest as the production
  entry does (`context.adapters.worker_profile`).
- `aliases`/`read_env` are `composition.configuration.aliases`/`read_env`; `GitSource` is `host_os.adapters.git_source`
  (M7 `adapters.operation_cli`); `organization` is `routing.adapters.organization_source.packaged_organization`;
  `MemoryStore`, `GitWorkspace`, `GitCommandError`, `MergeRefused`, `ContractError`, `FileArtifacts`, `MemorySpool`,
  `MemoryDirectory`, `Observer`, `new_process_run_id`, `POLICY`, `digest` and the BUCKET_* names come from their
  target homes. `Fleet` is `m7_coordination.Fleet` plus M7's private `_repository_aliases(tx)`, which is
  `coordination.application.fleet.state.repository_aliases`.
- `collect_monitor_canary` / `canary_checks` default `facts` to the delivery status projection over the store (M7
  `monitoring.host_delivery_facts` is `HostDelivery(store).status()`); `first_activation_facts` defaults `run` to
  `process_groups.run_process` and `source` to a `GitSource` over the lane repository, as M7's defaults resolved them.
- `HostDelivery` also routes M7's private `_now` to `DeliveryState.now` (read and assignment), and the class-level
  `_restart_state` / `_reservation_in` (read; an assignment to `_restart_state` installs on the `Recovery` class, the
  owner M7's `self._restart_state(...)` reached). These extend the composition's route table.
- `loaded_runtime()` reports the git-attested runtime root `conftest.pytest_collectstart` (the first ported collector, before any module import) builds once per session under
  pytest's basetemp (a COPY of the target `src/codex_harness`, committed under a pinned identity, as
  `s7_host_targets.attested_repository` does), because the target package's own root `target/` is neither a git root
  nor holds a `runtime.json`, so M7's `binds_a_runtime` guard would skip the real-child cases for good. The suites'
  `RUNTIME_REVISION = runtime_revision(RUNTIME_ROOT)` is read from that checkout, not invented; real children run the copy.
- `observes_this_process` (fixture, `usefixtures`) is a patch-target adaptation. M7's module constant
  `RUNTIME_ROOT = loaded_runtime()["runtime_root"]` means two things that coincide in M7 and differ here: (a) the root
  launched children run from, the attested copy; (b) THIS process's own identity as an in-process `serve()` observes it.
  For the duration of the one test that observes (b) and asserts against the constants,
  `test_the_launched_service_reports_the_identity_it_actually_loaded` (M7 lines 995-997: "Observed, not echoed: this
  process's own root, package, revision and effective configuration"; M7 already allows `RUNTIME_REVISION or ""`), it
  binds the ported module's `RUNTIME_ROOT`/`RUNTIME_REVISION` to the process's real values. Child-launching tests keep (a).
- Host migration (`test_host_migration*.py`, `test_fleet_host_migration.py`): `host_migration` and
  `host_migration_evidence` stand for M7 `adapters.host_migration` / `adapters.host_migration_evidence` (the suites'
  `adapter` / `producer`). Each is a facade over the moved module: a name reads from the module, an assignment
  (`monkeypatch.setattr(adapter, "write_activation", ...)`, `_posix`) is made on the module, so the module's own calls see
  it; `adapter.os` is the module's `os`. The names whose moved signature REQUIRES a collaborator (DESIGN-s7 adapters-move
  V6) close over the one composition passes, a case's own `runner=` winning as in M7: `run_canonical` and
  `pg_compare_schema` the chokepoint `process_groups.run` (M7's default was `subprocess.run`); `pg_dump_database`,
  `pg_restore_database`, `recovery_preconditions` and `switch_effect` `process_groups.run_process`;
  `HostReader` and `bounded_run` of the evidence module `processes=ChokepointProcesses()`. The operator CLI names
  (`main`, `parser`, `schema_store`, `cli_ports`, `observe_command`) and `canonical_module`'s provider (S10) are not on
  the facades: only tests skipped whole, with the owning slice, name them. `HostMigrations` is
  `delivery.application.host_migration`, `HostFacts` is `host_os.adapters.host_facts`.
- `fleet_recovery` stands for M7 `adapters.fleet_recovery`: the moved `coordination.adapters.fleet_recovery` (its
  `checkout_identity`, `collect_recovery_proof`, `collect_relocation_proof`, `collect_host_migration_proof` and
  `run_root` are also module names here) with `state` (a case's own wins), `run_records` and `git_source` supplied as
  `composition.fleet_recovery.collectors()` wires them (`budget` is only `collect_recovery_proof`'s, a case's own);
  `run_records` is the collectors' (M7 `adapters.isolated_worker.run_records`) and `run_process` is
  `process_groups.run_process` (M7 `adapters.commands.run_process`). `fleet_cli` (the operator CLI, S10) is an `unavailable` placeholder.
- Release runner (`test_file_canary`, `test_check_binding`, `test_release_runner`, `test_evaluator_code_guard`):
  `ReleaseRunner(service, git, artifacts, auth, auto_merge=True, fence=None, verification_root=None)` is
  `composition.release_verification.release_runner` with what M7's class built itself supplied as the delivery
  driver does (`compare/drivers/target/s7_release_runner.py`): `runner` is a holder over `process_groups.run_process`,
  `verification_services` and `request_rebase` are LABELLED refusals (their owners are S8 and S5) unless a case installs
  its own double, and `release_suite` and `hooks` are LABELLED refusals (S8/S10: never reached by these suites). The
  patch targets move with the collaborators: `deployment.run_process` (read/assigned) is the `runner` holder,
  `deployment.VerificationServices` the `verification_services` holder, and `Workflow.request_rebase` the `request_rebase`
  holder (called as M7 called it, `value(handler, task_id, base)`); `deployment` otherwise stands for the moved
  `delivery.adapters.deployment`. `fake_verification_services` is M7 `tests/conftest.py`'s fixture over that holder.
  `attempt_resources` closes over `ExecutionContainerNaming()`, the check_results names come from
  `review.domain.check_results`, `Harness` is `m7_coordination.Harness`, `FileArtifacts(root)` the target's with its
  default clock. The helpers of M7 modules whose suites are not ported (S8) that these suites import are labelled
  VERBATIM copies here, only their imports (and the `git` helper's name, `_fixture_git`) differing: `source_repository`
  (`verification_fixtures`), `candidate_runner` (`test_release_recovery`; it imports the ported `test_git_workspace`
  lazily), `runner_for` and `reviewed_record` (`test_release_evaluator_migration`). None reaches `fake_docker`, `fake_uv`
  or the real `ReleaseSuite`.
- Managed runtime (`test_managed_runtime`, `test_managed_systemd`): `ManagedFleetTarget`, `SystemdManagedFleetTarget` and
  `Materializer` are the moved adapters wired as composition wires them (`ChokepointProcesses()`, `configuration`,
  `run_process`; `compare/drivers/target/s7_managed_composition.py`); each class also recognizes its unwired base in
  `isinstance`, because `host_ports()` (`composition.delivery_hosts`) builds the base. `fixture_config`, `fixture_manifest`,
  `supervise` (`launcher=launch`) are `composition.managed_runtime`'s, the domain/fleet names come from their target homes,
  and `controller` (the production coordinator, S10) is an `unavailable`.
- Tooling (`test_aibox_service_templates`, `test_aibox_data_manifest`): the suites' own path-based loads of
  `deploy/aibox/zeus_aibox_service.py` and `scripts/aibox_data` are unchanged; only `ROOT`'s `parents[1]` is `parents[2]`
  (the target tree holding `deploy/` and `scripts/`).
- `database_url()` is the DSN of the disposable database the target conftest's `isolated_pgstore` uses (`ZEUS_TEST_DSN`;
  M7 `bootstrap.database_url`).
- Owner actions (`test_owner_actions_*`, `test_owner_canary_plan`, `test_owner_delivery`): `GitPlanPublisher(repository,
  timeout=)` is the moved `coordination.adapters.owner_actions.GitPlanPublisher` with the wiring
  `composition.owner_action_adapters.git_plan_publisher` closes over it (a named construction adaptation; subclassable),
  and `TargetFiles` is `delivery.adapters.target_files.TargetFiles`.
- `unavailable(slice_, name)` is `m7_coordination.unavailable`: a name whose owner is in a later slice imports as a
  placeholder that raises on use, and only tests skipped whole (with the owning slice) name it.
"""

from __future__ import annotations

import inspect
import os
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import ATTESTED
from m7_coordination import Fleet as _Fleet
from m7_coordination import (
    Harness,  # noqa: F401
    unavailable,
)

from codex_harness.composition import configuration, delivery_hosts
from codex_harness.composition import fleet_recovery as _recovery_composition
from codex_harness.composition import managed_runtime as _managed_composition
from codex_harness.composition import owner_action_adapters as _owner_adapters
from codex_harness.composition.release_verification import ExecutionContainerNaming, release_runner
from codex_harness.context.adapters import worker_profile
from codex_harness.coordination.adapters import fleet_recovery as _fleet_recovery
from codex_harness.coordination.application import execution_fence
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.fleet.state import repository_aliases
from codex_harness.delivery.adapters import deployment as _deployment
from codex_harness.delivery.adapters import host_delivery as _adapter
from codex_harness.delivery.adapters import host_migration as _migration
from codex_harness.delivery.adapters import host_migration_evidence as _evidence
from codex_harness.delivery.adapters import managed_runtime as _managed
from codex_harness.delivery.adapters.host_delivery import (  # noqa: F401
    DESCRIPTOR_FILE,
    LOCK_DIR,
    PAUSE_FILE,
    RECEIPT_FILE,
    STATE_FILE,
    STOP_FILE,
    WORK_FILE,
    canary_receipt_file,
    canary_request_file,
    normalize_checks,
    owner_qualified_canary,
    runtime_revision,
    startup_identity_canary,
)
from codex_harness.delivery.adapters.target_files import TargetFiles  # noqa: F401
from codex_harness.delivery.application.host_delivery import state as delivery_state
from codex_harness.delivery.application.host_delivery.controller import DeliveryController
from codex_harness.delivery.application.host_delivery.migration import DeliveryMigration
from codex_harness.delivery.application.host_delivery.recovery import Recovery
from codex_harness.delivery.application.host_delivery.registry import DeliveryRegistry, reservation_in
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
from codex_harness.delivery.application.host_migration import HostMigrations  # noqa: F401
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters.git_source import GitSource  # noqa: F401
from codex_harness.host_os.adapters.git_workspace import (  # noqa: F401
    GitCommandError,
    GitWorkspace,
    MergeRefused,
)
from codex_harness.host_os.adapters.host_facts import HostFacts  # noqa: F401
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError  # noqa: F401
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, digest, utcnow  # noqa: F401
from codex_harness.kernel.policy import POLICY  # noqa: F401
from codex_harness.observation.adapters.observation_spool import MemorySpool  # noqa: F401
from codex_harness.observation.application.observations import MemoryDirectory, Observer  # noqa: F401
from codex_harness.observation.domain.observation import new_process_run_id  # noqa: F401
from codex_harness.research.application.hook_rollback import HookRollback
from codex_harness.review.application.release_queue import ReleaseQueue as _ReleaseQueue
from codex_harness.review.application.releases import Releases as _Releases
from codex_harness.review.domain import check_results  # noqa: F401
from codex_harness.routing.adapters.organization_source import (
    packaged_organization as organization,  # noqa: F401
)
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: F401
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: F401
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: F401

aliases, read_env = configuration.aliases, configuration.read_env


class Fleet(_Fleet):
    @staticmethod
    def _repository_aliases(tx):  # M7's was static: read on the class (`Fleet._repository_aliases(tx)`) and on an instance
        return repository_aliases(tx)


def loaded_runtime() -> dict:
    """The attested runtime root the suites bind (conftest `pytest_collectstart`), with this process's module root."""
    return {**_adapter.loaded_runtime(), "runtime_root": ATTESTED["root"]}


class Releases(_Releases):
    def __init__(self, store, org, **ports):
        ports.setdefault("clock", SYSTEM_CLOCK)
        ports.setdefault("ids", SYSTEM_IDS)
        super().__init__(store, org, ticket_binding=tickets.ticket_binding,
                         ticket_superseded=tickets.TicketSuperseded, events=EventJournal(), hooks=HookRollback(),
                         **ports)


class ReleaseQueue(_ReleaseQueue):
    def __init__(self, store, **ports):
        ports.setdefault("clock", SYSTEM_CLOCK)
        ports.setdefault("ids", SYSTEM_IDS)
        super().__init__(store, ticket_binding=tickets.ticket_binding, fences=execution_fence, **ports)


class ProcessHostTarget(_adapter.ProcessHostTarget):
    def __init__(self, **kwargs):
        super().__init__(processes=process_groups.ChokepointProcesses(), **kwargs)


class GitHubDelivery(_adapter.GitHubDelivery):
    def __init__(self, workspace, *, runner=process_groups.run_process, **kwargs):
        super().__init__(workspace, runner=runner, **kwargs)


class GitPlanPublisher(_owner_adapters.GitPlanPublisher):
    """M7 `GitPlanPublisher(repository, timeout=...)` with the production wiring closed over, as
    `composition.owner_action_adapters.git_plan_publisher` wires it (runner, load_plan, git_source). Stays subclassable."""

    def __init__(self, repository, *, timeout=_owner_adapters.GIT_TIMEOUT):
        wired = _owner_adapters.git_plan_publisher(repository, timeout=timeout)
        super().__init__(repository, timeout=timeout, runner=wired.runner, load_plan=wired.load_plan,
                         git_source=wired.git_source)


@pytest.fixture
def observes_this_process(request, monkeypatch):
    """For a test that observes this process's identity in-process: bind the module's `RUNTIME_ROOT` and
    `RUNTIME_REVISION` to this process's REAL values (the product `loaded_runtime()` root, whose revision is read from
    it), restored afterwards."""
    root = _adapter.loaded_runtime()["runtime_root"]
    monkeypatch.setattr(request.module, "RUNTIME_ROOT", root)
    monkeypatch.setattr(request.module, "RUNTIME_REVISION", runtime_revision(root))


def _host_settings() -> dict:
    try:
        return configuration.settings()
    except Exception:
        return {}


def effective_worker_image(config=None) -> str:
    return _adapter.effective_worker_image(_host_settings() if config is None else config)


def effective_profile_digest():
    return _adapter.effective_profile_digest(worker_profile)


def committed_profile_digest(source, revision):
    return _adapter.committed_profile_digest(source, revision, worker_profile)


class _LaneSource:
    """`GitSource(lane["repository"])`, built on first use as M7's default was."""

    def __init__(self, lane):
        self.lane = lane

    def blob(self, revision, path):
        return GitSource(self.lane["repository"]).blob(revision, path)


def first_activation_facts(lane, host, revision, *, run=None, source=None):
    host = _host_settings() if host is None else host
    return _adapter.first_activation_facts(
        lane, host, revision, run=run or process_groups.run_process,
        source=_LaneSource(lane) if source is None else source, profiles=worker_profile)


def serve(state_dir, max_seconds=_adapter.SERVICE_MAX_SECONDS):
    return _adapter.serve(state_dir, max_seconds, image=effective_worker_image(),
                          profile_digest=effective_profile_digest())


def startup_receipt(descriptor):
    return _adapter.startup_receipt(descriptor, image=effective_worker_image(),
                                    profile_digest=effective_profile_digest())


def database_url():
    """The DSN of the disposable database the target conftest's `isolated_pgstore` uses (M7 `bootstrap.database_url`)."""
    return os.environ["ZEUS_TEST_DSN"]


def harness_database_url() -> str:
    """M7's `settings().get("HARNESS_DATABASE_URL") or ""` as its suites read it. In M7's integration runs that variable IS
    the disposable test database (M7 `bootstrap.database_url`); the target harness exports the same DSN as
    `ZEUS_TEST_DSN` (R-X: production endpoint names are refused), so integration runs read that, and every other run
    keeps M7's own reading (environment-naming adaptation, 2026-10-01: found by `compare/run.py target-integration`)."""
    return os.environ.get("ZEUS_TEST_DSN") or configuration.settings().get("HARNESS_DATABASE_URL") or ""


def delivery_facts(store):
    """M7 `monitoring.host_delivery_facts`: the status projection of a HostDelivery over the store."""
    return HostDelivery(store, None).status()


def collect_monitor_canary(target, descriptor, startup, *, store=None, facts=None):
    return _adapter.collect_monitor_canary(target, descriptor, startup, store=store, facts=facts or delivery_facts)


def canary_checks(store=None, *, facts=None):
    return _adapter.canary_checks(store, facts=facts or delivery_facts)


class _Facade:
    """A module as the M7 suites saw it: names read from the moved module unless wrapped, assignments land on the module."""

    def __init__(self, module, **wrapped):
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_wrapped", wrapped)

    def __getattr__(self, name):
        wrapped = object.__getattribute__(self, "_wrapped")
        return wrapped[name] if name in wrapped else getattr(object.__getattribute__(self, "_module"), name)

    def __setattr__(self, name, value):
        wrapped = object.__getattribute__(self, "_wrapped")
        if name in wrapped:
            wrapped[name] = value
        else:
            setattr(object.__getattribute__(self, "_module"), name, value)

    def __delattr__(self, name):
        delattr(object.__getattribute__(self, "_module"), name)


def _with_runner(function, default):
    def call(*args, runner=default, **kwargs):
        return function(*args, runner=runner, **kwargs)
    return call


host_migration = _Facade(
    _migration,
    run_canonical=_with_runner(_migration.run_canonical, process_groups.run),
    pg_compare_schema=_with_runner(_migration.pg_compare_schema, process_groups.run),
    pg_dump_database=_with_runner(_migration.pg_dump_database, process_groups.run_process),
    pg_restore_database=_with_runner(_migration.pg_restore_database, process_groups.run_process),
    recovery_preconditions=_with_runner(_migration.recovery_preconditions, process_groups.run_process),
    switch_effect=_with_runner(_migration.switch_effect, process_groups.run_process))


class _HostReader(_evidence.HostReader):
    def __init__(self, **kwargs):
        super().__init__(processes=process_groups.ChokepointProcesses(), **kwargs)


def _bounded_run(argv, **kwargs):
    return _evidence.bounded_run(argv, processes=process_groups.ChokepointProcesses(), **kwargs)


host_migration_evidence = _Facade(_evidence, HostReader=_HostReader, bounded_run=_bounded_run)


def _collected():
    return _recovery_composition.collectors(budget=None)


def checkout_identity(path, source=None):
    return _fleet_recovery.checkout_identity(path, source, git_source=_collected().git_source)


def collect_host_migration_proof(request, jobs, *, journal, host_dsn, state=None, **kwargs):
    wired = _collected()
    return _fleet_recovery.collect_host_migration_proof(
        request, jobs, journal=journal, host_dsn=host_dsn, state=wired.state if state is None else state,
        run_records=wired.run_records, git_source=wired.git_source, **kwargs)


def collect_recovery_proof(evidence, lane, *, reader, budget, state, clock=utcnow):
    return _fleet_recovery.collect_recovery_proof(evidence, lane, reader=reader, budget=budget, state=state,
                                                  run_records=_collected().run_records, clock=clock)


def collect_relocation_proof(request, config, jobs, *, journal, state, clock=utcnow):
    wired = _collected()
    return _fleet_recovery.collect_relocation_proof(request, config, jobs, journal=journal, state=state,
                                                    run_records=wired.run_records, git_source=wired.git_source,
                                                    clock=clock)


run_root = _fleet_recovery.run_root
run_records = _collected().run_records
run_process = process_groups.run_process
fleet_recovery = _Facade(_fleet_recovery, checkout_identity=checkout_identity,
                         collect_host_migration_proof=collect_host_migration_proof,
                         collect_recovery_proof=collect_recovery_proof,
                         collect_relocation_proof=collect_relocation_proof)
fleet_cli = unavailable("S10", "adapters.fleet_cli")


def releases_for(store, org):
    return Releases(store, org)


def queue_for(store):
    return ReleaseQueue(store)


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
PRIVATE = {"_emit": "emit", "_deadline": "deadline", "_now": "now"}
SHARED = {"github": ("github",), "hosts": ("hosts",), "canaries": ("canaries",), "verifier": ("verifier",),
          "releases": ("releases",), "queue": ("claims", "settlement"), "observer": ("observer",),
          "enabled": ("enabled",), "clock": ("clock",), "first_activation": ("first_activation",),
          "evaluator_pins": ("evaluator_pins",), "controller_code": ("controller_code",),
          "resume_seconds": ("resume_seconds",), "org": ("org",), "store": ("store",)}


# M7 private methods a case reads or patches AT CLASS LEVEL (`type(delivery)._restart_state`, `HostDelivery._reservation_in`):
# name -> (the owner object's key, its function). A class-level assignment installs on the owner's class, which is
# what M7's `self._restart_state(...)` reached (the objects call their own class); the facade keeps the original too.
CLASS_PRIVATE = {"_restart_state": ("recovery", Recovery._restart_state),
                 "_reservation_in": (None, staticmethod(reservation_in))}


class _Facade(type):
    def __setattr__(cls, name, value):
        super().__setattr__(name, value)
        if name in CLASS_PRIVATE and CLASS_PRIVATE[name][0] is not None:
            setattr(dict(OBJECTS)[CLASS_PRIVATE[name][0]], name, value)


class HostDelivery(metaclass=_Facade):
    _restart_state = CLASS_PRIVATE["_restart_state"][1]
    _reservation_in = CLASS_PRIVATE["_reservation_in"][1]

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
        if name in PRIVATE:
            return getattr(self.objects["state"], PRIVATE[name])
        if name in ROUTES:
            return getattr(self.objects[ROUTES[name]], name)
        if name in SHARED:
            obj, param = self._holders(name)[0]
            return getattr(obj, param)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in ("_emit", "_now"):
            setattr(self.objects["state"], PRIVATE[name], value)
            return
        holders = self._holders(name) if name in SHARED else []
        if not holders:
            raise AttributeError(name)
        for obj, param in holders:
            setattr(obj, param, value)


# ----- the release runner: the wiring composition passes, its carries as labelled refusals ----------------------
class _Holder:
    """A swappable collaborator: calls go to `value`, which a case installs through its patch target."""

    def __init__(self, value):
        self.value = value

    def __call__(self, *args, **kwargs):
        return self.value(*args, **kwargs)


def _refusal(label):
    def refuse(*args, **kwargs):
        raise AssertionError("M7 shim: " + label)
    return refuse


_PROCESS = _Holder(process_groups.run_process)
_SERVICES = _Holder(_refusal("VerificationServices reached without a case's own double (S8)"))
_REBASE_DEFAULT = _refusal("request_rebase reached without a case's own double (S5)")
_REBASE = _Holder(_REBASE_DEFAULT)
_SUITE = _refusal("ReleaseSuite reached: its owner is S8")
_HOOKS = _refusal("NativeHooks reached: its owner is S10")


def ReleaseRunner(service, git, artifacts, auth, auto_merge=True, fence=None, verification_root=None):
    handler = SimpleNamespace(store=service.store, org=service.org)  # the MessageHandler-shaped `self` of request_rebase
    return release_runner(
        service, git, artifacts, auth, auto_merge, fence, verification_root, runner=_PROCESS, release_suite=_SUITE,
        verification_services=_SERVICES, hooks=_HOOKS,
        request_rebase=lambda task_id, new_base: _REBASE.value(handler, task_id, new_base),
        clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


# The unbound staticmethod the controller cases call on the class.
ReleaseRunner._require_controller_code = _deployment.ReleaseRunner._require_controller_code


class _Rerouted:
    """`deployment` as the M7 cases patched it: the moved module, with the names whose collaborators are injected
    (`run_process`, `VerificationServices`) read from and assigned to their holders."""

    _HOLDERS = {"run_process": _PROCESS, "VerificationServices": _SERVICES}

    def __getattr__(self, name):
        holder = self._HOLDERS.get(name)
        return holder.value if holder is not None else getattr(_deployment, name)

    def __setattr__(self, name, value):
        holder = self._HOLDERS.get(name)
        if holder is not None:
            holder.value = value
        else:
            setattr(_deployment, name, value)


deployment = _Rerouted()


class _RebaseOwner(type):
    def __getattr__(cls, name):
        if name == "request_rebase":
            return _REBASE.value
        raise AttributeError(name)

    def __setattr__(cls, name, value):
        if name != "request_rebase":
            raise AttributeError(name)
        _REBASE.value = value

    def __delattr__(cls, name):  # monkeypatch's undo of a class attribute that was not in the class dict
        if name != "request_rebase":
            raise AttributeError(name)
        _REBASE.value = _REBASE_DEFAULT


class Workflow(metaclass=_RebaseOwner):
    """M7 `Workflow` as the release-runner cases use it: only `request_rebase` is patched on it (the S5 owner)."""


@pytest.fixture
def fake_verification_services(monkeypatch):
    """M7 `tests/conftest.py`: unit release orchestration must not launch real infrastructure."""
    monkeypatch.setattr(deployment, "VerificationServices",
                        lambda *args: nullcontext({"database_url": "postgresql://fixture/isolated",
                                                   "redis_url": "redis://fixture/0"}))


# Helpers of M7 modules whose suites are not ported (S8), copied VERBATIM (labelled; only the imports and the git
# helper's name differ) so the suites that import them run: `verification_fixtures.source_repository` and its `git`
# (tests/verification_fixtures.py:235-266, e38aa722), `test_release_recovery.candidate_runner` (tests/test_release_recovery.py:17-34)
# and `test_release_evaluator_migration.runner_for` / `reviewed_record` (tests/test_release_evaluator_migration.py:226-256).
# None reaches `fake_docker`, `fake_uv` or the real `ReleaseSuite`.
def _fixture_git(root, *argv) -> str:
    return subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True,
                          text=True).stdout.strip()


def source_repository(root: Path, *, failing_candidate: bool = False) -> dict:
    """A real disposable repository: a base with a tiny real suite, and one candidate commit."""
    root.mkdir(parents=True)
    _fixture_git(root, "init", "-q", "-b", "main")
    for key, value in (("core.autocrlf", "false"), ("user.name", "Fixture"),
                       ("user.email", "fixture@localhost")):
        _fixture_git(root, "config", "--local", key, value)
    (root / "tests").mkdir()
    # As in any real candidate repository, the evaluator's own venv is ignored; otherwise the
    # evaluator correctly refuses the workspace as dirty.
    (root / ".gitignore").write_text(".venv/\n__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "fixture-candidate"\nversion = "0"\n',
                                         encoding="utf-8")
    (root / "tests" / "test_fixture.py").write_text("def test_incumbent_fixture():\n    assert True\n",
                                                   encoding="utf-8")
    _fixture_git(root, "add", "-A")
    _fixture_git(root, "commit", "-q", "-m", "base")
    base = _fixture_git(root, "rev-parse", "HEAD")
    (root / "feature.txt").write_text("candidate\n", encoding="utf-8")
    if failing_candidate:
        (root / "tests" / "test_candidate.py").write_text("def test_candidate():\n    assert False\n",
                                                          encoding="utf-8")
    _fixture_git(root, "add", "-A")
    _fixture_git(root, "commit", "-q", "-m", "candidate")
    revision = _fixture_git(root, "rev-parse", "HEAD")
    _fixture_git(root, "checkout", "-q", "--detach", base)
    return {"root": root, "base": base, "revision": revision,
            "tree": _fixture_git(root, "rev-parse", revision + "^{tree}")}


def candidate_runner(tmp_path, store=None, remote=None):
    from test_git_workspace import repository  # the ported module (M7 imported it at module level)
    root = repository(tmp_path)
    # The target repository is part of the captured identity (FA-015), so it is fixed before capture.
    adapter = GitWorkspace(str(root), str(tmp_path / "workspaces"), remote=remote)
    workspace = adapter.prepare("candidate-task")
    (Path(workspace["path"]) / "change.txt").write_text("candidate", encoding="utf-8")
    candidate = adapter.capture(workspace)
    service = Harness(store or MemoryStore(), organization())
    runner = ReleaseRunner(service, adapter, FileArtifacts(tmp_path / "artifacts"), "unused")
    release = runner.releases.propose(candidate, {"checks": ["tests"]})
    for actor in ("lead:improvement", "conductor"):
        runner.releases.review(release["id"], actor, candidate["revision"], True, "fixture:review")
    runner.releases.verify(release["id"], candidate["revision"], release["policy_hash"],
                           {"tests": {"passed": True, "evidence": "fixture:tests"}})
    with service.store.transaction() as tx:
        tx.put("images", release["id"], {"image": "sha256:fixture"})
    return runner, release, root


def runner_for(tmp_path, repo, release, monkeypatch):
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put("releases", release["id"], release)
    service = SimpleNamespace(store=store, org=organization())
    runner = ReleaseRunner(service, GitWorkspace(str(repo["root"]), str(tmp_path / "workspaces")),
                           FileArtifacts(str(tmp_path / "artifacts")), str(tmp_path / "unused-auth"),
                           verification_root=str(tmp_path / "verification"))
    calls = []

    def check(argv, cwd=None, **kwargs):  # labelled: install passes, the incumbent suite "fails"
        calls.append({"argv": [str(a) for a in argv], "cwd": str(cwd)})
        return {"passed": len(calls) == 1, "evidence": "fixture:check-" + str(len(calls))}

    monkeypatch.setattr(runner, "_check", check)
    return runner, calls


def reviewed_record(repo, *, pin=None):
    candidate = {"revision": repo["revision"], "base": repo["base"], "tree": repo["tree"],
                 "author": "worker:implementation"}
    policy = {"checks": ["tests", "cli_start", "cli_file_task"], "revision": repo["base"]}
    record = {"id": "a" * 64, "candidate": candidate, "policy": policy, "status": "reviewed",
              "reviews": [], "checks": {}}
    if pin is not None:
        record["policy"] = {**policy, "revision": pin["evaluator_revision"]}
        record["evaluator_migration"] = {"source_release_id": "b" * 64, "base": repo["base"],
                                         "evidence": "sha256:" + "c" * 64, "approved_by": "conductor",
                                         **pin}
    record["policy_hash"] = digest(record["policy"])
    return record


def attempt_resources(attempt_id):
    return _deployment.attempt_resources(attempt_id, naming=ExecutionContainerNaming())


canary_handoff_script = _deployment.canary_handoff_script
EvaluatorCodeMismatch = _deployment.EvaluatorCodeMismatch
controller_code_revision = _deployment.controller_code_revision


# ----- the managed Fleet runtime, wired as composition wires it ------------------------------------------------
class _Recognizes(type):
    """A wired subclass that also recognizes its unwired base in `isinstance` (`host_ports()` builds the base)."""

    def __instancecheck__(cls, obj):
        base = next(b for b in cls.__mro__[1:] if type(b) is not _Recognizes)
        return isinstance(obj, base)


def _wired(base, **fixed):
    def __init__(self, *args, **kwargs):
        base.__init__(self, *args, **{**fixed, **kwargs})

    return _Recognizes(base.__name__, (base,), {"__init__": __init__})


ManagedFleetTarget = _wired(_managed.ManagedFleetTarget, processes=process_groups.ChokepointProcesses(),
                            configuration=configuration)
SystemdManagedFleetTarget = _wired(_managed.SystemdManagedFleetTarget, processes=process_groups.ChokepointProcesses(),
                                   configuration=configuration, runner=process_groups.run_process)
Materializer = _wired(_managed.Materializer, processes=process_groups.ChokepointProcesses())
host_ports = delivery_hosts.host_ports
controller = unavailable("S10", "adapters.host_delivery.controller (the production coordinator)")
fixture_config, fixture_manifest = _managed_composition.fixture_config, _managed_composition.fixture_manifest
supervise = _managed_composition.supervise
scan, owner_target = _managed.scan, _managed.owner_target
launcher_environment = _managed.launcher_environment
validate_launch_request = _managed.validate_launch_request
FIXTURE_JOBS_FILE, TARGET_FILE = _managed.FIXTURE_JOBS_FILE, _managed.TARGET_FILE
LAUNCH_REQUEST_FILE, SUPERVISOR_JOURNAL = _managed.LAUNCH_REQUEST_FILE, _managed.SUPERVISOR_JOURNAL
checkout_revision, _alive = _adapter.checkout_revision, _adapter._alive
