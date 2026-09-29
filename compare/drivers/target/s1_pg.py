"""Target driver: `storage.pg` on the target tree against the same labelled disposable PostgreSQL."""

import json
import os
import sys
from importlib.resources import files
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import psycopg  # noqa: E402
import s1_pg  # noqa: E402
from s1_target import PortClock  # noqa: E402

from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.storage.adapters.migrator import Migrator  # noqa: E402
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
CLOCK_PORT = PortClock(CLOCK)
RESOURCES = files("codex_harness.resources")

API = SimpleNamespace(
    PostgresStore=lambda dsn: PostgresStore(dsn, clock=CLOCK_PORT),
    Migrator=lambda dsn, config, root: Migrator(dsn, config, root, clock=CLOCK_PORT), ContractError=ContractError,
    resources_root=Path(str(RESOURCES)).resolve(),
    migrations_config=lambda: json.loads(RESOURCES.joinpath("migrations.json").read_text(encoding="utf-8")))

if __name__ == "__main__":
    driver.finish("target", "storage.pg", s1_pg.run(API, psycopg, os.environ["ZEUS_REBUILD_PG_DSN"], CLOCK))
