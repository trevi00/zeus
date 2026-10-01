"""Target driver: `delivery.host_migration_transfer` on the target tree (S7 pilot 44).

The API holds the moved `delivery.adapters.host_migration` names with the V6 injections closed over the wiring a
composition would pass (DESIGN-s7 adapters-move §9.4), so the common module runs unchanged:
- `run_canonical` and `pg_compare_schema` default their required `runner` to the chokepoint `run` (M7's default was
  `subprocess.run`); `recovery_preconditions` and `switch_effect` default theirs to `process_groups.run_process` (M7's
  default was `run_process`); a runner the case supplies wins, exactly as in M7. `SystemdHostTarget` is the moved class
  (every case passes its `runner`).
- `canonical_module` is LABELLED HARNESS CODE: M7's body verbatim, calling the TARGET adapter's `canonical_tool()` so a
  patched `PACKAGE_DIR` governs it. S10 carry: the production provider is wired by the operator CLI process root
  (`aibox_data` is external tooling that no product layer may import).
- `trace()`, `os_replace(factory)` and `patched(**attrs)` act on the target adapter module, as the reference hooks act on
  M7's. `patched` wraps a patched `recovery_preconditions` that takes two positional arguments into one that accepts and
  ignores the `runner`/`proc` keywords the moved `switch_effect` passes to its default observer.
- `checkout(path)` patches `PACKAGE_DIR` to `<path>/src/codex_harness` (the reference makes `adapter.codex_harness` a
  stand-in with that `__file__`), so `canonical_tool` resolves `<path>/scripts/aibox_data`.
- `launcher` is the unchanged deploy/aibox launcher module, loaded from the SOURCE tree as the reference loads it.
- `main` (the S10 CLI) is not part of the target api: its cases are `delivery.host_migration_cli`.

The clock seam (as in pilot 43): the reference freezes time with `determinism.install`, so the digests of the fence
document (`at`), the controller state (`started_at`) and the recovery receipts embed that instant. This driver installs no
determinism; for the run it substitutes the imported `_utcnow` of each target adapter module that stamps those files
(`delivery.adapters.host_migration` and `delivery.adapters.host_delivery`) with the SAME `determinism.FakeClock` the
reference installs (a module-attribute substitution, restored afterwards)."""

import contextlib
from datetime import timezone
import importlib
import importlib.util
import inspect
import os
import stat
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402

import s7_host_migration_transfer  # noqa: E402
from codex_harness.delivery.adapters import host_delivery, host_migration as adapter  # noqa: E402
from codex_harness.delivery.application import host_migration as application  # noqa: E402
from codex_harness.delivery.domain import host_migration as policy  # noqa: E402
from codex_harness.delivery.domain.host_delivery import (  # noqa: E402
    DESCRIPTOR_SCHEMA,
    KIND_SYSTEMD,
    descriptor_digest,
    validate_targets,
)
from codex_harness.host_os.adapters import process_groups  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

SOURCE_ROOT = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve()
TOOL_ROOT = Path(os.environ["ZEUS_REBUILD_TARGET_SRC"]).resolve().parent
CLOCK = determinism.FakeClock()
LAUNCHER_PATH = SOURCE_ROOT / "deploy" / "aibox" / "zeus_aibox_service.py"
_spec = importlib.util.spec_from_file_location("zeus_aibox_service_transfer", LAUNCHER_PATH)
_launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_launcher)


def run_canonical(argv, *, runner=process_groups.run, **kwargs):
    return adapter.run_canonical(argv, runner=runner, **kwargs)


def pg_compare_schema(*args, runner=process_groups.run, **kwargs):
    return adapter.pg_compare_schema(*args, runner=runner, **kwargs)


def recovery_preconditions(control_dir, managed_state_dir, *, runner=process_groups.run_process, **kwargs):
    return adapter.recovery_preconditions(control_dir, managed_state_dir, runner=runner, **kwargs)


def switch_effect(control_dir, releases_dir, managed_state_dir, *, runner=process_groups.run_process, **kwargs):
    return adapter.switch_effect(control_dir, releases_dir, managed_state_dir, runner=runner, **kwargs)


