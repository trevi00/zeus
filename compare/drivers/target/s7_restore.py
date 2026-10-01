"""Target driver: `delivery.restore.pg` on the target tree (S7 pilot 44). NOT wired into the scenario: the OWNER runs it
with `--pg` on the disposable pair and then flips the scenario.

The api members and their target sources:
- adapter (`delivery.adapters.host_migration`): `pg_catalog`, `catalog_digest`, `pg_export`, `pg_coverage_receipt`;
  `pg_dump_database`, `pg_restore_database`, `run_canonical` and `pg_compare_schema` are wrapped with the V6 `runner`
  M7 defaulted (`process_groups.run_process` for the docker tools, the chokepoint `run` for the canonical tool); the
  `docker exec` argv is unchanged, so the guard's PGEXEC form still admits it. A runner a case supplies wins.
- domain host_migration (`delivery.domain.host_migration`): `MigrationRefused`, `compare_catalogs`, `reverse_maps`.
- `PostgresStore` (`storage.adapters.postgres_store`), `PostgresKnowledge` (`knowledge.adapters.postgres_knowledge`).
- `Fleet(store)`: the S5 facade (`s5_fleet_composition.FleetFacade`) over the S5 registry/admission/pause/recovery objects,
  with the clock and token the reference gets from its installed fakes (the SAME `FakeClock(2026-09-25T09:00Z)` and
  `FakeIds`, instantiated without installing them).
- `BUCKET_JOBS`, `BUCKET_REGISTRY` (`coordination.application.fleet.state`); `config_digest`, `repository_identity`,
  `resolve_repository`, `validate_budget` (`coordination.domain.fleet`); `HOST_MIGRATION_SCHEMA`
  (`coordination.domain.fleet_recovery`); `repository_aliases(fleet, tx)` (`fleet.state.repository_aliases(tx)`, M7's
  `Fleet._repository_aliases`).
- `checkout_identity`, `collect_host_migration_proof`, `run_root`: M7 `adapters.fleet_recovery` collectors. They have NO
  target home yet (the fleet_recovery collectors move is a later pilot): these three members raise
  `NotImplementedError` naming that gap, so the registry case cannot run until they exist.
- `SOURCE_ROOT` (the SOURCE checkout) and `TOOL_ROOT` (the target root whose `scripts/aibox_data` is the canonical tool;
  `common/s7_restore.py` copies `SOURCE_ROOT/scripts/aibox_data` and needs the same one-member change as the transfer
  family to use `TOOL_ROOT`).
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
from codex_harness.coordination.application.fleet import state as fleet_state  # noqa: E402
from codex_harness.coordination.domain import fleet as fleet_domain  # noqa: E402
from codex_harness.coordination.domain.fleet_recovery import HOST_MIGRATION_SCHEMA  # noqa: E402
from codex_harness.delivery.adapters import host_delivery, host_migration as adapter  # noqa: E402
from codex_harness.delivery.domain.host_migration import (  # noqa: E402
    MigrationRefused,
    compare_catalogs,
    reverse_maps,
)
from codex_harness.host_os.adapters import process_groups  # noqa: E402
from codex_harness.knowledge.adapters.postgres_knowledge import PostgresKnowledge  # noqa: E402
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
SOURCE_ROOT = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve()
TOOL_ROOT = Path(os.environ["ZEUS_REBUILD_TARGET_SRC"]).resolve().parent


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


def _missing(name):
    def pending(*args, **kwargs):
        raise NotImplementedError(f"{name}: M7 adapters.fleet_recovery has no target home yet (later move)")
    return pending


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
    PostgresStore=PostgresStore, PostgresKnowledge=PostgresKnowledge, Fleet=Fleet,
    BUCKET_JOBS=fleet_state.BUCKET_JOBS, BUCKET_REGISTRY=fleet_state.BUCKET_REGISTRY,
    config_digest=fleet_domain.config_digest, repository_identity=fleet_domain.repository_identity,
    resolve_repository=fleet_domain.resolve_repository, validate_budget=fleet_domain.validate_budget,
    HOST_MIGRATION_SCHEMA=HOST_MIGRATION_SCHEMA, checkout_identity=_missing("checkout_identity"),
    collect_host_migration_proof=_missing("collect_host_migration_proof"), run_root=_missing("run_root"),
    repository_aliases=lambda fleet, tx: fleet_state.repository_aliases(tx), SOURCE_ROOT=SOURCE_ROOT,
    TOOL_ROOT=TOOL_ROOT, checkout=checkout)

if __name__ == "__main__":
    with fake_utcnow():
        result = s7_restore.run(API)
    driver.finish("target", "delivery.restore.pg", result)
