"""Host-side boundary of a host migration (INV-HOST-MIGRATION-001).

@invariant INV-HOST-MIGRATION-001

Nothing here decides a migration: `domain.host_migration` holds the policy and
`application.host_migration.HostMigrations` records every transition, checkpoint and activation
intent. This module is the outer adapter boundary:

* Artifact inventory, staging and verification, and every offline comparison (PG rows, Redis
  keys/streams/PEL, PEL owners, rollback gates) are delegated to the accepted canonical tooling
  `scripts/aibox_data`. It runs as its own process, so its real exit code is observed. Each run
  becomes a typed evidence receipt that is `ok` only when the exit code is 0 AND the typed result
  (`match`, `valid`, `eligible`, `ok`, `status: complete`) passes. A mismatch, an unknown or an
  inconsistent pair is a failed receipt, and every command here exits non-zero for it. This module
  keeps no second filesystem walker or comparator.
* Live exporters produce exactly the canonical export formats (E2/E3 PostgreSQL, E4 Redis):
  - PostgreSQL uses one read-only REPEATABLE READ transaction over a connection whose ONLY search
    path is the stated schema. A source `public` (the Windows control ledger) is allowed; a
    target `public` is refused.
  - Redis records PEXPIRETIME, the DUMP digest, stream entries, groups, consumers and the full PEL.
  - The Redis copy is DUMP/RESTORE ABSTTL without REPLACE, verified by the canonical
    `compare-redis`.
* The launcher files of deploy/aibox are written atomically: `host-activation.json`, derived from
  the coordinator's recorded intent, and `host-fence.json`.
* `SystemdHostTarget` controls only `zeus-aibox-*.service` units through `systemctl
  show|start|stop`. It never runs `reset-failed`, and a unit being active is never taken as
  consumption proof.

A connection string is read from a NAMED environment variable, never from argv, and never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import codex_harness
from codex_harness.adapters.commands import run_process
from codex_harness.adapters.host_delivery import STATE_FILE as HOST_STATE_FILE
from codex_harness.adapters.host_delivery import (
    STOP_POLL,
    STOP_TIMEOUT,
    DeliveryRefused,
    HostTargetBase,
    _utcnow,
    _write_json,
)
from codex_harness.domain.host_delivery import KIND_SYSTEMD, descriptor_digest
from codex_harness.domain.host_migration import (
    ACTIVATION_SCHEMA,
    CATALOG_SCHEMA,
    RESTORE_SCHEMA,
    SOURCE_PUBLIC,
    MigrationRefused,
    evidence_receipt,
    pg_coverage,
    schema_comparison,
    schema_subject,
)

STREAM_PAGE = 1000
CANONICAL_TIMEOUT = 3600
LAYOUT = ("repo", "worktrees", "releases", "runtime/control", "runtime/lanes", "artifacts", "backups", "tmp")
FENCE_FILE = "host-fence.json"
ACTIVATION_FILE = "host-activation.json"
IDENT = re.compile(r"[a-z_][a-z0-9_]{0,62}")
UNIT = re.compile(r"zeus-aibox-[a-z][a-z-]{0,40}")
# How the canonical tool states its typed result, per command (scripts/aibox_data/cli.py).
TYPED_RESULT = {"inventory": "ok", "pg-inventory": "ok", "verify-staged": "match", "compare-pg": "match",
                "compare-redis": "match", "pel-owners": "valid", "verify-artifacts": "valid",
                "gate": "eligible", "stage": "status"}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----- the canonical offline tooling --------------------------------------------------------------
def canonical_tool() -> Path:
    """`scripts/aibox_data` of the checkout this package runs from; refused when absent."""
    tool = Path(codex_harness.__file__).resolve().parents[2] / "scripts" / "aibox_data"
    if not (tool / "__main__.py").is_file():
        raise MigrationRefused("canonical_tool_unavailable", "scripts/aibox_data")
    return tool


def canonical_module(name: str):
    """In-process access to a canonical helper (e.g. the stream-entries digest) for the exporters."""
    import importlib

    scripts = str(canonical_tool().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module("aibox_data." + name)


def run_canonical(argv: list, *, check: str | None = None, subject=None, runner=subprocess.run) -> dict:
    """Run the canonical tool once; return its parsed result and the typed receipt of that run.

    `ok` requires exit 0 AND the command's typed result to pass. For a command writing `--out`, the
    typed result is the one-line `{"written", "ok"}` notice and the digest covers the written file.
    """
    command = argv[0]
    completed = runner([sys.executable, str(canonical_tool()), *argv], capture_output=True,
                       timeout=CANONICAL_TIMEOUT)
    stdout = completed.stdout if isinstance(completed.stdout, bytes) else (completed.stdout or "").encode()
    try:
        document = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        document = None
    field = TYPED_RESULT.get(command)
    typed = isinstance(document, dict) and (document.get(field) == "complete" if command == "stage"
                                            else document.get(field) is True)
    body = stdout
    if isinstance(document, dict) and "written" in document:
        try:
            body = Path(document["written"]).read_bytes()
        except OSError:
            typed = False
    ok = completed.returncode == 0 and typed
    # An exit 0 beside a failing typed result is recorded as a failure with a non-zero exit.
    exit_code = completed.returncode if completed.returncode != 0 else (0 if ok else 1)
    receipt = evidence_receipt(check or command, subject, exit_code, ok, _sha256_bytes(body))
    return {"receipt": receipt, "result": document, "canonical_exit": completed.returncode}


# ----- PostgreSQL ----------------------------------------------------------------------------------
def _schema(schema: str, role: str) -> str:
    if role not in ("source", "target") or not IDENT.fullmatch(schema):
        raise MigrationRefused("schema_invalid", "schema")
    if schema == SOURCE_PUBLIC and role != "source":
        raise MigrationRefused("public_schema", "schema")
    return schema


def schema_store(dsn: str, schema: str, role: str = "target"):
    """A PostgresStore whose only search path is `schema`; the lane rule refuses any fallback."""
    from codex_harness.adapters.fleet_runtime import lane_dsn, verify_lane_schema
    from codex_harness.adapters.store import PostgresStore
    from codex_harness.application.fleet import LaunchRefused

    _schema(schema, role)
    try:
        scoped = lane_dsn(dsn, schema)
        verify_lane_schema(scoped, schema)
    except LaunchRefused as exc:
        raise MigrationRefused(exc.reason_code, "schema") from None
    return PostgresStore(scoped)


def pg_export(dsn: str, schema: str, role: str, meta_out, rows_out, *, connect=None) -> dict:
    """The canonical E2 metadata and E3 `documents` JSONL of ONE schema, read-only.

    One READ ONLY, REPEATABLE READ transaction reads the server version, extensions, the schema's
    tables and sequences and every document row, so the metadata and rows describe one instant.
    A sequence that was never used (`last_value` NULL) is reported as 0.
    """
    import psycopg
    from psycopg.conninfo import make_conninfo

    _schema(schema, role)
    connect = connect or psycopg.connect
    rows = 0
    with connect(make_conninfo(dsn, options="-c search_path=" + schema), connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        if conn.execute("SELECT current_schema()").fetchone()[0] != schema:
            raise MigrationRefused("lane_schema_mismatch", "schema")
        meta = {"schema": "zeus.aibox-pg-inventory/1",
                "server_version_num": int(conn.execute("SHOW server_version_num").fetchone()[0]),
                "extensions": dict(conn.execute("SELECT extname, extversion FROM pg_extension ORDER BY 1").fetchall()),
                "schemas": {schema: {
                    "tables": [r[0] for r in conn.execute(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema=%s ORDER BY 1",
                        (schema,)).fetchall()],
                    "sequences": {r[0]: int(r[1] or 0) for r in conn.execute(
                        "SELECT sequencename, last_value FROM pg_sequences WHERE schemaname=%s ORDER BY 1",
                        (schema,)).fetchall()}}}}
        if "documents" not in meta["schemas"][schema]["tables"]:
            raise MigrationRefused("lane_schema_unprovisioned", "schema")
        with open(rows_out, "w", encoding="utf-8") as stream:
            for bucket, identifier, body in conn.execute(
                    "SELECT bucket, id, body FROM documents ORDER BY bucket, id"):
                stream.write(json.dumps({"bucket": bucket, "id": identifier, "body": body},
                                        sort_keys=True, ensure_ascii=False) + "\n")
                rows += 1
    Path(meta_out).write_text(json.dumps(meta, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return {"schema": schema, "role": role, "rows": rows, "tables": len(meta["schemas"][schema]["tables"])}


def _single_schema(inventory: dict, schema: str) -> dict:
    if schema not in (inventory.get("schemas") or {}):
        raise MigrationRefused("schema_missing", "inventory." + schema)
    return {**inventory, "schemas": {schema: inventory["schemas"][schema]}}


def pg_compare_schema(source: dict, target: dict, schema_map: dict, source_schema: str, delta=None,
                      *, runner=subprocess.run) -> dict:
    """ONE schema through the canonical `compare-pg`; a delta only for public -> control."""
    decision = schema_comparison(schema_map, source_schema, delta)
    with tempfile.TemporaryDirectory(prefix="zeus-pg-compare-") as work:
        work = Path(work)
        files = {"source": _single_schema(source, source_schema),
                 "target": _single_schema(target, decision["target_schema"]),
                 "map": {source_schema: decision["target_schema"]}}
        for name, document in files.items():
            (work / (name + ".json")).write_text(json.dumps(document), encoding="utf-8")
        argv = ["compare-pg", "--source", str(work / "source.json"), "--target", str(work / "target.json"),
                "--schema-map", str(work / "map.json")]
        if delta is not None:
            (work / "delta.json").write_text(json.dumps(delta), encoding="utf-8")
            argv += ["--delta", str(work / "delta.json")]
        return run_canonical(argv, subject=schema_subject(source_schema), runner=runner)


def pg_coverage_receipt(schema_map: dict, receipts: list) -> dict:
    report = pg_coverage(schema_map, receipts)
    digest = _sha256_bytes(json.dumps({"report": report, "receipts": receipts}, sort_keys=True).encode())
    return {"receipt": evidence_receipt("pg-coverage", None, 0 if report["ok"] else 1, report["ok"], digest),
            "result": report}


def _docker_pg(container: str, user: str, argv: list, runner=run_process, timeout: int = 3600):
    """One PostgreSQL client tool inside the database container over its local socket: no DSN, no
    password and no network endpoint ever reaches argv. The container's own local auth decides."""
    for value, name in ((container, "container"), (user, "user")):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
            raise MigrationRefused("pg_tool_invalid", name)
    return runner(["docker", "exec", container, *argv[:1], "-U", user, "-h", "/var/run/postgresql", *argv[1:]],
                  timeout=timeout)


