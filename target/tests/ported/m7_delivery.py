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
  target homes. `Fleet` is `m7_coordination.Fleet`.
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
- `unavailable(slice_, name)` is `m7_coordination.unavailable`: a name whose owner is in a later slice imports as a
  placeholder that raises on use, and only tests skipped whole (with the owning slice) name it.
"""

from __future__ import annotations

import inspect

import pytest
from conftest import ATTESTED
from m7_coordination import Fleet, unavailable  # noqa: F401

from codex_harness.composition import configuration
from codex_harness.context.adapters import worker_profile
from codex_harness.coordination.application import execution_fence
from codex_harness.coordination.application.events import EventJournal
from codex_harness.delivery.adapters import host_delivery as _adapter
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
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters.git_source import GitSource  # noqa: F401
from codex_harness.host_os.adapters.git_workspace import (  # noqa: F401
    GitCommandError,
    GitWorkspace,
    MergeRefused,
)
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
from codex_harness.routing.adapters.organization_source import (
    packaged_organization as organization,  # noqa: F401
)
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: F401
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: F401

aliases, read_env = configuration.aliases, configuration.read_env


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


def delivery_facts(store):
    """M7 `monitoring.host_delivery_facts`: the status projection of a HostDelivery over the store."""
    return HostDelivery(store, None).status()


def collect_monitor_canary(target, descriptor, startup, *, store=None, facts=None):
    return _adapter.collect_monitor_canary(target, descriptor, startup, store=store, facts=facts or delivery_facts)


def canary_checks(store=None, *, facts=None):
    return _adapter.canary_checks(store, facts=facts or delivery_facts)


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


