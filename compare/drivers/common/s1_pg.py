"""Scenario body `storage.pg` (REBUILD-DESIGN-v2 §5.3 S1: store transaction, advisory lock 734219 and
lock_timeout on a labelled disposable PostgreSQL; the §2.9 recorder against the PostgreSQL store).

Layer: harness (never shipped). `api` provides: PostgresStore, Migrator, migrations_config,
resources_root, ContractError. `psycopg` is the side's own driver library (both pin 3.3.5). Every
case uses a fresh schema of the disposable server and drops it afterwards; the durable rows are
read back through a separate connection, never through the store under test.
"""

from __future__ import annotations

import threading

import recorder as rec
from s1_common import outcome, relative

LOCK = 734219


class Injected(RuntimeError):
    pass


class Schema:
    def __init__(self, psycopg, dsn: str, name: str):
        from psycopg.conninfo import make_conninfo

        self.psycopg, self.base, self.name = psycopg, dsn, "s1_" + name
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.name}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{self.name}"')
        self.dsn = make_conninfo(dsn, options=f"-c search_path={self.name},public")

    def rows(self, table="documents"):
        with self.psycopg.connect(self.dsn) as conn:
            if table == "documents":
                return [[b, k, v] for b, k, v in conn.execute(
                    "SELECT bucket, id, body FROM documents ORDER BY bucket, id").fetchall()]
            if table == "knowledge_nodes":
                return [list(r) for r in conn.execute(
                    "SELECT id, repository, kind, body, source_ref, revision, properties FROM knowledge_nodes "
                    "ORDER BY id").fetchall()]
            if table == "knowledge_edges":
                return [list(r) for r in conn.execute("SELECT * FROM knowledge_edges ORDER BY 1, 2, 3").fetchall()]
            raise ValueError(table)

    def advisory_holders(self) -> int:
        with self.psycopg.connect(self.base, autocommit=True) as conn:
            return conn.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = %s "
                                "AND granted", (LOCK,)).fetchone()[0]

    def drop(self):
        with self.psycopg.connect(self.base, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA "{self.name}" CASCADE')


def migrate(api, psycopg, dsn, clock) -> dict:
    schema = Schema(psycopg, dsn, "migrate")
    clock.reset()
    store = api.PostgresStore(schema.dsn)
    first = store.migrate()
    clock.advance(3)
    second = store.migrate()
    with psycopg.connect(schema.dsn) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY 1",
            (schema.name,)).fetchall()]
        history = [list(r) for r in conn.execute(
            "SELECT module, version, checksum, name, tool, applied_at, applied_by FROM schema_migrations "
            "ORDER BY module, version").fetchall()]
        columns = [list(r) for r in conn.execute(
            "SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = %s ORDER BY table_name, ordinal_position", (schema.name,)).fetchall()]
        indexes = [r[0] for r in conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = %s ORDER BY indexname", (schema.name,)).fetchall()]
    migrator = api.Migrator(schema.dsn, api.migrations_config(), api.resources_root)
    precheck = migrator.precheck()
    schema.drop()
    roots = {"RESOURCES": str(api.resources_root)}
    return {"first": relative(first, roots), "second": relative(second, roots), "tables": tables,
            "history": history, "columns": columns, "indexes": [i.replace(schema.name, "<schema>") for i in indexes],
            "precheck": relative(precheck, roots)}


def transactions(api, psycopg, dsn) -> dict:
    out: dict = {}
    schema = Schema(psycopg, dsn, "tx")
    store = api.PostgresStore(schema.dsn)
    store.migrate()
    with store.transaction() as tx:
        tx.put("b", "k2", {"v": 2})
        tx.put("b", "k1", {"v": 1, "nested": {"한": [1, None]}})
        out["read_own_write"] = tx.get("b", "k1")
        out["lock_timeout"] = tx.conn.execute("SHOW lock_timeout").fetchone()[0]
        out["advisory_holders_during"] = schema.advisory_holders()
    out["advisory_holders_after"] = schema.advisory_holders()
    out["committed_rows"] = schema.rows()
    try:
        with store.transaction() as tx:
            tx.put("b", "k3", {"v": 3})
            tx.put("b", "k1", {"v": "overwritten"})
            raise Injected("rollback")
    except Injected:
        pass
    out["after_rollback_rows"] = schema.rows()
    with store.transaction(fail_fast=True) as tx:
        out["fail_fast_lock_timeout"] = tx.conn.execute("SHOW lock_timeout").fetchone()[0]
        out["scan"] = tx.scan("b")
        out["records"] = tx.records()
        out["entries"] = [tx.entries("b"), tx.entries("b", after="k1"), tx.entries("b", "k1", 1)]
        out["missing"] = tx.get("b", "absent")
    # A second writer while the control-plane lock is held: the fail-fast budget refuses it.
    with store.transaction() as holder:
        holder.put("b", "held", {"v": 1})
        out["concurrent_fail_fast"] = outcome(lambda: _enter(store, fail_fast=True))
    # A normal-budget writer waits for the holder instead of failing.
    order = []
    release = threading.Event()

    def hold():
        with store.transaction() as tx:
            tx.put("b", "first", {"v": 1})
            order.append("holder_locked")
            release.wait(5)
            order.append("holder_commit")

    thread = threading.Thread(target=hold)
    thread.start()
    while "holder_locked" not in order:
        release.wait(0.01)
    timer = threading.Timer(0.3, release.set)
    timer.start()
    with store.transaction() as tx:
        order.append("waiter_locked")
        out["waiter_sees_holder_commit"] = tx.get("b", "first")
    thread.join()
    out["wait_order"] = order
    # Graph writes share the documents transaction: a rollback removes nodes and edges too.
    with store.transaction() as tx:
        graph = tx.graph()
        graph.put_node({"id": "n1", "repository": "r", "kind": "module", "body": {"a": 1}, "source_ref": "s",
                        "revision": "v", "properties": {"p": 1}})
        graph.put_node({"id": "n2", "repository": "r", "kind": "module", "body": {}, "source_ref": "s",
                        "revision": "v", "properties": {}})
        graph.put_edge("n1", "n2", "imports")
        graph.put_edge("n1", "n2", "imports")
    try:
        with store.transaction() as tx:
            tx.graph().put_node({"id": "n9", "repository": "r", "kind": "module", "body": {}, "source_ref": "s",
                                 "revision": "v", "properties": {}})
            raise Injected("graph rollback")
    except Injected:
        pass
    with store.transaction() as tx:
        tx.graph().put_node({"id": "n1", "repository": "other", "kind": "module", "body": {"a": 2},
                             "source_ref": "s2", "revision": "v2", "properties": {}})
    out["graph_nodes"] = schema.rows("knowledge_nodes")
    out["graph_edges"] = schema.rows("knowledge_edges")
    schema.drop()
    return out


def _enter(store, fail_fast):
    with store.transaction(fail_fast=fail_fast) as tx:
        tx.put("b", "second", {"v": 2})
    return "entered"


def recorder_over_pg(api, psycopg, dsn) -> dict:
    """The S0 §2.9 recorder against this side's PostgreSQL store (the S1 slice-specific exit)."""
    out = {}

    def completion(e):
        return e["kind"] == "write" and e["bucket"] == "decisions_pending" and e["status"] == "succeeded"

    def case(name, body):
        schema = Schema(psycopg, dsn, "rec_" + name)
        inner = api.PostgresStore(schema.dsn)
        inner.migrate()
        store = rec.RecordingStore(inner)
        error = None
        try:
            body(store, store.recorder)
        except Exception as exc:  # noqa: BLE001 - the unit's failure type is part of the result
            error = type(exc).__name__
        r = store.recorder
        out[name] = {"error": error, "verdict": r.classify({"releases"}, completion),
                     "violations": sorted({v["kind"] for v in r.violations}), "trace": r.trace(),
                     "durable_rows": [[b, k, (v or {}).get("status")] for b, k, v in schema.rows()]}
        schema.drop()

    def atomic(store, r):
        with store.transaction() as tx:
            r.fence("lease", True)
            tx.put("releases", "r1", {"status": "proposed"})
            tx.put("decisions_pending", "d", {"status": "succeeded"})

    def rollback(store, r):
        with store.transaction() as tx:
            tx.put("releases", "r1", {"status": "proposed"})
            raise Injected("after release, before decision")

    def nested(store, r):
        with store.transaction() as tx:
            tx.put("decisions_pending", "d", {"status": "running"})
            with store.transaction() as inner:
                inner.put("outbox", "m", {"status": "pending"})

    def effect_inside(store, r):
        with store.transaction() as tx:
            tx.put("decisions_pending", "d", {"status": "running"})
            r.effect("provider_call")

    for name, body in (("atomic_commit", atomic), ("atomic_rollback", rollback), ("nested_begin", nested),
                       ("effect_inside_unit", effect_inside)):
        case(name, body)
    return out


def run(api, psycopg, dsn, clock) -> dict:
    return {"migrate": migrate(api, psycopg, dsn, clock), "transactions": transactions(api, psycopg, dsn),
            "recorder": recorder_over_pg(api, psycopg, dsn)}