def _archive_facts(container: str, user: str, path: str, runner) -> dict:
    listing = _docker_pg(container, user, ["pg_restore", "-l", path], runner)
    checksum = runner(["docker", "exec", container, "sha256sum", path], timeout=600)
    if listing.returncode or checksum.returncode:
        raise MigrationRefused("pg_archive_unreadable", "path")
    # The listing header carries the dump time; the entries alone identify the archive contents.
    entries = [line for line in (listing.stdout or "").splitlines() if line.strip() and not line.startswith(";")]
    return {"archive_sha256": (checksum.stdout or "").split()[0], "toc_entries": len(entries),
            "toc_sha256": _sha256_bytes("\n".join(entries).encode("utf-8"))}


def pg_dump_database(container: str, user: str, database: str, path: str, runner=run_process) -> dict:
    """ONE portable custom-format archive of the whole database: every schema, the extensions,
    tables, indexes, constraints, sequences and data (D3). Roles are globals and not included."""
    if not IDENT.fullmatch(database):
        raise MigrationRefused("pg_tool_invalid", "database")
    result = _docker_pg(container, user, ["pg_dump", "-d", database, "-Fc", "-f", path], runner)
    if result.returncode:
        raise MigrationRefused("pg_dump_failed", "exit_code")
    facts = _archive_facts(container, user, path, runner)
    if facts["toc_entries"] == 0:
        raise MigrationRefused("pg_dump_empty", "path")
    return {"database": database, "path": path, **facts}


