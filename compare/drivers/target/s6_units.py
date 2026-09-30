"""Target driver: `effects.continuation_units` on the target tree (the Continuation and OwnerActions splits, DESIGN-s6
§3/§4; the §2.9 units). The API is the reference's: the S0 RecordingStore over a fresh target MemoryStore, and the S6
compositions. `reset()` resets the S5 scripted clock/ids the G1 envelope draws from (R6), as the reference resets its
patched sources per case."""

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
import s5_coordination_composition as coordination  # noqa: E402
import s6_owner_actions_composition as composition  # noqa: E402
import s6_units  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: E402


def digest(body) -> str:
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


PG_DSN = os.environ.get("ZEUS_REBUILD_PG_DSN")
SCENARIO = "effects.continuation_units.pg" if PG_DSN else "effects.continuation_units"


class Backend:
    """A fresh MemoryStore, or (`effects.continuation_units.pg`) a fresh schema on the labelled disposable PostgreSQL
    migrated by this side's PostgresStore; its stored rows are readable as [bucket, key, status, body digest]."""

    def __init__(self, name: str):
        assert name == "memory", name
        self.schema = None
        if not PG_DSN:
            self.store = MemoryStore()
            return
        import psycopg
        from psycopg.conninfo import make_conninfo

        self.psycopg = psycopg
        self.schema = "s6_units"
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{self.schema}"')
        self.dsn = make_conninfo(PG_DSN, options=f"-c search_path={self.schema},public")
        self.store = PostgresStore(self.dsn)
        self.store.migrate()

    def rows(self) -> list:
        if self.schema is None:
            return sorted([b, k, (v or {}).get("status") or "", digest(v)] for (b, k), v in self.store.data.items())
        with self.psycopg.connect(self.dsn) as conn:
            return sorted([b, k, (v or {}).get("status") or "", digest(v)] for b, k, v in conn.execute(
                "SELECT bucket, id, body FROM documents").fetchall())

    def drop(self) -> None:
        if self.schema is not None:
            with self.psycopg.connect(PG_DSN, autocommit=True) as conn:
                conn.execute(f'DROP SCHEMA "{self.schema}" CASCADE')


def reset():
    coordination.CLOCK.reset()
    coordination.IDS.reset()


API = SimpleNamespace(**composition.api(backend=Backend, reset=reset, recording=lambda store: rec.RecordingStore(store)))

if __name__ == "__main__":
    driver.finish("target", SCENARIO, s6_units.run(API))
