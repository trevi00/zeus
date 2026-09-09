from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from importlib.resources import files
from threading import RLock

import psycopg
from psycopg.types.json import Jsonb


class MemoryTransaction:
    def __init__(self, data: dict):
        self.data = data

    def get(self, bucket: str, key: str) -> dict | None:
        return deepcopy(self.data.get((bucket, key)))

    def put(self, bucket: str, key: str, body: dict) -> None:
        self.data[bucket, key] = deepcopy(body)

    def scan(self, bucket: str) -> list[dict]:
        return [deepcopy(v) for (b, _), v in sorted(self.data.items()) if b == bucket]

    def records(self) -> list[dict]:
        return [{"bucket": bucket, "id": key, "body": deepcopy(value)}
                for (bucket, key), value in sorted(self.data.items())]


class MemoryStore:
    def __init__(self):
        self.data: dict = {}
        self.lock = RLock()

    @contextmanager
    def transaction(self):
        with self.lock:
            draft = deepcopy(self.data)
            yield MemoryTransaction(draft)
            self.data = draft


class PostgresTransaction:
    def __init__(self, conn):
        self.conn = conn

    def get(self, bucket: str, key: str) -> dict | None:
        row = self.conn.execute("SELECT body FROM documents WHERE bucket=%s AND id=%s",
                                (bucket, key)).fetchone()
        return row[0] if row else None

    def put(self, bucket: str, key: str, body: dict) -> None:
        self.conn.execute("""INSERT INTO documents(bucket,id,body) VALUES (%s,%s,%s)
            ON CONFLICT(bucket,id) DO UPDATE SET body=excluded.body""", (bucket, key, Jsonb(body)))

    def scan(self, bucket: str) -> list[dict]:
        return [r[0] for r in self.conn.execute(
            "SELECT body FROM documents WHERE bucket=%s ORDER BY id", (bucket,)).fetchall()]

    def records(self) -> list[dict]:
        return [dict(zip(("bucket", "id", "body"), row)) for row in self.conn.execute(
            "SELECT bucket,id,body FROM documents ORDER BY bucket,id").fetchall()]


class PostgresStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def migrate(self) -> None:
        sql = files("codex_harness.resources").joinpath("001.sql").read_text(encoding="utf-8")
        with psycopg.connect(self.dsn) as conn:
            # INV-GRAPH-001: IF NOT EXISTS alone does not serialize concurrent DDL.
            # Use the control-plane lock before creating extensions, tables or indexes.
            conn.execute("SET LOCAL lock_timeout = '10s'")
            conn.execute("SELECT pg_advisory_xact_lock(734219)")
            conn.execute(sql)

    @contextmanager
    def transaction(self):
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            # One control-plane writer at a time on this local bootstrap DB.
            # Replace with per-aggregate locks after measuring contention.
            conn.execute("SET LOCAL lock_timeout = '10s'")
            conn.execute("SELECT pg_advisory_xact_lock(734219)")
            yield PostgresTransaction(conn)