CATALOG_SQL = {
    "schemas": """SELECT n.nspname, pg_get_userbyid(n.nspowner), n.nspacl::text, obj_description(n.oid, 'pg_namespace')
        FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema' ORDER BY 1""",
    "extensions": """SELECT e.extname, e.extversion, n.nspname FROM pg_extension e
        JOIN pg_namespace n ON n.oid = e.extnamespace ORDER BY 1""",
    "members": """SELECT DISTINCT coalesce(t.typname, p.proname, o.oprname) FROM pg_depend d
        LEFT JOIN pg_type t ON d.classid = 'pg_type'::regclass AND t.oid = d.objid
        LEFT JOIN pg_proc p ON d.classid = 'pg_proc'::regclass AND p.oid = d.objid
        LEFT JOIN pg_operator o ON d.classid = 'pg_operator'::regclass AND o.oid = d.objid
        WHERE d.deptype = 'e' AND coalesce(t.typname, p.proname, o.oprname) ~ '^[A-Za-z_][A-Za-z0-9_]*$'
        ORDER BY 1""",
    "relations": """SELECT n.nspname, c.relname, c.relkind::text, c.oid FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'm') AND n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'
          AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                          AND d.deptype = 'e') ORDER BY 1, 2""",
    "columns": """SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
        pg_get_expr(ad.adbin, ad.adrelid) FROM pg_attribute a
        LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
        WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum""",
    "indexes": """SELECT schemaname, indexname, indexdef FROM pg_indexes
        WHERE schemaname NOT LIKE 'pg\\_%' AND schemaname <> 'information_schema' ORDER BY 1, 2""",
    "constraints": """SELECT n.nspname, c.relname, k.conname, k.contype::text, pg_get_constraintdef(k.oid)
        FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema' ORDER BY 1, 2, 3""",
    "sequences": """SELECT schemaname, sequencename, data_type::text, last_value FROM pg_sequences
        WHERE schemaname NOT LIKE 'pg\\_%' ORDER BY 1, 2""",
    "views": """SELECT n.nspname, c.relname, pg_get_viewdef(c.oid) FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind = 'v'
          AND n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'
          AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e') ORDER BY 1, 2""",
    "functions": """SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid), md5(pg_get_functiondef(p.oid))
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE p.prokind IN ('f', 'p') AND n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'
          AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid
                          AND d.deptype = 'e') ORDER BY 1, 2, 3""",
    "triggers": """SELECT n.nspname, c.relname, t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE NOT t.tgisinternal AND n.nspname NOT LIKE 'pg\\_%' ORDER BY 1, 2, 3""",
}


def pg_catalog(dsn: str, database: str, *, connect=None) -> dict:
    """The whole-database catalog of one database, read in ONE read-only REPEATABLE READ snapshot.

    `search_path` is pg_catalog only, so every definition and type is printed schema-qualified and
    a renamed schema shows up as a different spelling rather than hiding behind a search path.
    Every table's rows are counted and digested (`record::text`, sorted), so documents, graph
    tables and schema_migrations are all covered, not just `documents`.
    """
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    if not IDENT.fullmatch(database):
        raise MigrationRefused("pg_tool_invalid", "database")
    connect = connect or psycopg.connect
    with connect(make_conninfo(dsn, dbname=database, options="-c search_path=pg_catalog"), connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        schemas = {name: {"owner": owner, "acl": acl, "comment": comment, **{k: {} if k == "relations" else []
                                                                             for k in ("relations", "indexes",
                                                                                       "constraints", "sequences",
                                                                                       "views", "functions",
                                                                                       "triggers")}}
                   for name, owner, acl, comment in conn.execute(CATALOG_SQL["schemas"]).fetchall()}
        if "zeus_migration_extensions" in schemas:
            raise MigrationRefused("rename_incomplete", "zeus_migration_extensions")
        for schema, name, kind, oid in conn.execute(CATALOG_SQL["relations"]).fetchall():
            columns = [list(row) for row in conn.execute(CATALOG_SQL["columns"], (oid,)).fetchall()]
            count, rows = conn.execute(sql.SQL(
                "SELECT count(*), encode(sha256(convert_to(coalesce(string_agg(t::text, E'\\n' ORDER BY t::text), ''),"
                " 'UTF8')), 'hex') FROM {}.{} t").format(sql.Identifier(schema), sql.Identifier(name))).fetchone()
            schemas[schema]["relations"][name] = {"kind": kind, "columns": columns, "rows": count, "rows_sha256": rows}
        for section in ("indexes", "constraints", "sequences", "views", "functions", "triggers"):
            for row in conn.execute(CATALOG_SQL[section]).fetchall():
                schemas[row[0]][section].append([str(value) if value is not None else None for value in row[1:]])
        extensions = [list(row) for row in conn.execute(CATALOG_SQL["extensions"]).fetchall()]
        members = [row[0] for row in conn.execute(CATALOG_SQL["members"]).fetchall()]
        version = int(conn.execute("SHOW server_version_num").fetchone()[0])
    return {"schema": CATALOG_SCHEMA, "database": database, "server_version_num": version,
            "extensions": extensions, "extension_members": members, "schemas": schemas}


def catalog_digest(catalog: dict) -> str:
    body = {k: v for k, v in catalog.items() if k != "database"}
    return _sha256_bytes(json.dumps(body, sort_keys=True).encode("utf-8"))


def _maintenance(dsn: str, connect):
    from psycopg.conninfo import make_conninfo

    return connect(make_conninfo(dsn, dbname="postgres"), connect_timeout=5, autocommit=True)


def _database_state(dsn: str, database: str, connect) -> dict:
    """Whether the database exists, its marker comment and whether it holds any user object."""
    from psycopg.conninfo import make_conninfo

    with _maintenance(dsn, connect) as conn:
        row = conn.execute("SELECT d.oid, shobj_description(d.oid, 'pg_database') FROM pg_database d "
                           "WHERE d.datname = %s", (database,)).fetchone()
    if row is None:
        return {"exists": False, "marker": None, "user_objects": 0}
    with connect(make_conninfo(dsn, dbname=database), connect_timeout=5) as conn:
        objects = conn.execute("""SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'""").fetchone()[0]
        schemas = conn.execute("""SELECT count(*) FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%'
            AND nspname NOT IN ('information_schema', 'public')""").fetchone()[0]
        extensions = conn.execute("SELECT count(*) FROM pg_extension WHERE extname <> 'plpgsql'").fetchone()[0]
    return {"exists": True, "marker": row[1], "user_objects": int(objects) + int(schemas) + int(extensions)}


def _rename(dsn: str, database: str, plan: dict, connect) -> None:
    """The renames, in ONE transaction; extensions homed in `public` are parked and re-homed.

    1. every extension in `public` moves to the parking schema;
    2. a `public` that is a rename TARGET (reverse) must now be empty and is dropped (RESTRICT);
    3. the planned renames run;
    4. a missing `public` is recreated as the standard one (owner pg_database_owner, USAGE to PUBLIC);
    5. the parked extensions return to `public` and the parking schema is dropped.
    Any failure rolls the whole transaction back, leaving the restored names untouched.
    """
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    home, parking = plan["extension_home"], plan["parking"]
    with connect(make_conninfo(dsn, dbname=database), connect_timeout=5) as conn:
        with conn.transaction():
            parked = [row[0] for row in conn.execute(
                "SELECT e.extname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
                "WHERE n.nspname = %s ORDER BY 1", (home,)).fetchall()]
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(parking)))
            for name in parked:
                conn.execute(sql.SQL("ALTER EXTENSION {} SET SCHEMA {}").format(sql.Identifier(name),
                                                                                sql.Identifier(parking)))
            if any(new == home for _, new in plan["renames"]):
                conn.execute(sql.SQL("DROP SCHEMA {} RESTRICT").format(sql.Identifier(home)))
            for old, new in plan["renames"]:
                conn.execute(sql.SQL("ALTER SCHEMA {} RENAME TO {}").format(sql.Identifier(old), sql.Identifier(new)))
            exists = conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (home,)).fetchone()
            if exists is None:
                conn.execute(sql.SQL("CREATE SCHEMA {} AUTHORIZATION pg_database_owner").format(sql.Identifier(home)))
                conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO PUBLIC").format(sql.Identifier(home)))
                conn.execute(sql.SQL("COMMENT ON SCHEMA {} IS 'standard public schema'").format(sql.Identifier(home)))
            for name in parked:
                conn.execute(sql.SQL("ALTER EXTENSION {} SET SCHEMA {}").format(sql.Identifier(name),
                                                                                sql.Identifier(home)))
            conn.execute(sql.SQL("DROP SCHEMA {} RESTRICT").format(sql.Identifier(parking)))


