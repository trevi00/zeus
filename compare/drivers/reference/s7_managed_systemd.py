"""Reference driver: `delivery.managed_systemd` (M7 `SystemdManagedFleetTarget`, `supervise`, the unit binding).

The API holds plain M7 objects from `adapters.managed_runtime`:
- `SystemdManagedFleetTarget`, `ManagedFleetTarget`, `supervise`, `owner_target`, `validate_launch_request`,
  `launcher_environment`, `runtime_image`;
- the constants `LAUNCH_REQUEST_FILE`, `SUPERVISOR_JOURNAL`, `TARGET_FILE`, `FIXTURE_JOBS_FILE`,
  `LAUNCH_REQUEST_SCHEMA`, `MODULE` (the module the unit's ExecStart imports by name) and `EXIT_REFUSED`;
- `fixture_config` (the fixture workload's config, for the labelled Fleet authority).

It holds these M7 `adapters.host_delivery` names: `host_ports`, `owner_qualified_canary`,
`startup_identity_canary`, `effective_profile_digest`, `alive` (the module's `_alive`) and the file names
`DESCRIPTOR_FILE`, `RECEIPT_FILE`, `STATE_FILE`, `PAUSE_FILE` and `STOP_FILE`.

It holds the coordinator doubles' M7 dependencies, as `tests/test_managed_systemd.py` builds them (the labelled
`SerialStore`, `FakeGitHub`, `reviewed_release`, `plan_document` and `pin` are `s7_delivery`'s): `HostDelivery`
(`application.host_delivery`, wrapped as `HostDelivery(store, org, **ports)`), `BUCKET_INTENTS`, `organization`
(`bootstrap`), `releases(store)` = `Releases(store, organization())`, `MemoryStore` (`adapters.store`),
`MergeRefused` (`adapters.git`) and `ContractError` (`domain.model`).

It holds these M7 `domain.host_delivery` names: `KIND_MANAGED`, `KIND_MANAGED_SYSTEMD`, `MANAGED_SYSTEMD_UNIT`,
`ACTIVE`, `ROLLED_BACK`, `CANARY_STARTUP`, `CANARY_FLEET`, `PLAN_SCHEMA`, `REGISTRY_SCHEMA`, `DESCRIPTOR_SCHEMA`,
`DeliveryRefused`, `descriptor_digest`, `managed_runtime_root`, `validate_targets`; from `domain.managed_runtime`,
`manifest_digest`, `HEARTBEAT_SCHEMA` and `EnvironmentUnqualified`; and the Fleet authority of the gate: `Fleet`
(`application.fleet`).

`SOURCE_PACKAGE` is the SOURCE archive's `src/codex_harness` (the fixture source repository copies it) and
`PACKAGE_DIR` is the directory of the imported `codex_harness` package. `sync_clock()` puts the driver's fake clock
on the real wall time, because `determinism.install` freezes it and the live children write real heartbeats;
`reset_ids()` restarts the id source (`s7_managed_runtime.SpreadIds`). The module reads no other clock and no other
id source."""

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
import s7_managed_systemd  # noqa: E402

import codex_harness  # noqa: E402
from codex_harness.adapters import host_delivery, managed_runtime  # noqa: E402
from codex_harness.adapters.git import MergeRefused  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import fleet as application_fleet  # noqa: E402
from codex_harness.application import host_delivery as application  # noqa: E402
from codex_harness.application.releases import Releases  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import host_delivery as domain  # noqa: E402
from codex_harness.domain import managed_runtime as domain_managed  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), s7_managed_runtime.SpreadIds()
determinism.install(CLOCK, IDS)


def sync_clock():
    CLOCK.current = determinism.ORIGINAL_DATETIME.now(timezone.utc)


API = SimpleNamespace(
    SystemdManagedFleetTarget=managed_runtime.SystemdManagedFleetTarget,
    ManagedFleetTarget=managed_runtime.ManagedFleetTarget, supervise=managed_runtime.supervise,
    owner_target=managed_runtime.owner_target, validate_launch_request=managed_runtime.validate_launch_request,
    launcher_environment=managed_runtime.launcher_environment, runtime_image=managed_runtime.runtime_image,
    fixture_config=managed_runtime.fixture_config, LAUNCH_REQUEST_FILE=managed_runtime.LAUNCH_REQUEST_FILE,
    SUPERVISOR_JOURNAL=managed_runtime.SUPERVISOR_JOURNAL, TARGET_FILE=managed_runtime.TARGET_FILE,
    FIXTURE_JOBS_FILE=managed_runtime.FIXTURE_JOBS_FILE,
    LAUNCH_REQUEST_SCHEMA=managed_runtime.LAUNCH_REQUEST_SCHEMA, MODULE=managed_runtime.MODULE,
    EXIT_REFUSED=managed_runtime.EXIT_REFUSED,
    host_ports=host_delivery.host_ports, owner_qualified_canary=host_delivery.owner_qualified_canary,
    startup_identity_canary=host_delivery.startup_identity_canary,
    effective_profile_digest=host_delivery.effective_profile_digest, alive=host_delivery._alive,
    DESCRIPTOR_FILE=host_delivery.DESCRIPTOR_FILE, RECEIPT_FILE=host_delivery.RECEIPT_FILE,
    STATE_FILE=host_delivery.STATE_FILE, PAUSE_FILE=host_delivery.PAUSE_FILE, STOP_FILE=host_delivery.STOP_FILE,
    HostDelivery=lambda store, org, **ports: application.HostDelivery(store, org, **ports),
    BUCKET_INTENTS=application.BUCKET_INTENTS, organization=organization,
    releases=lambda store: Releases(store, organization()), MemoryStore=MemoryStore, MergeRefused=MergeRefused,
    ContractError=ContractError, KIND_MANAGED=domain.KIND_MANAGED, KIND_MANAGED_SYSTEMD=domain.KIND_MANAGED_SYSTEMD,
    MANAGED_SYSTEMD_UNIT=domain.MANAGED_SYSTEMD_UNIT, ACTIVE=domain.ACTIVE, ROLLED_BACK=domain.ROLLED_BACK,
    CANARY_STARTUP=domain.CANARY_STARTUP, CANARY_FLEET=domain.CANARY_FLEET, PLAN_SCHEMA=domain.PLAN_SCHEMA,
    REGISTRY_SCHEMA=domain.REGISTRY_SCHEMA, DESCRIPTOR_SCHEMA=domain.DESCRIPTOR_SCHEMA,
    DeliveryRefused=domain.DeliveryRefused, descriptor_digest=domain.descriptor_digest,
    managed_runtime_root=domain.managed_runtime_root, validate_targets=domain.validate_targets,
    manifest_digest=domain_managed.manifest_digest, HEARTBEAT_SCHEMA=domain_managed.HEARTBEAT_SCHEMA,
    EnvironmentUnqualified=domain_managed.EnvironmentUnqualified, Fleet=application_fleet.Fleet,
    SOURCE_PACKAGE=Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve() / "src" / "codex_harness",
    PACKAGE_DIR=Path(codex_harness.__file__).resolve().parent, sync_clock=sync_clock, reset_ids=IDS.reset)

if __name__ == "__main__":
    driver.finish("reference", "delivery.managed_systemd", s7_managed_systemd.run(API))