def canonical_module(name: str):
    """In-process access to a canonical helper (M7 `canonical_module`, verbatim; LABELLED HARNESS CODE).

    S10 carry: the production provider is wired by the operator CLI process root."""
    scripts = str(adapter.canonical_tool().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module("aibox_data." + name)


@contextlib.contextmanager
def trace():
    events = []
    real_write, real_replace = adapter.write_activation, adapter._replace_current
    real_directory, real_fsync = adapter._fsync_directory, os.fsync

    def fsync(descriptor):
        events.append("os.fsync:dir" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "os.fsync:file")
        return real_fsync(descriptor)
    adapter.write_activation = lambda *a, **k: events.append("receipt") or real_write(*a, **k)
    adapter._replace_current = lambda *a, **k: events.append("current") or real_replace(*a, **k)
    adapter._fsync_directory = lambda path: events.append("fsync:" + Path(path).name) or real_directory(path)
    os.fsync = fsync
    try:
        yield events
    finally:
        adapter.write_activation, adapter._replace_current = real_write, real_replace
        adapter._fsync_directory, os.fsync = real_directory, real_fsync


@contextlib.contextmanager
def os_replace(factory):
    real = adapter.os.replace
    adapter.os.replace = factory(real)
    try:
        yield
    finally:
        adapter.os.replace = real


def _accepting_runner(function):
    """A patched two-argument `recovery_preconditions` accepts and ignores the `runner`/`proc` keywords."""
    positional = [p for p in inspect.signature(function).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if len(positional) != 2 or any(p.kind is p.VAR_KEYWORD for p in inspect.signature(function).parameters.values()):
        return function
    return lambda control, managed, **ignored: function(control, managed)


@contextlib.contextmanager
def patched(**attributes):
    saved = {name: getattr(adapter, name) for name in attributes}
    for name, value in attributes.items():
        setattr(adapter, name, _accepting_runner(value) if name == "recovery_preconditions" else value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(adapter, name, value)


@contextlib.contextmanager
def checkout(path):
    saved = adapter.PACKAGE_DIR
    adapter.PACKAGE_DIR = (Path(path) / "src" / "codex_harness").resolve()
    try:
        yield
    finally:
        adapter.PACKAGE_DIR = saved


API = SimpleNamespace(
    write_activation=adapter.write_activation, write_fence=adapter.write_fence, current_revision=adapter.current_revision,
    classify_activation_files=adapter.classify_activation_files, release_ready=adapter.release_ready,
    recovery_preconditions=recovery_preconditions, runner_processes=adapter.runner_processes,
    runner_argv=adapter._runner_argv, switch_effect=switch_effect, SystemdHostTarget=adapter.SystemdHostTarget,
    prepare_layout=adapter.prepare_layout, pg_compare_schema=pg_compare_schema,
    pg_coverage_receipt=adapter.pg_coverage_receipt, run_canonical=run_canonical,
    canonical_tool=adapter.canonical_tool, canonical_module=canonical_module,
    catalog_digest=adapter.catalog_digest, document_bytes=adapter._document_bytes, atomic_write=adapter._atomic_write,
    ACTIVATION_FILE=adapter.ACTIVATION_FILE, FENCE_FILE=adapter.FENCE_FILE,
    RECORDED_NOT_SWITCHED=adapter.RECORDED_NOT_SWITCHED, RECEIPT_WRITTEN=adapter.RECEIPT_WRITTEN,
    SWITCHED=adapter.SWITCHED, INCONSISTENT=adapter.INCONSISTENT, POSIX_ONLY=adapter.POSIX_ONLY,
    SWITCH_UNITS=adapter.SWITCH_UNITS, LAYOUT=adapter.LAYOUT, MigrationRefused=policy.MigrationRefused,
    MemoryStore=MemoryStore, HostMigrations=application.HostMigrations, BUCKET=application.BUCKET,
    BUCKET_TRANSITIONS=application.BUCKET_TRANSITIONS, BUCKET_CHECKPOINTS=application.BUCKET_CHECKPOINTS,
    policy=policy, DESCRIPTOR_SCHEMA=DESCRIPTOR_SCHEMA, descriptor_digest=descriptor_digest, digest=digest,
    validate_targets=validate_targets, KIND_SYSTEMD=KIND_SYSTEMD, launcher=_launcher, launcher_path=LAUNCHER_PATH,
    SOURCE_ROOT=SOURCE_ROOT, TOOL_ROOT=TOOL_ROOT, trace=trace, os_replace=os_replace, patched=patched, checkout=checkout)



@contextlib.contextmanager
def fake_utcnow():
    saved = adapter._utcnow, host_delivery._utcnow
    adapter._utcnow = host_delivery._utcnow = lambda: CLOCK.now(timezone.utc).isoformat()
    try:
        yield
    finally:
        adapter._utcnow, host_delivery._utcnow = saved


if __name__ == "__main__":
    with fake_utcnow():
        result = s7_host_migration_transfer.run(API)
    driver.finish("target", "delivery.host_migration_transfer", result)