ACL_ITEM = re.compile(r"^(?P<grantee>[A-Za-z_][A-Za-z0-9_]*|)=(?P<privs>[UC]+)/(?P<grantor>[A-Za-z_][A-Za-z0-9_]*)$")


def _reapply_schema_acls(dsn: str, database: str, source_catalog: dict, connect) -> list:
    """Schema ACLs pg_dump leaves out because they equal the recorded initial privileges.

    The schema that was `public` keeps public's initial ACL through a rename, and pg_dump does not
    emit privileges equal to `pg_init_privs`, so a restored copy of it comes back with a NULL ACL.
    Only a restored ACL that is NULL is filled in, only from the source catalog's own aclitems, only
    USAGE/CREATE granted by the schema owner; an existing ACL is never replaced. The exact catalog
    comparison that follows still decides whether the restore matches.
    """
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    applied = []
    with connect(make_conninfo(dsn, dbname=database), connect_timeout=5) as conn:
        with conn.transaction():
            for name, body in sorted(source_catalog["schemas"].items()):
                wanted = body.get("acl")
                row = conn.execute("SELECT nspacl::text, pg_get_userbyid(nspowner) FROM pg_namespace "
                                   "WHERE nspname = %s", (name,)).fetchone()
                if row is None or row[0] is not None or not wanted:
                    continue
                items = [item for item in wanted.strip("{}").split(",") if item]
                parsed = [ACL_ITEM.fullmatch(item) for item in items]
                if any(match is None or match["grantor"] != row[1] for match in parsed):
                    raise MigrationRefused("schema_acl_unsupported", "schemas." + name)
                for match in parsed:
                    if match["grantee"] == row[1]:
                        continue  # the owner's entry is materialized by the first grant
                    privileges = sql.SQL(", ").join(sql.SQL({"U": "USAGE", "C": "CREATE"}[p]) for p in match["privs"])
                    grantee = sql.SQL("PUBLIC") if match["grantee"] == "" else sql.Identifier(match["grantee"])
                    conn.execute(sql.SQL("GRANT {} ON SCHEMA {} TO {}").format(privileges, sql.Identifier(name), grantee))
                applied.append(name)
    return applied


def _write_receipt(path: Path, receipt: dict) -> None:
    _atomic_write(path.parent, path.name, receipt)


