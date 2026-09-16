from __future__ import annotations

import json
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

    def entries(self, bucket: str, after: str = "", limit: int = 100) -> list[dict]:
        return [{"id": key, "body": deepcopy(value)}
                for (name, key), value in sorted(self.data.items()) if name == bucket and key > after][:limit]

    def graph(self):
        """Graph-write port (INV-AUTONOMOUS-001): nodes and edges live in the same draft as documents."""
        return MemoryGraph(self)


class MemoryGraph:
    def __init__(self, tx):
        self.tx = tx

    def put_node(self, node: dict) -> None:
        self.tx.put("knowledge_nodes", node["id"], node)

    def put_edge(self, source: str, target: str, kind: str) -> None:
        self.tx.put("knowledge_edges", source + "->" + target + ":" + kind, {"source": source, "target": target, "kind": kind})


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
    def __init__(self, dsn: str):
        self.dsn = dsn

    def migrate(self) -> dict:
        # INV-GRAPH-001: IF NOT EXISTS alone does not serialize concurrent DDL; the migrator takes
        # the control-plane lock, re-reads the applied history under it, refuses a modified applied
        # version and records every applied version with its checksum (INV-MIGRATION-001).
        from codex_harness.adapters.migrations import Migrator
        root = files("codex_harness.resources")
        config = json.loads(root.joinpath("migrations.json").read_text(encoding="utf-8"))
        return Migrator(self.dsn, config, str(root)).apply("store.migrate")

    @contextmanager
    def transaction(self):
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            # One control-plane writer at a time on this local bootstrap DB.
            # Replace with per-aggregate locks after measuring contention.
            conn.execute("SET LOCAL lock_timeout = '10s'")
            conn.execute("SELECT pg_advisory_xact_lock(734219)")
            yield PostgresTransaction(conn)
