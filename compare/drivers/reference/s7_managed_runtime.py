"""Reference driver: `delivery.managed_runtime` (M7 `Materializer`, `ManagedFleetTarget`, the fixture workload).

The API holds plain M7 objects from `adapters.managed_runtime`:
- `ManagedFleetTarget`, `Materializer`, `scan`, `owner_target`, `gate_refusal`, `validate_launch_request`,
  `runtime_image`;
- `RuntimeControl`, `FixtureLauncher`, `fixture_config`, `fixture_manifest`, `run_fixture`, `entry` and `launch`
  (the fixture workload and the in-process entry points);
- the constants `FIXTURE_JOBS_FILE`, `TARGET_FILE`, `LAUNCHER_JOURNAL`, `MODULE`, `EXIT_REFUSED` and
  `LAUNCH_REQUEST_SCHEMA`.

It holds these M7 `adapters.host_delivery` names the cases use: the file names `DESCRIPTOR_FILE`, `RECEIPT_FILE`,
`STATE_FILE`, `PAUSE_FILE` and `STOP_FILE`; `alive` (the module's `_alive`), `checkout_revision`,
`runtime_revision`, `host_ports` and `effective_profile_digest`.

It holds these M7 domain names: from `domain.host_delivery`, `DESCRIPTOR_SCHEMA`, `RECEIPT_SCHEMA`,
`REGISTRY_SCHEMA`, `KIND_MANAGED`, `DeliveryRefused`, `consumption_verdict`, `descriptor_digest`,
`managed_runtime_root`, `same_path`, `within_path` and `validate_targets`; from `domain.managed_runtime`,
`HEARTBEAT_SCHEMA`, `LISTING_FILE`, `MANIFEST_FILE`, `STAGE_PREFIX`, `EnvironmentUnqualified`, `check_runtime_path`,
`validate_manifest` and `work_verdict`.

It holds the Fleet authority of the gate: `Fleet`, `ACTIVATION_HOLD`, `BUCKET_CONTROL`, `BUCKET_JOBS`,
`BUCKET_UNITS` and `CONTROL_KEY` (`application.fleet`), `FleetRefused` and `UNIT_CONDUCTOR` (`domain.fleet`) and
`MemoryStore` (`adapters.store`).

`SOURCE_PACKAGE` is the SOURCE archive's `src/codex_harness` (the fixture source repository copies it, so the sealed
runtimes are identical inputs on both sides) and `PACKAGE_DIR` is the directory of the imported `codex_harness`
package (the controller-side code the trusted launcher runs). `sync_clock()` puts the driver's fake clock on the real
wall time, because `determinism.install` freezes it and the live children write real heartbeats; `reset_ids()`
restarts the id source, whose `uuid4` (`s7_managed_runtime.SpreadIds`) draws the seal stage names. The module reads
no other clock and no other id source."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from datetime import timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_managed_runtime  # noqa: E402

import codex_harness  # noqa: E402
from codex_harness.adapters import host_delivery, managed_runtime  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import fleet as application_fleet  # noqa: E402
from codex_harness.domain import fleet as domain_fleet  # noqa: E402
from codex_harness.domain import host_delivery as domain  # noqa: E402
from codex_harness.domain import managed_runtime as domain_managed  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), s7_managed_runtime.SpreadIds()
determinism.install(CLOCK, IDS)


def sync_clock():
    CLOCK.current = determinism.ORIGINAL_DATETIME.now(timezone.utc)


API = SimpleNamespace(
    ManagedFleetTarget=managed_runtime.ManagedFleetTarget, Materializer=managed_runtime.Materializer,
    scan=managed_runtime.scan, owner_target=managed_runtime.owner_target, gate_refusal=managed_runtime.gate_refusal,
    validate_launch_request=managed_runtime.validate_launch_request, runtime_image=managed_runtime.runtime_image,
    RuntimeControl=managed_runtime.RuntimeControl, FixtureLauncher=managed_runtime.FixtureLauncher,
    fixture_config=managed_runtime.fixture_config, fixture_manifest=managed_runtime.fixture_manifest,
    run_fixture=managed_runtime.run_fixture, entry=managed_runtime.entry, launch=managed_runtime.launch,
    FIXTURE_JOBS_FILE=managed_runtime.FIXTURE_JOBS_FILE, TARGET_FILE=managed_runtime.TARGET_FILE,
    LAUNCHER_JOURNAL=managed_runtime.LAUNCHER_JOURNAL, MODULE=managed_runtime.MODULE,
    EXIT_REFUSED=managed_runtime.EXIT_REFUSED, LAUNCH_REQUEST_SCHEMA=managed_runtime.LAUNCH_REQUEST_SCHEMA,
    DESCRIPTOR_FILE=host_delivery.DESCRIPTOR_FILE, RECEIPT_FILE=host_delivery.RECEIPT_FILE,
    STATE_FILE=host_delivery.STATE_FILE, PAUSE_FILE=host_delivery.PAUSE_FILE, STOP_FILE=host_delivery.STOP_FILE,
    alive=host_delivery._alive, checkout_revision=host_delivery.checkout_revision,
    runtime_revision=host_delivery.runtime_revision, host_ports=host_delivery.host_ports,
    effective_profile_digest=host_delivery.effective_profile_digest,
    DESCRIPTOR_SCHEMA=domain.DESCRIPTOR_SCHEMA, RECEIPT_SCHEMA=domain.RECEIPT_SCHEMA,
    REGISTRY_SCHEMA=domain.REGISTRY_SCHEMA, KIND_MANAGED=domain.KIND_MANAGED, DeliveryRefused=domain.DeliveryRefused,
    consumption_verdict=domain.consumption_verdict, descriptor_digest=domain.descriptor_digest,
    managed_runtime_root=domain.managed_runtime_root, same_path=domain.same_path, within_path=domain.within_path,
    validate_targets=domain.validate_targets, HEARTBEAT_SCHEMA=domain_managed.HEARTBEAT_SCHEMA,
    LISTING_FILE=domain_managed.LISTING_FILE, MANIFEST_FILE=domain_managed.MANIFEST_FILE,
    STAGE_PREFIX=domain_managed.STAGE_PREFIX, EnvironmentUnqualified=domain_managed.EnvironmentUnqualified,
    check_runtime_path=domain_managed.check_runtime_path, validate_manifest=domain_managed.validate_manifest,
    work_verdict=domain_managed.work_verdict, Fleet=application_fleet.Fleet,
    ACTIVATION_HOLD=application_fleet.ACTIVATION_HOLD, BUCKET_CONTROL=application_fleet.BUCKET_CONTROL,
    BUCKET_JOBS=application_fleet.BUCKET_JOBS, BUCKET_UNITS=application_fleet.BUCKET_UNITS,
    CONTROL_KEY=application_fleet.CONTROL_KEY, FleetRefused=domain_fleet.FleetRefused,
    UNIT_CONDUCTOR=domain_fleet.UNIT_CONDUCTOR, MemoryStore=MemoryStore,
    SOURCE_PACKAGE=Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve() / "src" / "codex_harness",
    PACKAGE_DIR=Path(codex_harness.__file__).resolve().parent, sync_clock=sync_clock, reset_ids=IDS.reset)

if __name__ == "__main__":
    driver.finish("reference", "delivery.managed_runtime", s7_managed_runtime.run(API))
