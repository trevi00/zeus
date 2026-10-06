"""Target driver: `delivery.canaries` on the target tree (S7 pilot 45).

The API holds the moved `delivery.adapters.host_delivery` helpers with the V6 injections closed over composition's
wiring, exactly as the M7 defaults resolved them (DESIGN-s7 adapters-move §8-§9):
- `first_activation_facts` supplies `run=process_groups.run_process`, a `host_os` `GitSource` over the lane repository
  when no source is given, and `context.adapters.worker_profile`; `host=None` reads the host settings;
- `effective_worker_image(config=None)` reads `composition.configuration.settings` (a malformed configuration is `{}`);
- `effective_profile_digest` / `committed_profile_digest` take the worker profile adapter;
- `load_plan` reads blobs through `intake.adapters.backlog_blobs.read_blob`;
- `collect_monitor_canary` / `canary_checks` default `facts` to the delivery status projection over the store (M7
  `monitoring.host_delivery_facts` is `HostDelivery(store).status()`), built as the target delivery families build it;
- `host_ports` is `composition.delivery_hosts.host_ports`.
`advance` is a no-op: this driver installs no determinism."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import codex_harness  # noqa: E402
import s7_delivery_composition  # noqa: E402
import s7_host_delivery_helpers  # noqa: E402
from codex_harness.composition import configuration, delivery_hosts  # noqa: E402
from codex_harness.context.adapters import worker_profile  # noqa: E402
from codex_harness.delivery.adapters import host_delivery  # noqa: E402
from codex_harness.delivery.application.host_delivery import state as delivery_state  # noqa: E402
from codex_harness.delivery.domain import host_delivery as domain  # noqa: E402
from codex_harness.host_os.adapters import process_groups  # noqa: E402
from codex_harness.host_os.adapters.git_source import GitSource  # noqa: E402
from codex_harness.intake.adapters import backlog_blobs  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402


def host_settings():
    try:
        return configuration.settings()
    except Exception:
        # M7 `_host_settings`: a malformed host configuration invents none.
        return {}


def host_settings_with(function):
    saved = configuration.settings
    configuration.settings = function
    try:
        return host_settings()
    finally:
        configuration.settings = saved


def profile_digest_with_failing_load(error):
    def failing(*args, **kwargs):
        raise error

    saved = worker_profile.load_profile
    worker_profile.load_profile = failing
    try:
        return host_delivery.effective_profile_digest(worker_profile)
    finally:
        worker_profile.load_profile = saved


def effective_worker_image(config=None):
    return host_delivery.effective_worker_image(host_settings() if config is None else config)


def first_activation_facts(lane, host, revision, *, run=None, source=None):
    host = host_settings() if host is None else host
    # M7 built the git source only after the docker and revision checks, and only when none was given.
    return host_delivery.first_activation_facts(
        lane, host, revision, run=run or process_groups.run_process,
        source=_LaneSource(lane) if source is None else source, profiles=worker_profile)


class _LaneSource:
    """`GitSource(lane["repository"])`, built on first use as M7's default was."""

    def __init__(self, lane):
        self.lane = lane

    def blob(self, revision, path):
        return GitSource(self.lane["repository"]).blob(revision, path)


def delivery_facts(store):
    return s7_delivery_composition.HostDelivery(store, None).status()


def collect_monitor_canary(target, descriptor, startup, *, store=None, facts=None):
    return host_delivery.collect_monitor_canary(target, descriptor, startup, store=store,
                                                facts=facts or delivery_facts)


def canary_checks(store=None, *, facts=None):
    return host_delivery.canary_checks(store, facts=facts or delivery_facts)


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
    loaded_runtime=host_delivery.loaded_runtime, effective_worker_image=effective_worker_image,
    host_settings=host_settings,
    effective_profile_digest=lambda: host_delivery.effective_profile_digest(worker_profile),
    committed_profile_digest=lambda source, revision: host_delivery.committed_profile_digest(
        source, revision, worker_profile),
    first_activation_facts=first_activation_facts,
    load_plan=lambda source, revision, path: host_delivery.load_plan(
        source, revision, path, read_blob=backlog_blobs.read_blob),
    normalize_checks=host_delivery.normalize_checks, host_ports=delivery_hosts.host_ports,
    systemd_control_dir=host_delivery.systemd_control_dir,
    startup_identity_canary=host_delivery.startup_identity_canary,
    collect_monitor_canary=collect_monitor_canary,
    owner_qualified_canary=host_delivery.owner_qualified_canary, canary_checks=canary_checks,
    KIND_PROCESS=domain.KIND_PROCESS, KIND_SCHEDULED_TASK=domain.KIND_SCHEDULED_TASK, KIND_MANAGED=domain.KIND_MANAGED,
    KIND_MANAGED_SYSTEMD=domain.KIND_MANAGED_SYSTEMD, KIND_SYSTEMD=domain.KIND_SYSTEMD,
    CANARY_STARTUP=domain.CANARY_STARTUP, CANARY_COLLECT=domain.CANARY_COLLECT, CANARY_FLEET=domain.CANARY_FLEET,
    CANARY_REQUEST_SCHEMA=domain.CANARY_REQUEST_SCHEMA, DESCRIPTOR_SCHEMA=domain.DESCRIPTOR_SCHEMA,
    RECEIPT_SCHEMA=domain.RECEIPT_SCHEMA, PLAN_SCHEMA=domain.PLAN_SCHEMA, plan_digest=domain.plan_digest,
    descriptor_digest=domain.descriptor_digest, GitSource=GitSource, MemoryStore=MemoryStore,
    BUCKET_DESCRIPTORS=delivery_state.BUCKET_DESCRIPTORS, host_delivery_facts=delivery_facts,
    host_settings_with=host_settings_with, profile_digest_with_failing_load=profile_digest_with_failing_load,
    profile_character_limit=lambda: worker_profile.MAX_CHARACTERS,
    PACKAGE_DIR=Path(codex_harness.__file__).resolve().parent,
    SOURCE_PACKAGE=Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve() / "src" / "codex_harness",
    alive=host_delivery._alive, advance=lambda seconds: None)

if __name__ == "__main__":
    driver.finish("target", "delivery.canaries", s7_host_delivery_helpers.run(API))
