"""Reference driver: `storage.pg` on SOURCE M7 against a labelled disposable PostgreSQL.

M7 `PostgresStore` (migrate, transaction, fail_fast, graph) and `Migrator`; `ZEUS_REBUILD_PG_DSN`
names the runner's network-less fixture server (Unix socket only). Clock and ids are the scripted
fakes patched into this process only.
"""

import json
import os
import sys
from importlib.resources import files
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import psycopg  # noqa: E402
import s1_pg  # noqa: E402

from codex_harness.adapters.migrations import Migrator  # noqa: E402
from codex_harness.adapters.store import PostgresStore  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
RESOURCES = files("codex_harness.resources")

API = SimpleNamespace(
    PostgresStore=PostgresStore, Migrator=Migrator, ContractError=ContractError,
    resources_root=Path(str(RESOURCES)).resolve(),
    migrations_config=lambda: json.loads(RESOURCES.joinpath("migrations.json").read_text(encoding="utf-8")))

if __name__ == "__main__":
    driver.finish("reference", "storage.pg", s1_pg.run(API, psycopg, os.environ["ZEUS_REBUILD_PG_DSN"], CLOCK))
