"""Target wiring of the S7 managed families (harness only, never shipped).

The reference API holds plain M7 objects; the moved adapters take their collaborators (DESIGN-s7 adapters-move §9.4), so
each class the cases construct is a thin wired subclass that closes over composition's wiring (`ChokepointProcesses()`,
`run_process`, `composition.configuration`) and whose class also recognizes its unwired base in `isinstance` (the cases
test the type `host_ports` returns). `Fleet` composes the S5 target objects (`s5_fleet_composition.FleetFacade`) with
their own defaults. Names come from their target homes."""

from pathlib import Path

import codex_harness
import s5_fleet_composition
from codex_harness.composition import configuration, delivery_hosts
from codex_harness.composition import managed_runtime as composition
from codex_harness.coordination.application.fleet import state as fleet_state
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.domain import fleet as domain_fleet
from codex_harness.delivery.adapters import host_delivery, managed_runtime
from codex_harness.delivery.domain import host_delivery as domain
from codex_harness.delivery.domain import managed_runtime as domain_managed
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses, run_process
from codex_harness.storage.adapters.memory_store import MemoryStore


class _Recognizes(type):
    def __instancecheck__(cls, obj):
        base = next(b for b in cls.__mro__[1:] if type(b) is not _Recognizes)
        return isinstance(obj, base)


def _wired(base, **fixed):
    def __init__(self, *args, **kwargs):
        base.__init__(self, *args, **{**fixed, **kwargs})

    return _Recognizes(base.__name__, (base,), {"__init__": __init__})


ManagedFleetTarget = _wired(managed_runtime.ManagedFleetTarget, processes=ChokepointProcesses(),
                            configuration=configuration)
SystemdManagedFleetTarget = _wired(managed_runtime.SystemdManagedFleetTarget, processes=ChokepointProcesses(),
                                   configuration=configuration, runner=run_process)
Materializer = _wired(managed_runtime.Materializer, processes=ChokepointProcesses())
FixtureLauncher = _wired(composition.FixtureLauncher, processes=ChokepointProcesses())
_CLOCK, _TOKEN = FleetRegistry.__init__.__defaults__


def Fleet(store):
    return s5_fleet_composition.FleetFacade(store, _CLOCK, _TOKEN)


def runtime_image(target, environment):
    return managed_runtime.runtime_image(target, environment, configuration)


def package_dir():
    return Path(codex_harness.__file__).resolve().parent


def names() -> dict:
    return dict(
        ManagedFleetTarget=ManagedFleetTarget, SystemdManagedFleetTarget=SystemdManagedFleetTarget,
        Materializer=Materializer, FixtureLauncher=FixtureLauncher, Fleet=Fleet, runtime_image=runtime_image,
        scan=managed_runtime.scan, owner_target=managed_runtime.owner_target,
        gate_refusal=managed_runtime.gate_refusal, validate_launch_request=managed_runtime.validate_launch_request,
        launcher_environment=managed_runtime.launcher_environment, supervise=composition.supervise,
        RuntimeControl=managed_runtime.RuntimeControl, fixture_config=composition.fixture_config,
        fixture_manifest=composition.fixture_manifest, run_fixture=composition.run_fixture, entry=composition.entry,
        launch=composition.launch, FIXTURE_JOBS_FILE=managed_runtime.FIXTURE_JOBS_FILE,
        TARGET_FILE=managed_runtime.TARGET_FILE, LAUNCHER_JOURNAL=managed_runtime.LAUNCHER_JOURNAL,
        MODULE=managed_runtime.MODULE, EXIT_REFUSED=managed_runtime.EXIT_REFUSED,
        LAUNCH_REQUEST_SCHEMA=managed_runtime.LAUNCH_REQUEST_SCHEMA,
        LAUNCH_REQUEST_FILE=managed_runtime.LAUNCH_REQUEST_FILE,
        SUPERVISOR_JOURNAL=managed_runtime.SUPERVISOR_JOURNAL,
        DESCRIPTOR_FILE=host_delivery.DESCRIPTOR_FILE, RECEIPT_FILE=host_delivery.RECEIPT_FILE,
        STATE_FILE=host_delivery.STATE_FILE, PAUSE_FILE=host_delivery.PAUSE_FILE, STOP_FILE=host_delivery.STOP_FILE,
        alive=host_delivery._alive, checkout_revision=host_delivery.checkout_revision,
        runtime_revision=host_delivery.runtime_revision, host_ports=delivery_hosts.host_ports,
        DESCRIPTOR_SCHEMA=domain.DESCRIPTOR_SCHEMA, RECEIPT_SCHEMA=domain.RECEIPT_SCHEMA,
        REGISTRY_SCHEMA=domain.REGISTRY_SCHEMA, KIND_MANAGED=domain.KIND_MANAGED,
        KIND_MANAGED_SYSTEMD=domain.KIND_MANAGED_SYSTEMD, MANAGED_SYSTEMD_UNIT=domain.MANAGED_SYSTEMD_UNIT,
        DeliveryRefused=domain.DeliveryRefused, consumption_verdict=domain.consumption_verdict,
        descriptor_digest=domain.descriptor_digest, managed_runtime_root=domain.managed_runtime_root,
        same_path=domain.same_path, within_path=domain.within_path, validate_targets=domain.validate_targets,
        ACTIVE=domain.ACTIVE, ROLLED_BACK=domain.ROLLED_BACK, CANARY_STARTUP=domain.CANARY_STARTUP,
        CANARY_FLEET=domain.CANARY_FLEET, PLAN_SCHEMA=domain.PLAN_SCHEMA,
        HEARTBEAT_SCHEMA=domain_managed.HEARTBEAT_SCHEMA, LISTING_FILE=domain_managed.LISTING_FILE,
        MANIFEST_FILE=domain_managed.MANIFEST_FILE, STAGE_PREFIX=domain_managed.STAGE_PREFIX,
        EnvironmentUnqualified=domain_managed.EnvironmentUnqualified,
        check_runtime_path=domain_managed.check_runtime_path, validate_manifest=domain_managed.validate_manifest,
        manifest_digest=domain_managed.manifest_digest, work_verdict=domain_managed.work_verdict,
        ACTIVATION_HOLD=fleet_state.ACTIVATION_HOLD, BUCKET_CONTROL=fleet_state.BUCKET_CONTROL,
        BUCKET_JOBS=fleet_state.BUCKET_JOBS, BUCKET_UNITS=fleet_state.BUCKET_UNITS,
        CONTROL_KEY=fleet_state.CONTROL_KEY, FleetRefused=domain_fleet.FleetRefused,
        UNIT_CONDUCTOR=domain_fleet.UNIT_CONDUCTOR, MemoryStore=MemoryStore,
        PACKAGE_DIR=package_dir())

