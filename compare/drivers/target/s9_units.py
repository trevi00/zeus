"""Target driver: `effects.s9_units` on the target tree (the V9 home `observation.application.observations`: Collector and Observer over
the moved file spool and schema, and the moved `MemoryStore`/`PostgresStore`). The reference's `backend(name)`, `reset()` and `recording(store)`; no clock or id
source is patched in (the shared steps inject them per case).
"""

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import recorder as rec  # noqa: E402
import s9_units  # noqa: E402
from codex_harness.observation.adapters.observation_schema import validate_observation  # noqa: E402
from codex_harness.observation.adapters.observation_spool import (  # noqa: E402
    FileSpool,
    SpoolDirectory,
    encode_record,
)
from codex_harness.observation.application.observations import Collector, Observer  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: E402


def digest_of(body) -> str:
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


PG_DSN = os.environ.get("ZEUS_REBUILD_PG_DSN")
SCENARIO = "effects.s9_units.pg" if PG_DSN else "effects.s9_units"


class Backend:
    """A fresh MemoryStore, or (`effects.s9_units.pg`) a fresh schema on the labelled disposable PostgreSQL migrated by this
    side's PostgresStore; its stored rows are readable as [bucket, key, status, body digest]."""

    def __init__(self, name: str):
        assert name == "memory", name
        self.schema = None
        if not PG_DSN:
            self.store = MemoryStore()
            return
        import psycopg
        from psycopg.conninfo import make_conninfo

        self.psycopg = psycopg
        self.schema = "s9_units"
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{self.schema}"')
        self.dsn = make_conninfo(PG_DSN, options=f"-c search_path={self.schema},public")
        self.store = PostgresStore(self.dsn)
        self.store.migrate()

    def rows(self) -> list:
        if self.schema is None:
            return sorted([b, k, (v or {}).get("status") or "", digest_of(v)] for (b, k), v in self.store.data.items())
        with self.psycopg.connect(self.dsn) as conn:
            return sorted([b, k, (v or {}).get("status") or "", digest_of(v)] for b, k, v in conn.execute(
                "SELECT bucket, id, body FROM documents").fetchall())

    def drop(self) -> None:
        if self.schema is not None:
            with self.psycopg.connect(PG_DSN, autocommit=True) as conn:
                conn.execute(f'DROP SCHEMA "{self.schema}" CASCADE')


def reset():
    pass   # the clock, ids, host and pid are injected per case by the shared steps

API = SimpleNamespace(Collector=Collector, Observer=Observer, FileSpool=FileSpool, SpoolDirectory=SpoolDirectory,
                      encode_record=encode_record, validate=validate_observation, MemoryStore=MemoryStore, backend=Backend, reset=reset,
                      recording=lambda store: rec.RecordingStore(store))

if __name__ == "__main__":
    driver.finish("target", SCENARIO, s9_units.run(API))
