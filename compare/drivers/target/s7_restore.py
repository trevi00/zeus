"""Target driver: `delivery.restore.pg` on the target tree (S7 pilot 44; wired by the owner after pilot 48 moved the
collectors). The owner runs it with `--pg` on the disposable pair.

The api members and their target sources:
- adapter (`delivery.adapters.host_migration`): `pg_catalog`, `catalog_digest`, `pg_export`, `pg_coverage_receipt`;
  `pg_dump_database`, `pg_restore_database`, `run_canonical` and `pg_compare_schema` are wrapped with the V6 `runner`
  M7 defaulted (`process_groups.run_process` for the docker tools, the chokepoint `run` for the canonical tool); the
  `docker exec` argv is unchanged, so the guard's PGEXEC form still admits it. A runner a case supplies wins.
- domain host_migration (`delivery.domain.host_migration`): `MigrationRefused`, `compare_catalogs`, `reverse_maps`.
- `PostgresStore` (`storage.adapters.postgres_store`, with this driver's fake clock as the S1 `s1_pg` driver passes it:
  its migrator stamps `schema_migrations.applied_at`, which the catalogs digest; the reference's installed fake
  serves M7's `utcnow()` there), `PostgresKnowledge` (`knowledge.adapters.postgres_knowledge`).
- `Fleet(store)`: the S5 facade (`s5_fleet_composition.FleetFacade`) over the S5 registry/admission/pause/recovery objects,
  with the clock and token the reference gets from its installed fakes (the SAME `FakeClock(2026-09-25T09:00Z)` and
  `FakeIds`, instantiated without installing them).
- `BUCKET_JOBS`, `BUCKET_REGISTRY` (`coordination.application.fleet.state`); `config_digest`, `repository_identity`,
  `resolve_repository`, `validate_budget` (`coordination.domain.fleet`); `HOST_MIGRATION_SCHEMA`
  (`coordination.domain.fleet_recovery`); `repository_aliases(fleet, tx)` (`fleet.state.repository_aliases(tx)`, M7's
  `Fleet._repository_aliases`).
- `checkout_identity`, `collect_host_migration_proof`, `run_root`: the moved collectors
  (`coordination.adapters.fleet_recovery`, pilot 48), with the collaborators `composition.fleet_recovery.collectors()`
  wires (`state`, `run_records`, `git_source`); the proof's `clock` is this driver's fake clock, as the reference's
  installed fake serves M7's `clock=utcnow` default. `verify_schema` keeps M7's default, the moved real
  `verify_lane_schema` (DESIGN adapters-move §14 correction).
- `SOURCE_ROOT` (the SOURCE checkout) and `TOOL_ROOT` (the target root whose `scripts/aibox_data` is the canonical tool;
  `common/s7_restore.py` copies `TOOL_ROOT/scripts/aibox_data`).
- `checkout(path)` patches the adapter's `PACKAGE_DIR` to `<path>/src/codex_harness`.

Clock seam (as in pilot 43): the imported `_utcnow` of the target adapter modules is substituted for the run with the same
fake clock (a module-attribute substitution, restored afterwards); the fakes are never installed."""

import contextlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s5_fleet_composition  # noqa: E402
import s7_restore  # noqa: E402
from codex_harness.composition import fleet_recovery as recovery_composition  # noqa: E402
from codex_harness.coordination.adapters import fleet_recovery as collectors  # noqa: E402
from codex_harness.coordination.application.fleet import state as fleet_state  # noqa: E402
from codex_harness.coordination.domain import fleet as fleet_domain  # noqa: E402
from codex_harness.coordination.domain.fleet_recovery import HOST_MIGRATION_SCHEMA  # noqa: E402
from codex_harness.delivery.adapters import host_delivery  # noqa: E402
from codex_harness.delivery.adapters import host_migration as adapter  # noqa: E402
from codex_harness.delivery.domain.host_migration import (  # noqa: E402
    MigrationRefused,
    compare_catalogs,
    reverse_maps,
)
from codex_harness.host_os.adapters import process_groups  # noqa: E402
from codex_harness.knowledge.adapters.postgres_knowledge import PostgresKnowledge  # noqa: E402
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
SOURCE_ROOT = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve()
TOOL_ROOT = Path(os.environ["ZEUS_REBUILD_TARGET_SRC"]).resolve().parent
CLOCK_PORT = PortClock(CLOCK)