def pg_restore_database(container: str, user: str, dsn: str, database: str, archive: str, archive_sha256: str,
                        source_catalog: dict, schema_map: dict, receipt_path, *, reverse: bool = False,
                        recover: bool = False, runner=run_process, connect=None) -> dict:
    """Whole-archive restore into a NEW dedicated database, verified, then the atomic renames (D3).

    * The database must not exist. It is created from template0, owned by `user`, and marked with
      the restore id; the receipt (state `created`) is written before pg_restore runs.
    * `pg_restore --exit-on-error --single-transaction` restores everything or nothing. Its exit 0
      is not believed: the restored catalog must equal the source catalog exactly (every table's
      rows, columns, indexes, constraints, sequences, extensions) before any rename.
    * The renames run in one transaction (`_rename`); the renamed catalog must equal the source
      catalog through the schema map.
    * The same receipt replays read-only once `renamed`: the catalog is re-read and must match.
      An existing database without that receipt refuses (`target_occupied`). An interrupted
      restore resumes only with `recover=True`, into a database carrying this restore's marker and
      no user object; nothing is ever dropped or cleaned.
    """
    import psycopg

    from codex_harness.domain.host_migration import compare_catalogs, rename_plan, restore_id

    connect = connect or psycopg.connect
    if not IDENT.fullmatch(database) or database in ("postgres", "template0", "template1"):
        raise MigrationRefused("pg_tool_invalid", "database")
    plan = rename_plan(source_catalog, schema_map, reverse=reverse)
    identity = restore_id(database, archive_sha256, catalog_digest(source_catalog), plan)
    marker = "zeus-host-migration-restore:" + identity
    receipt_path = Path(receipt_path)
    receipt = json.loads(receipt_path.read_text("utf-8")) if receipt_path.exists() else None
    if receipt is not None and receipt.get("restore_id") != identity:
        raise MigrationRefused("restore_conflict", "receipt")
    state = _database_state(dsn, database, connect)
    if receipt is not None and receipt["state"] == "renamed":
        observed = pg_catalog(dsn, database, connect=connect)
        if not state["exists"] or catalog_digest(observed) != receipt["renamed_catalog_sha256"]:
            raise MigrationRefused("restore_replay_mismatch", "database")
        return {**receipt, "cached": True}
    facts = _archive_facts(container, user, archive, runner)
    if facts["archive_sha256"] != archive_sha256:
        raise MigrationRefused("archive_digest_mismatch", "archive")
    if facts["toc_entries"] == 0:
        raise MigrationRefused("pg_dump_empty", "archive")
    base = {"schema": RESTORE_SCHEMA, "restore_id": identity, "database": database, "archive_sha256": archive_sha256,
            "toc_sha256": facts["toc_sha256"], "toc_entries": facts["toc_entries"],
            "source_catalog_sha256": catalog_digest(source_catalog), "plan": plan}
    if state["exists"]:
        known = receipt is not None and receipt["state"] in ("created", "restore_failed")
        if not (recover and known and state["marker"] == marker and state["user_objects"] == 0):
            raise MigrationRefused("target_occupied", "database")
    else:
        if receipt is not None and receipt["state"] != "created":
            raise MigrationRefused("restore_receipt_without_database", "receipt")
        from psycopg import sql

        with _maintenance(dsn, connect) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0").format(
                sql.Identifier(database), sql.Identifier(user)))
            conn.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(database), sql.Literal(marker)))
        _write_receipt(receipt_path, {**base, "state": "created", "at": _utcnow()})
    restored = _docker_pg(container, user, ["pg_restore", "--exit-on-error", "--single-transaction",
                                            "-d", database, archive], runner)
    if restored.returncode:
        _write_receipt(receipt_path, {**base, "state": "restore_failed", "exit_code": restored.returncode,
                                      "at": _utcnow()})
        raise MigrationRefused("pg_restore_failed", "exit_code")
    acls = _reapply_schema_acls(dsn, database, source_catalog, connect)
    base["acl_reapplied"] = acls
    identity_map = {name: name for name in schema_map}
    before = compare_catalogs(source_catalog, pg_catalog(dsn, database, connect=connect), identity_map)
    if not before["match"] or before["tables"] == 0:
        _write_receipt(receipt_path, {**base, "state": "restored", "verified": False, "at": _utcnow()})
        raise MigrationRefused("restore_contents_mismatch", "database")
    _write_receipt(receipt_path, {**base, "state": "restored", "verified": True, "at": _utcnow()})
    _rename(dsn, database, plan, connect)
    renamed = pg_catalog(dsn, database, connect=connect)
    after = compare_catalogs(source_catalog, renamed, schema_map)
    if not after["match"]:
        raise MigrationRefused("renamed_contents_mismatch", "database")
    final = {**base, "state": "renamed", "verified": True, "renamed_catalog_sha256": catalog_digest(renamed),
             "tables": after["tables"], "rows": after["rows"], "schemas": after["schemas"], "at": _utcnow()}
    _write_receipt(receipt_path, final)
    return {**final, "cached": False}


# ----- Redis: the canonical E4 inventory --------------------------------------------------------
def _text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _server_ms(client) -> int:
    seconds, micros = client.time()
    return int(seconds) * 1000 + int(micros) // 1000


def _stream(client, key: str, entries_sha256) -> dict:
    info = client.xinfo_stream(key)
    groups = {}
    for group in client.xinfo_groups(key) or []:
        name = _text(group["name"])
        consumers = {_text(c["name"]): int(c["pending"]) for c in client.xinfo_consumers(key, name) or []}
        pending = client.xpending_range(key, name, min="-", max="+", count=1000000) or []
        groups[name] = {"last_delivered_id": _text(group["last-delivered-id"]), "consumers": consumers,
                        "pending": [{"id": _text(p["message_id"]), "consumer": _text(p["consumer"]),
                                     "deliveries": int(p["times_delivered"])} for p in pending]}
    entries, cursor = [], "-"
    while True:
        page = client.xrange(key, min=cursor, max="+", count=STREAM_PAGE)
        rows = [[_text(i), {_text(k): _text(v) for k, v in fields.items()}] for i, fields in page]
        if cursor != "-" and rows:
            rows = rows[1:]  # the inclusive start repeats the last entry of the previous page
        entries.extend(rows)
        if len(page) < STREAM_PAGE:
            break
        cursor = _text(page[-1][0])
    return {"length": int(info["length"]), "last_generated_id": _text(info["last-generated-id"]),
            "entries_sha256": entries_sha256(entries), "groups": groups}


def redis_inventory(client, namespaces) -> dict:
    """The canonical E4 document for the namespaces: keys via SCAN MATCH <ns>:* only."""
    entries_sha256 = canonical_module("contracts").stream_entries_sha256
    keys, streams = {}, {}
    names = set()
    for namespace in namespaces:
        if client.exists(namespace):
            names.add(namespace)
        names.update(_text(k) for k in client.scan_iter(match=namespace + ":*", count=1000))
    for key in sorted(names):
        kind = _text(client.type(key))
        if kind == "none":
            continue  # expired between SCAN and TYPE; the seal is taken on a quiescent instance
        expiry = int(client.execute_command("PEXPIRETIME", key))
        meta = {"type": kind, "expire_at_ms": expiry if expiry >= 0 else None}
        if kind == "stream":
            streams[key] = _stream(client, key, entries_sha256)
        else:
            meta["dump_sha256"] = _sha256_bytes(client.dump(key) or b"")
        keys[key] = meta
    return {"schema": "zeus.aibox-redis-inventory/1", "captured_at_ms": _server_ms(client),
            "namespace_prefixes": list(namespaces), "keys": keys, "streams": streams}


