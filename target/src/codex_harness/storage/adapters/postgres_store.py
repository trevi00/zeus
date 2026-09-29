"""The PostgreSQL store: one connection, one transaction and the control-plane advisory lock per unit.

Layer: adapters
Context: storage
Owns: access to the `documents`, `knowledge_nodes`, `knowledge_edges` tables; `migrate()`
Does not own: record meaning; the schema history rules (storage.domain.migrations)
Entry points: PostgresStore.transaction, PostgresStore.migrate, PostgresTransaction, PostgresGraph
Contracts: INV-MIGRATION-001, INV-GRAPH-001

§2.9: every atomic unit is exactly one `transaction()`: one connection, `lock_timeout`, then
`pg_advisory_xact_lock(734219)`, released by the commit/rollback that ends the unit. A nested
`transaction()` is a second connection waiting on the lock its own caller holds, so it can only
time out: owner operations take the caller's `Transaction` instead of opening one.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from importlib.resources import files

import psycopg
from psycopg.types.json import Jsonb

from codex_harness.kernel.ports import Clock

# One control-plane writer at a time: the same key as the migrator's (storage.adapters.migrator.LOCK).
CONTROL_PLANE_LOCK = 734219


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

    def entries(self, bucket: str, after: str = "", limit: int = 100) -> list[dict]:
        return [{"id": row[0], "body": row[1]} for row in self.conn.execute(
            "SELECT id,body FROM documents WHERE bucket=%s AND id>%s ORDER BY id LIMIT %s",
            (bucket, after, limit)).fetchall()]

    def graph(self):
        """Graph-write port on the same connection and transaction as the documents (INV-AUTONOMOUS-001):
        a rollback of the receipt rolls the nodes and edges back with it."""
        return PostgresGraph(self.conn)


class PostgresGraph:
    def __init__(self, conn):
        self.conn = conn

    def put_node(self, node: dict) -> None:
        # A promoted namespace row is only ever updated by its own namespace, never by index_python
        # or project_runtime (they delete within their own repository values only).
        self.conn.execute("""INSERT INTO knowledge_nodes(id,repository,kind,body,source_ref,revision,properties)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET body=excluded.body,source_ref=excluded.source_ref,
            revision=excluded.revision,properties=excluded.properties WHERE knowledge_nodes.repository=excluded.repository""",
                          (node["id"], node["repository"], node["kind"], json.dumps(node["body"], sort_keys=True),
                           node["source_ref"], node["revision"], Jsonb(node["properties"])))

    def put_edge(self, source: str, target: str, kind: str) -> None:
        self.conn.execute("INSERT INTO knowledge_edges VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (source, target, kind))


class PostgresStore:
    """Opens one short-lived connection per unit; holds no connection between units."""

    def __init__(self, dsn: str, *, clock: Clock | None = None):
        self.dsn = dsn
        self.clock = clock

    def migrate(self) -> dict:
        # INV-GRAPH-001: IF NOT EXISTS alone does not serialize concurrent DDL; the migrator takes
        # the control-plane lock, re-reads the applied history under it, refuses a modified applied
        # version and records every applied version with its checksum (INV-MIGRATION-001).
        from codex_harness.storage.adapters.migrator import Migrator
        root = files("codex_harness.resources")
        config = json.loads(root.joinpath("migrations.json").read_text(encoding="utf-8"))
        return Migrator(self.dsn, config, str(root), clock=self.clock).apply("store.migrate")

    @contextmanager
    def transaction(self, fail_fast: bool = False):
        # `fail_fast` is for display-only writes (S2b activity) that must never wait behind the control-plane
        # writer: a short connect and lock budget, and the caller drops its write instead of waiting. Every other
        # caller keeps the normal budget.
        with psycopg.connect(self.dsn, connect_timeout=2 if fail_fast else 5) as conn:
            # One control-plane writer at a time on this local bootstrap DB.
            # Replace with per-aggregate locks after measuring contention.
            conn.execute("SET LOCAL lock_timeout = '500ms'" if fail_fast else "SET LOCAL lock_timeout = '10s'")
            conn.execute(f"SELECT pg_advisory_xact_lock({CONTROL_PLANE_LOCK})")
            yield PostgresTransaction(conn)