def pg_dump_database(*args, runner=process_groups.run_process):
    return adapter.pg_dump_database(*args, runner=runner)


def pg_restore_database(*args, runner=process_groups.run_process, **kwargs):
    return adapter.pg_restore_database(*args, runner=runner, **kwargs)


def run_canonical(argv, *, runner=process_groups.run, **kwargs):
    return adapter.run_canonical(argv, runner=runner, **kwargs)


def pg_compare_schema(*args, runner=process_groups.run, **kwargs):
    return adapter.pg_compare_schema(*args, runner=runner, **kwargs)


def Fleet(store):
    return s5_fleet_composition.FleetFacade(
        store, lambda: CLOCK.now(timezone.utc).isoformat(), lambda: IDS.uuid4().hex)


WIRED = recovery_composition.collectors(budget=None)


def checkout_identity(path, source=None):
    return collectors.checkout_identity(path, source, git_source=WIRED.git_source)


def collect_host_migration_proof(request, jobs, *, journal, host_dsn, **kwargs):
    kwargs.setdefault("clock", lambda: CLOCK.now(timezone.utc).isoformat())
    return collectors.collect_host_migration_proof(request, jobs, journal=journal, host_dsn=host_dsn,
                                                   state=WIRED.state, run_records=WIRED.run_records,
                                                   git_source=WIRED.git_source, **kwargs)


@contextlib.contextmanager
def checkout(path):
    saved = adapter.PACKAGE_DIR
    adapter.PACKAGE_DIR = (Path(path) / "src" / "codex_harness").resolve()
    try:
        yield
    finally:
        adapter.PACKAGE_DIR = saved


@contextlib.contextmanager
def fake_utcnow():
    saved = adapter._utcnow, host_delivery._utcnow
    adapter._utcnow = host_delivery._utcnow = lambda: CLOCK.now(timezone.utc).isoformat()
    try:
        yield
    finally:
        adapter._utcnow, host_delivery._utcnow = saved


API = SimpleNamespace(
    pg_catalog=adapter.pg_catalog, catalog_digest=adapter.catalog_digest, pg_dump_database=pg_dump_database,
    pg_restore_database=pg_restore_database, pg_export=adapter.pg_export, run_canonical=run_canonical,
    pg_compare_schema=pg_compare_schema, pg_coverage_receipt=adapter.pg_coverage_receipt,
    MigrationRefused=MigrationRefused, compare_catalogs=compare_catalogs, reverse_maps=reverse_maps,
    PostgresStore=lambda dsn: PostgresStore(dsn, clock=CLOCK_PORT), PostgresKnowledge=PostgresKnowledge, Fleet=Fleet,
    BUCKET_JOBS=fleet_state.BUCKET_JOBS, BUCKET_REGISTRY=fleet_state.BUCKET_REGISTRY,
    config_digest=fleet_domain.config_digest, repository_identity=fleet_domain.repository_identity,
    resolve_repository=fleet_domain.resolve_repository, validate_budget=fleet_domain.validate_budget,
    HOST_MIGRATION_SCHEMA=HOST_MIGRATION_SCHEMA, checkout_identity=checkout_identity,
    collect_host_migration_proof=collect_host_migration_proof, run_root=collectors.run_root,
    repository_aliases=lambda fleet, tx: fleet_state.repository_aliases(tx), SOURCE_ROOT=SOURCE_ROOT,
    TOOL_ROOT=TOOL_ROOT, checkout=checkout)

if __name__ == "__main__":
    with fake_utcnow():
        result = s7_restore.run(API)
    driver.finish("target", "delivery.restore.pg", result)