def copy_redis(source, target, keys) -> dict:
    """DUMP/RESTORE ABSTTL of exactly `keys`; resumable; never REPLACE, never extend an expiry.

    A key already on the target is left alone; whether it equals the source is decided afterwards
    by the canonical `compare-redis`, never assumed here.
    """
    restored = present = expired = 0
    for key in keys:
        if target.exists(key):
            present += 1
            continue
        payload = source.dump(key)
        if payload is None:
            raise MigrationRefused("redis_source_missing", "key")
        expiry = int(source.execute_command("PEXPIRETIME", key))
        if 0 <= expiry <= _server_ms(target):
            expired += 1  # really expired during the downtime; reported, not revived
            continue
        target.restore(key, expiry if expiry >= 0 else 0, payload, absttl=expiry >= 0)
        restored += 1
    return {"restored": restored, "already_present": present, "expired_in_downtime": expired, "keys": len(keys)}


# ----- launcher files (deploy/aibox INTEGRATION-CONTRACT s2) --------------------------------------
def _atomic_write(directory: Path, name: str, document: dict) -> str:
    """temp file in the same directory, fsync, rename, fsync the directory; returns the sha256."""
    data = (json.dumps(document, sort_keys=True, indent=1) + "\n").encode("utf-8")
    if not directory.is_dir() or directory.is_symlink():
        raise MigrationRefused("control_dir_unavailable", "control_dir")
    descriptor, temporary = tempfile.mkstemp(prefix="." + name + ".", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / name)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
    handle = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)
    return _sha256_bytes(data)


def write_activation(control_dir, document: dict) -> dict:
    """Write the coordinator-derived `host-activation.json`; refused beside a host fence."""
    control = Path(control_dir)
    if not (isinstance(document, dict) and document.get("schema") == ACTIVATION_SCHEMA and document.get("intent_id")):
        raise MigrationRefused("activation_receipt_invalid", "document")
    if os.path.lexists(control / FENCE_FILE):
        raise MigrationRefused("host_fenced", FENCE_FILE)
    sha = _atomic_write(control, ACTIVATION_FILE, document)
    return {"written": str(control / ACTIVATION_FILE), "sha256": sha, "state": document["state"],
            "intent_id": document["intent_id"]}


def write_fence(control_dir, migration_id: str, reason: str) -> dict:
    """`host-fence.json`: its existence refuses every launcher role on this host, monitors included."""
    control = Path(control_dir)
    sha = _atomic_write(control, FENCE_FILE, {"migration_id": migration_id, "reason": reason, "at": _utcnow()})
    return {"written": str(control / FENCE_FILE), "sha256": sha}


# ----- the Linux systemd service target ----------------------------------------------------------
class SystemdHostTarget(HostTargetBase):
    """An owner-installed `zeus-aibox-*` systemd unit, controlled by name only.

    Control rights are restricted to `systemctl show|start|stop` of the registered unit; the unit
    name must be a `zeus-aibox-*` service (the polkit/sudoers rule the owner grants is scoped the
    same way), and `reset-failed` is never issued: a unit past its start limit stays failed for a
    human. `running` reads `ActiveState`; an unknown state raises instead of reading as stopped.
    A start requires the launcher's `host-activation.json` to be present and bound to an intent
    (the launcher itself re-checks host id and revision), and the unit's InvocationID is recorded.
    `active` is not consumption proof: the startup receipt decides that. Docker containers the
    service started are not in its cgroup and are reconciled by run label separately.
    """

    kind = KIND_SYSTEMD

    def __init__(self, *, runner=run_process, timeout: int = 60, control_dir=None, control=None, **kwargs):
        super().__init__(**kwargs)
        self.runner, self.timeout = runner, timeout
        # `control` is the factory's validated `systemd_control_dir` result; `control_dir` a direct path.
        control = control or {"control_dir": control_dir,
                              "reason_code": None if control_dir else "control_dir_unconfigured"}
        self.control_dir, self.control_reason = control["control_dir"], control["reason_code"]

    @staticmethod
    def unit(target: dict) -> str:
        if not UNIT.fullmatch(target["service"]):
            raise DeliveryRefused("target_unit_not_allowed", "service")
        return target["service"] + ".service"

    def _show(self, target: dict) -> dict:
        result = self.runner(["systemctl", "show", self.unit(target), "-p", "ActiveState", "-p", "MainPID",
                              "-p", "InvocationID"], timeout=self.timeout)
        if result.returncode:
            raise RuntimeError("systemd unit state unavailable")
        return dict(line.split("=", 1) for line in (result.stdout or "").splitlines() if "=" in line)

    def running(self, target: dict) -> bool:
        state = self._show(target).get("ActiveState")
        if state in ("active", "activating", "deactivating", "reloading"):
            return True
        if state in ("inactive", "failed"):
            return False
        raise RuntimeError("systemd unit state unavailable")

    def stop(self, target: dict) -> dict:
        invocation = self._show(target).get("InvocationID") or None
        result = self.runner(["systemctl", "stop", self.unit(target)], timeout=self.timeout)
        deadline = time.monotonic() + STOP_TIMEOUT
        while self.running(target) and time.monotonic() < deadline:
            time.sleep(STOP_POLL)
        return {"stopped": not self.running(target), "exit_code": result.returncode, "invocation_id": invocation}

    def _launch(self, target: dict, descriptor: dict, context) -> dict:
        if not self.control_dir:
            raise DeliveryRefused(self.control_reason or "control_dir_unconfigured", "control_dir")
        control = Path(self.control_dir)
        if not (control / ACTIVATION_FILE).is_file():
            raise DeliveryRefused("activation_receipt_required", "control_dir")
        if os.path.lexists(control / FENCE_FILE):
            raise DeliveryRefused("host_fenced", "control_dir")
        activation = json.loads((control / ACTIVATION_FILE).read_text("utf-8"))
        if activation.get("schema") != ACTIVATION_SCHEMA or not activation.get("intent_id"):
            raise DeliveryRefused("activation_receipt_invalid", "control_dir")
        result = self.runner(["systemctl", "start", self.unit(target)], timeout=self.timeout)
        if result.returncode:
            raise RuntimeError("systemd unit could not be started")
        record = {"service": target["service"], "started_at": _utcnow(),
                  "descriptor_sha256": descriptor_digest(descriptor),
                  "invocation_id": self._show(target).get("InvocationID") or None,
                  "intent_id": activation["intent_id"]}
        _write_json(self.path(target, HOST_STATE_FILE), record)
        return {"started": True, "service": target["service"], "launch": record}


