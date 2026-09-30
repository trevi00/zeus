"""Reference driver: `delivery.canaries` (M7 `adapters/host_delivery.py`: the canaries, the runtime/plan helpers, the
host ports).

The API holds plain M7 objects from `adapters.host_delivery`:
- the file names and limits `DESCRIPTOR_FILE`, `RECEIPT_FILE`, `STATE_FILE`, `WORK_FILE`, `STOP_FILE`, `PAUSE_FILE`,
  `LOCK_DIR`, `RUNTIME_FILE`, `MAX_PLAN_BYTES`, `MAX_STATE_BYTES`, `ENABLED_SETTING`, `TRUE_VALUES`,
  `PROFILE_RESOURCES`, `IMAGE_REVISION_LABEL`, `IMAGE_INSPECT_TIMEOUT`;
- `canary_request_file`, `canary_receipt_file`, `plan_token` (`_plan_token`), `configured_enabled`;
- `read_json` (`_read_json`), `write_json` (`_write_json`), `git_directory` (`_git_directory`), `ref_directories`
  (`_ref_directories`), `checkout_revision`, `runtime_revision`, `loaded_runtime`;
- `effective_worker_image`, `host_settings` (`_host_settings`), `effective_profile_digest`,
  `committed_profile_digest`, `first_activation_facts`;
- `load_plan`, `normalize_checks`, `host_ports`, `systemd_control_dir`;
- `startup_identity_canary`, `collect_monitor_canary`, `owner_qualified_canary`, `canary_checks`.

It also holds the M7 names the cases use:
- `KIND_PROCESS`, `KIND_SCHEDULED_TASK`, `KIND_MANAGED`, `KIND_MANAGED_SYSTEMD`, `KIND_SYSTEMD`, `CANARY_STARTUP`,
  `CANARY_COLLECT`, `CANARY_FLEET`, `CANARY_REQUEST_SCHEMA`, `DESCRIPTOR_SCHEMA`, `PLAN_SCHEMA`, `plan_digest`,
  `descriptor_digest` (`domain.host_delivery`);
- `GitSource` (`adapters.operation_cli`), `MemoryStore` (`adapters.store`), `BUCKET_DESCRIPTORS`
  (`application.host_delivery`) and `host_delivery_facts` (`adapters.monitoring`).

Two seams are the driver's own and named here: `host_settings_with(fn)` and `profile_digest_with_failing_load(error)`
replace `codex_harness.adapters.configuration.settings` and `codex_harness.adapters.worker_profile.load_profile` for one
call and restore them, and `profile_character_limit()` is `worker_profile.MAX_CHARACTERS`. The fixtures of the
`s7_host_targets` Fixture additionally need `PACKAGE_DIR`, `SOURCE_PACKAGE`, `RECEIPT_SCHEMA`, `alive` (`_alive`, the sweep's liveness check) and the target names
below; nothing else reads a clock or an id source (`determinism.install`)."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_host_delivery_helpers  # noqa: E402

import codex_harness  # noqa: E402
from codex_harness.adapters import (  # noqa: E402
    configuration,
    host_delivery,
    monitoring,
    worker_profile,
)
from codex_harness.adapters.operation_cli import GitSource  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import host_delivery as application  # noqa: E402
from codex_harness.domain import host_delivery as domain  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)


def host_settings_with(function):
    saved = configuration.settings
    configuration.settings = function
    try:
        return host_delivery._host_settings()
    finally:
        configuration.settings = saved


def profile_digest_with_failing_load(error):
    def failing(*args, **kwargs):
        raise error

    saved = worker_profile.load_profile
    worker_profile.load_profile = failing
    try:
        return host_delivery.effective_profile_digest()
    finally:
        worker_profile.load_profile = saved


API = SimpleNamespace(
    DESCRIPTOR_FILE=host_delivery.DESCRIPTOR_FILE, RECEIPT_FILE=host_delivery.RECEIPT_FILE,
    STATE_FILE=host_delivery.STATE_FILE, WORK_FILE=host_delivery.WORK_FILE, STOP_FILE=host_delivery.STOP_FILE,
    PAUSE_FILE=host_delivery.PAUSE_FILE, LOCK_DIR=host_delivery.LOCK_DIR, RUNTIME_FILE=host_delivery.RUNTIME_FILE,
    MAX_PLAN_BYTES=host_delivery.MAX_PLAN_BYTES, MAX_STATE_BYTES=host_delivery.MAX_STATE_BYTES,
    ENABLED_SETTING=host_delivery.ENABLED_SETTING, TRUE_VALUES=host_delivery.TRUE_VALUES,
    PROFILE_RESOURCES=host_delivery.PROFILE_RESOURCES, IMAGE_REVISION_LABEL=host_delivery.IMAGE_REVISION_LABEL,
    IMAGE_INSPECT_TIMEOUT=host_delivery.IMAGE_INSPECT_TIMEOUT,
    canary_request_file=host_delivery.canary_request_file, canary_receipt_file=host_delivery.canary_receipt_file,
    plan_token=host_delivery._plan_token, configured_enabled=host_delivery.configured_enabled,
    read_json=host_delivery._read_json, write_json=host_delivery._write_json,
    git_directory=host_delivery._git_directory, ref_directories=host_delivery._ref_directories,
    checkout_revision=host_delivery.checkout_revision, runtime_revision=host_delivery.runtime_revision,
    loaded_runtime=host_delivery.loaded_runtime, effective_worker_image=host_delivery.effective_worker_image,
    host_settings=host_delivery._host_settings, effective_profile_digest=host_delivery.effective_profile_digest,
    committed_profile_digest=host_delivery.committed_profile_digest,
    first_activation_facts=host_delivery.first_activation_facts, load_plan=host_delivery.load_plan,
    normalize_checks=host_delivery.normalize_checks, host_ports=host_delivery.host_ports,
    systemd_control_dir=host_delivery.systemd_control_dir,
    startup_identity_canary=host_delivery.startup_identity_canary,
    collect_monitor_canary=host_delivery.collect_monitor_canary,
    owner_qualified_canary=host_delivery.owner_qualified_canary, canary_checks=host_delivery.canary_checks,
    KIND_PROCESS=domain.KIND_PROCESS, KIND_SCHEDULED_TASK=domain.KIND_SCHEDULED_TASK, KIND_MANAGED=domain.KIND_MANAGED,
    KIND_MANAGED_SYSTEMD=domain.KIND_MANAGED_SYSTEMD, KIND_SYSTEMD=domain.KIND_SYSTEMD,
    CANARY_STARTUP=domain.CANARY_STARTUP, CANARY_COLLECT=domain.CANARY_COLLECT, CANARY_FLEET=domain.CANARY_FLEET,
    CANARY_REQUEST_SCHEMA=domain.CANARY_REQUEST_SCHEMA, DESCRIPTOR_SCHEMA=domain.DESCRIPTOR_SCHEMA,
    RECEIPT_SCHEMA=domain.RECEIPT_SCHEMA, PLAN_SCHEMA=domain.PLAN_SCHEMA, plan_digest=domain.plan_digest,
    descriptor_digest=domain.descriptor_digest, GitSource=GitSource, MemoryStore=MemoryStore,
    BUCKET_DESCRIPTORS=application.BUCKET_DESCRIPTORS, host_delivery_facts=monitoring.host_delivery_facts,
    host_settings_with=host_settings_with, profile_digest_with_failing_load=profile_digest_with_failing_load,
    profile_character_limit=lambda: worker_profile.MAX_CHARACTERS,
    PACKAGE_DIR=Path(codex_harness.__file__).resolve().parent,
    SOURCE_PACKAGE=Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve() / "src" / "codex_harness",
    alive=host_delivery._alive, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "delivery.canaries", s7_host_delivery_helpers.run(API))
