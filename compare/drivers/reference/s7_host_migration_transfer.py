"""Reference driver: `delivery.host_migration_transfer` (M7 `adapters/host_migration.py` without the PG/Redis transfer).

The API holds plain M7 objects. From `adapters.host_migration`:
- the functions `write_activation`, `write_fence`, `current_revision`, `classify_activation_files`, `release_ready`,
  `recovery_preconditions`, `runner_processes`, `switch_effect`, `prepare_layout`, `pg_compare_schema`,
  `pg_coverage_receipt`, `run_canonical`, `canonical_tool`, `canonical_module`, `catalog_digest` and `main`;
- the private names `_runner_argv` (as `runner_argv`), `_document_bytes` (as `document_bytes`) and `_atomic_write`
  (as `atomic_write`);
- `SystemdHostTarget`;
- the constants `ACTIVATION_FILE`, `FENCE_FILE`, `RECORDED_NOT_SWITCHED`, `RECEIPT_WRITTEN`, `SWITCHED`,
  `INCONSISTENT`, `POSIX_ONLY`, `SWITCH_UNITS` and `LAYOUT`.

From pilot 28 (`delivery.host_migrations`): `MemoryStore`, `HostMigrations`, `BUCKET`, `BUCKET_TRANSITIONS`,
`BUCKET_CHECKPOINTS`, `policy` (the M7 `domain.host_migration` module), `DESCRIPTOR_SCHEMA`, `descriptor_digest` and
`digest`. From `domain.host_delivery`: `validate_targets` and `KIND_SYSTEMD`. `MigrationRefused` is the domain's.
`launcher` and `launcher_path` are the unchanged deploy/aibox launcher module and path, loaded from the SOURCE tree;
`SOURCE_ROOT` is that tree (the canonical tool `scripts/aibox_data` is COPIED from it).

Four hooks, each a context manager that restores what it changed:
- `trace()` wraps the adapter's `write_activation`, `_replace_current`, `_fsync_directory` and `os.fsync` and yields
  one ordered `events` list (`receipt`, `current`, `fsync:<directory name>`, `os.fsync:file`, `os.fsync:dir`), as M7's
  `spied` does;
- `os_replace(factory)` makes `adapter.os.replace` the callable `factory(real)` returns;
- `patched(**attrs)` replaces attributes of the adapter module (`_posix`, `_coordinator`, `recovery_preconditions`);
- `checkout(path)` makes `adapter.codex_harness` a stand-in whose `__file__` is `<path>/src/codex_harness/__init__.py`,
  so `canonical_tool` resolves `<path>/scripts/aibox_data`.

The module reads its clock and id source through `determinism.install` (the fence document's `at`)."""

import contextlib
import importlib.util
import os
import stat
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_host_migration_transfer  # noqa: E402

from codex_harness.adapters import host_migration as adapter  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import host_migration as application  # noqa: E402
from codex_harness.domain import host_migration as policy  # noqa: E402
from codex_harness.domain.host_delivery import (  # noqa: E402
    DESCRIPTOR_SCHEMA,
    KIND_SYSTEMD,
    descriptor_digest,
    validate_targets,
)
from codex_harness.domain.model import digest  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)

SOURCE_ROOT = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve()
LAUNCHER_PATH = SOURCE_ROOT / "deploy" / "aibox" / "zeus_aibox_service.py"
_spec = importlib.util.spec_from_file_location("zeus_aibox_service_transfer", LAUNCHER_PATH)
_launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_launcher)


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


@contextlib.contextmanager
def patched(**attributes):
    saved = {name: getattr(adapter, name) for name in attributes}
    for name, value in attributes.items():
        setattr(adapter, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(adapter, name, value)


@contextlib.contextmanager
def checkout(path):
    saved = adapter.codex_harness
    adapter.codex_harness = SimpleNamespace(__file__=str(Path(path) / "src" / "codex_harness" / "__init__.py"))
    try:
        yield
    finally:
        adapter.codex_harness = saved


API = SimpleNamespace(
    write_activation=adapter.write_activation, write_fence=adapter.write_fence, current_revision=adapter.current_revision,
    classify_activation_files=adapter.classify_activation_files, release_ready=adapter.release_ready,
    recovery_preconditions=adapter.recovery_preconditions, runner_processes=adapter.runner_processes,
    runner_argv=adapter._runner_argv, switch_effect=adapter.switch_effect, SystemdHostTarget=adapter.SystemdHostTarget,
    prepare_layout=adapter.prepare_layout, pg_compare_schema=adapter.pg_compare_schema,
    pg_coverage_receipt=adapter.pg_coverage_receipt, run_canonical=adapter.run_canonical,
    canonical_tool=adapter.canonical_tool, canonical_module=adapter.canonical_module,
    catalog_digest=adapter.catalog_digest, document_bytes=adapter._document_bytes, atomic_write=adapter._atomic_write,
    main=adapter.main, ACTIVATION_FILE=adapter.ACTIVATION_FILE, FENCE_FILE=adapter.FENCE_FILE,
    RECORDED_NOT_SWITCHED=adapter.RECORDED_NOT_SWITCHED, RECEIPT_WRITTEN=adapter.RECEIPT_WRITTEN,
    SWITCHED=adapter.SWITCHED, INCONSISTENT=adapter.INCONSISTENT, POSIX_ONLY=adapter.POSIX_ONLY,
    SWITCH_UNITS=adapter.SWITCH_UNITS, LAYOUT=adapter.LAYOUT, MigrationRefused=policy.MigrationRefused,
    MemoryStore=MemoryStore, HostMigrations=application.HostMigrations, BUCKET=application.BUCKET,
    BUCKET_TRANSITIONS=application.BUCKET_TRANSITIONS, BUCKET_CHECKPOINTS=application.BUCKET_CHECKPOINTS,
    policy=policy, DESCRIPTOR_SCHEMA=DESCRIPTOR_SCHEMA, descriptor_digest=descriptor_digest, digest=digest,
    validate_targets=validate_targets, KIND_SYSTEMD=KIND_SYSTEMD, launcher=_launcher, launcher_path=LAUNCHER_PATH,
    SOURCE_ROOT=SOURCE_ROOT, TOOL_ROOT=SOURCE_ROOT, trace=trace, os_replace=os_replace, patched=patched, checkout=checkout)

if __name__ == "__main__":
    driver.finish("reference", "delivery.host_migration_transfer", s7_host_migration_transfer.run(API))