# ----- target layout -----------------------------------------------------------------------------
def prepare_layout(root, *, apply: bool = False) -> dict:
    """The /srv/zeus directory layout; a dry run by default. Existing directories are kept as they
    are; a path that exists as something other than a directory refuses."""
    root = Path(root)
    if not root.is_absolute():
        raise MigrationRefused("layout_invalid", "root")
    rows = []
    for path in (root / part for part in LAYOUT):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise MigrationRefused("layout_conflict", str(path.relative_to(root)))
        state = "present" if path.is_dir() else "created" if apply else "would_create"
        if apply and state == "created":
            path.mkdir(mode=0o750, parents=True)
        rows.append({"path": path.relative_to(root).as_posix(), "state": state})
    return {"root": str(root), "applied": apply, "directories": rows}


# ----- CLI ---------------------------------------------------------------------------------------
def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MigrationRefused("environment_missing", name)
    return value


def _redis_client(url_env: str | None, socket: str | None):
    from redis import Redis

    if socket:
        return Redis(unix_socket_path=socket, socket_timeout=10)
    return Redis.from_url(_env(url_env), socket_timeout=10)


def _coordinator(args):
    from codex_harness.application.host_migration import HostMigrations

    return HostMigrations(schema_store(_env(args.dsn_env), args.schema, "target"))


