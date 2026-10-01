"""Reference driver: the M7 whole-database restore rehearsal of `adapters/host_migration.py` (D1-D3, R1), scenario
family `delivery.restore.pg`, on the labelled disposable PostgreSQL PAIR the harness starts for a
`disposable-postgresql-pair` scenario (A/evidence/rebuild/s7/restore/DESIGN.md §2).

The API (plain M7 objects):
- adapter: `pg_catalog`, `catalog_digest`, `pg_dump_database`, `pg_restore_database`, `pg_export`, `run_canonical`,
  `pg_compare_schema`, `pg_coverage_receipt`;
- domain host_migration: `MigrationRefused`, `compare_catalogs`, `reverse_maps`;
- `PostgresStore`, `PostgresKnowledge`, `Fleet`, `BUCKET_JOBS`, `BUCKET_REGISTRY`;
- domain fleet: `config_digest`, `repository_identity`, `resolve_repository`, `validate_budget`;
- `HOST_MIGRATION_SCHEMA`;
- adapters fleet_recovery: `checkout_identity`, `collect_host_migration_proof`, `run_root`;
- `repository_aliases(fleet, tx)` (M7 `Fleet._repository_aliases`, as M7's rehearsal reads it);
- `SOURCE_ROOT` (the SOURCE checkout the harness extracted);
- `checkout(path)`: it makes `adapter.codex_harness` a stand-in whose `__file__` is
  `<path>/src/codex_harness/__init__.py`, so `canonical_tool` resolves `<path>/scripts/aibox_data` (the wheel
  carries no `scripts`).

The clock and id source go through `determinism.install`."""

import contextlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s7_restore  # noqa: E402

from codex_harness.adapters import host_migration as adapter  # noqa: E402
from codex_harness.adapters.fleet_recovery import (  # noqa: E402
    checkout_identity,
    collect_host_migration_proof,
    run_root,
)
from codex_harness.adapters.knowledge import PostgresKnowledge  # noqa: E402
from codex_harness.adapters.store import PostgresStore  # noqa: E402
from codex_harness.application.fleet import BUCKET_JOBS, BUCKET_REGISTRY, Fleet  # noqa: E402
from codex_harness.domain.fleet import (  # noqa: E402
    config_digest,
    repository_identity,
    resolve_repository,
    validate_budget,
)
from codex_harness.domain.fleet_recovery import HOST_MIGRATION_SCHEMA  # noqa: E402
from codex_harness.domain.host_migration import (  # noqa: E402
    MigrationRefused,
    compare_catalogs,
    reverse_maps,
)

CLOCK = determinism.FakeClock(datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)
SOURCE_ROOT = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve()


@contextlib.contextmanager
def checkout(path):
    saved = adapter.codex_harness
    adapter.codex_harness = SimpleNamespace(__file__=str(Path(path) / "src" / "codex_harness" / "__init__.py"))
    try:
        yield
    finally:
        adapter.codex_harness = saved


API = SimpleNamespace(
    pg_catalog=adapter.pg_catalog, catalog_digest=adapter.catalog_digest, pg_dump_database=adapter.pg_dump_database,
    pg_restore_database=adapter.pg_restore_database, pg_export=adapter.pg_export, run_canonical=adapter.run_canonical,
    pg_compare_schema=adapter.pg_compare_schema, pg_coverage_receipt=adapter.pg_coverage_receipt,
    MigrationRefused=MigrationRefused, compare_catalogs=compare_catalogs, reverse_maps=reverse_maps,
    PostgresStore=PostgresStore, PostgresKnowledge=PostgresKnowledge, Fleet=Fleet, BUCKET_JOBS=BUCKET_JOBS,
    BUCKET_REGISTRY=BUCKET_REGISTRY, config_digest=config_digest, repository_identity=repository_identity,
    resolve_repository=resolve_repository, validate_budget=validate_budget,
    HOST_MIGRATION_SCHEMA=HOST_MIGRATION_SCHEMA, checkout_identity=checkout_identity,
    collect_host_migration_proof=collect_host_migration_proof, run_root=run_root,
    repository_aliases=lambda fleet, tx: fleet._repository_aliases(tx), SOURCE_ROOT=SOURCE_ROOT, checkout=checkout)

if __name__ == "__main__":
    driver.finish("reference", "delivery.restore.pg", s7_restore.run(API))