def _read(path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _checked(outcome: dict) -> tuple[dict, bool]:
    """A delegated run: the receipt decides the exit, the result is shown beside it unchanged."""
    return outcome, outcome["receipt"]["ok"]


def execute(args) -> tuple[dict, bool]:
    command = args.command
    if command == "validate":
        from codex_harness.domain.host_migration import manifest_digest, validate_manifest

        manifest = validate_manifest(_read(args.file))
        return {"valid": True, "migration_id": manifest["migration_id"],
                "manifest_sha256": manifest_digest(manifest)}, True
    if command in ("plan", "advance", "checkpoint", "intend-activation"):
        coordinator = _coordinator(args)
        method = {"plan": coordinator.plan, "advance": coordinator.advance, "checkpoint": coordinator.checkpoint,
                  "intend-activation": coordinator.intend_activation}[command]
        return method(_read(args.file)), True
    if command == "status":
        return _coordinator(args).status(args.migration_id), True
    if command == "rollback-plan":
        return _coordinator(args).rollback_plan(args.migration_id), True
    if command == "activation-write":
        document = _coordinator(args).activation_document(args.migration_id)
        return write_activation(args.control_dir, document), True
    if command == "fence-write":
        return write_fence(args.control_dir, args.migration_id, args.reason), True
    if command == "artifact-inventory":
        argv = ["inventory", "--migration-id", args.migration_id, "--out", args.out]
        for root in args.root:
            argv += ["--root", root]
        return _checked(run_canonical(argv))
    if command == "artifact-stage":
        return _checked(run_canonical(["stage", "--manifest", args.manifest, "--root-id", args.root_id,
                                       "--source", args.source, "--staging", args.staging, "--work", args.work],
                                      subject="root=" + args.root_id))
    if command == "artifact-verify":
        argv = ["verify-staged", "--manifest", args.manifest, "--root-id", args.root_id, "--staging", args.staging]
        if args.work:
            argv += ["--work", args.work]
        return _checked(run_canonical(argv, subject="root=" + args.root_id))
    if command == "pg-export":
        return pg_export(_env(args.dsn_env), args.schema, args.role, args.meta_out, args.rows_out), True
    if command == "pg-inventory":
        argv = ["pg-inventory", "--meta", args.meta, "--role", args.role, "--out", args.out]
        for export in args.export:
            argv += ["--export", export]
        return _checked(run_canonical(argv))
    if command == "pg-compare-schema":
        return _checked(pg_compare_schema(_read(args.source), _read(args.target), _read(args.schema_map),
                                          args.source_schema, _read(args.delta) if args.delta else None))
    if command == "pg-coverage":
        return _checked(pg_coverage_receipt(_read(args.schema_map), [_read(path) for path in args.receipt]))
    if command == "pg-dump-db":
        return pg_dump_database(args.container, args.user, args.database, args.path), True
    if command == "pg-catalog":
        catalog = pg_catalog(_env(args.dsn_env), args.database)
        Path(args.out).write_text(json.dumps(catalog, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        return {"written": args.out, "catalog_sha256": catalog_digest(catalog),
                "schemas": len(catalog["schemas"])}, True
    if command == "pg-compare-catalog":
        from codex_harness.domain.host_migration import compare_catalogs

        report = compare_catalogs(_read(args.source), _read(args.target), _read(args.schema_map))
        return {"result": report, "receipt": evidence_receipt(
            "pg-catalog", None, 0 if report["match"] else 1, report["match"],
            _sha256_bytes(json.dumps(report, sort_keys=True).encode()))}, report["match"]
    if command == "pg-restore-db":
        return pg_restore_database(args.container, args.user, _env(args.dsn_env), args.database, args.path,
                                   args.archive_sha256, _read(args.source_catalog), _read(args.schema_map),
                                   args.receipt, reverse=args.reverse, recover=args.recover), True
    if command == "redis-inventory":
        document = redis_inventory(_redis_client(args.url_env, args.socket), args.namespace)
        Path(args.out).write_text(json.dumps(document, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        return {"written": args.out, "keys": len(document["keys"]), "streams": len(document["streams"])}, True
    if command == "redis-copy":
        source = _redis_client(args.source_url_env, args.source_socket)
        target = _redis_client(args.target_url_env, args.target_socket)
        before = redis_inventory(source, args.namespace)
        copied = copy_redis(source, target, sorted(before["keys"]))
        after = redis_inventory(target, args.namespace)
        with tempfile.TemporaryDirectory(prefix="zeus-redis-compare-") as work:
            for name, document in (("source", before), ("target", after)):
                (Path(work) / (name + ".json")).write_text(json.dumps(document), encoding="utf-8")
            outcome = run_canonical(["compare-redis", "--source", str(Path(work) / "source.json"),
                                     "--target", str(Path(work) / "target.json")])
        return {**outcome, "copy": copied}, outcome["receipt"]["ok"]
    if command == "compare-redis":
        return _checked(run_canonical(["compare-redis", "--source", args.source, "--target", args.target]))
    if command == "pel-owners":
        return _checked(run_canonical(["pel-owners", "--inventory", args.inventory, "--owners", args.owners]))
    if command == "gate":
        return _checked(run_canonical(["gate", args.gate, "--evidence", args.evidence], check="gate-" + args.gate))
    if command == "prepare-layout":
        return prepare_layout(args.root, apply=args.apply), True
    raise MigrationRefused("command_unknown", "command")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m codex_harness.adapters.host_migration",
                                   description="Host migration coordinator boundary (INV-HOST-MIGRATION-001). "
                                               "Connection strings come from named environment variables only; "
                                               "offline checks delegate to scripts/aibox_data.")
    sub = root.add_subparsers(dest="command", required=True)

    def store_args(command):
        command.add_argument("--dsn-env", default="HARNESS_DATABASE_URL", help="Env var NAME holding the DSN")
        command.add_argument("--schema", required=True, help="The coordinator schema (never public)")

    sub.add_parser("validate").add_argument("--file", required=True)
    for name in ("plan", "advance", "checkpoint", "intend-activation"):
        command = sub.add_parser(name)
        command.add_argument("--file", required=True)
        store_args(command)
    for name in ("status", "rollback-plan", "activation-write"):
        command = sub.add_parser(name)
        command.add_argument("--migration-id", required=True)
        store_args(command)
        if name == "activation-write":
            command.add_argument("--control-dir", required=True)
    command = sub.add_parser("fence-write")
    command.add_argument("--control-dir", required=True)
    command.add_argument("--migration-id", required=True)
    command.add_argument("--reason", required=True)
    command = sub.add_parser("artifact-inventory")
    command.add_argument("--migration-id", required=True)
    command.add_argument("--root", action="append", required=True, metavar="ID=PATH")
    command.add_argument("--out", required=True)
    for name in ("artifact-stage", "artifact-verify"):
        command = sub.add_parser(name)
        command.add_argument("--manifest", required=True)
        command.add_argument("--root-id", required=True)
        command.add_argument("--staging", required=True)
        command.add_argument("--work", required=name == "artifact-stage")
        if name == "artifact-stage":
            command.add_argument("--source", required=True)
    command = sub.add_parser("pg-export")
    command.add_argument("--dsn-env", required=True)
    command.add_argument("--schema", required=True)
    command.add_argument("--role", choices=["source", "target"], required=True)
    command.add_argument("--meta-out", required=True)
    command.add_argument("--rows-out", required=True)
    command = sub.add_parser("pg-inventory")
    command.add_argument("--meta", required=True)
    command.add_argument("--export", action="append", required=True, metavar="SCHEMA=JSONL")
    command.add_argument("--role", choices=["source", "target"], required=True)
    command.add_argument("--out", required=True)
    command = sub.add_parser("pg-compare-schema")
    command.add_argument("--source", required=True)
    command.add_argument("--target", required=True)
    command.add_argument("--schema-map", required=True)
    command.add_argument("--source-schema", required=True)
    command.add_argument("--delta")
    command = sub.add_parser("pg-coverage")
    command.add_argument("--schema-map", required=True)
    command.add_argument("--receipt", action="append", required=True, help="compare-pg receipt JSON; repeatable")
    command = sub.add_parser("pg-dump-db", help="Whole-database custom archive (D3)")
    command.add_argument("--container", required=True)
    command.add_argument("--user", required=True)
    command.add_argument("--database", required=True)
    command.add_argument("--path", required=True, help="Archive path inside the container")
    command = sub.add_parser("pg-catalog", help="Whole-database catalog with every table's row digest")
    command.add_argument("--dsn-env", required=True)
    command.add_argument("--database", required=True)
    command.add_argument("--out", required=True)
    command = sub.add_parser("pg-compare-catalog")
    command.add_argument("--source", required=True)
    command.add_argument("--target", required=True)
    command.add_argument("--schema-map", required=True)
    command = sub.add_parser("pg-restore-db", help="Restore into a NEW dedicated DB, verify, rename atomically")
    command.add_argument("--container", required=True)
    command.add_argument("--user", required=True)
    command.add_argument("--dsn-env", required=True, help="Env var NAME of the target server DSN")
    command.add_argument("--database", required=True)
    command.add_argument("--path", required=True, help="Archive path inside the container")
    command.add_argument("--archive-sha256", required=True)
    command.add_argument("--source-catalog", required=True)
    command.add_argument("--schema-map", required=True)
    command.add_argument("--receipt", required=True)
    command.add_argument("--reverse", action="store_true", help="R1: the inverse map back to source names")
    command.add_argument("--recover", action="store_true",
                         help="Resume an interrupted restore of THIS receipt into its own empty database")
    command = sub.add_parser("redis-inventory")
    command.add_argument("--url-env")
    command.add_argument("--socket")
    command.add_argument("--namespace", action="append", required=True)
    command.add_argument("--out", required=True)
    command = sub.add_parser("redis-copy")
    for side in ("source", "target"):
        command.add_argument("--" + side + "-url-env")
        command.add_argument("--" + side + "-socket")
    command.add_argument("--namespace", action="append", required=True)
    command = sub.add_parser("compare-redis")
    command.add_argument("--source", required=True)
    command.add_argument("--target", required=True)
    command = sub.add_parser("pel-owners")
    command.add_argument("--inventory", required=True)
    command.add_argument("--owners", required=True)
    command = sub.add_parser("gate")
    command.add_argument("gate", choices=["r0", "r1", "c"])
    command.add_argument("--evidence", required=True)
    command = sub.add_parser("prepare-layout")
    command.add_argument("--root", required=True)
    command.add_argument("--apply", action="store_true")
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        result, ok = execute(args)
    except MigrationRefused as exc:
        print(json.dumps({"refused": exc.reason_code, "field": exc.field}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["SystemdHostTarget", "canonical_module", "canonical_tool", "copy_redis", "execute", "main", "parser",
           "pg_catalog", "pg_compare_schema", "pg_coverage_receipt", "pg_dump_database", "pg_export",
           "pg_restore_database", "prepare_layout",
           "redis_inventory", "run_canonical", "schema_store", "write_activation", "write_fence"]
