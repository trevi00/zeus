"""Host-side observation, copy and service mechanics of a host migration (INV-HOST-MIGRATION-001).

@invariant INV-HOST-MIGRATION-001

Nothing here decides a migration: `domain.host_migration` holds the policy and
`application.host_migration.HostMigrations` records every transition and checkpoint. This module
only observes and copies, and reports what it saw with the whole denominator:

* artifacts: a hash inventory that never follows a symlink or a special file (each is reported as
  an anomaly), and a resumable copy that re-hashes the source, writes through a temporary file,
  fsyncs, publishes with a no-overwrite link and refuses a differing destination rather than
  replacing content-addressed bytes;
* PostgreSQL: per-bucket count and digest of the `documents` table as the store reads it, over a
  connection whose ONLY search path is the stated schema (the lane rule of `fleet_runtime`);
* Redis: key/type/value digest, absolute expiry (`PEXPIRETIME`), stream length, last generated id,
  groups, last delivered ids and the pending entries list with consumer and delivery count; the copy
  is `DUMP`/`RESTORE ... ABSTTL` of an allowlisted key set, which carries a stream's groups and PEL.
  Entries are never re-added with XADD, a TTL is never extended and an existing key is never
  replaced;
* the Linux service target: an owner-installed systemd unit started and stopped through
  `systemctl`, sharing the descriptor/receipt/drain lifecycle of every HostDelivery target.

A connection string is read from a NAMED environment variable, never from argv, and never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.host_delivery import STATE_FILE as HOST_STATE_FILE
from codex_harness.adapters.host_delivery import (
    STOP_POLL,
    STOP_TIMEOUT,
    HostTargetBase,
    _utcnow,
    _write_json,
)
from codex_harness.domain.host_delivery import KIND_SYSTEMD, descriptor_digest
from codex_harness.domain.host_migration import (
    MigrationRefused,
    compare_buckets,
    compare_redis,
    compare_trees,
    render_unit,
    tree_digest,
)
from codex_harness.domain.model import canonical, digest

CHUNK = 1024 * 1024
STREAM_PAGE = 1000
LAYOUT = ("repo", "worktrees", "releases", "runtime/control", "runtime/lanes", "artifacts", "backups", "tmp")


# ----- artifacts ---------------------------------------------------------------------------------
def _sha256(path: Path) -> tuple[str, int]:
    h, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def artifact_inventory(root) -> dict:
    """Every regular file below `root`: relative POSIX path -> {sha256, bytes}.

    Symlinks, special files, unreadable entries and names that collide when case-folded (which a
    Windows source cannot hold apart) are anomalies; they are listed, never followed or merged.
    """
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise MigrationRefused("artifact_root_unavailable", "root")
    files, anomalies, folded = {}, [], {}
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in sorted(dirnames):
            if (base / name).is_symlink():
                anomalies.append("symlink:" + (base / name).relative_to(root).as_posix())
        for name in sorted(filenames):
            path = base / name
            relative = path.relative_to(root).as_posix()
            try:
                mode = path.lstat().st_mode
            except OSError:
                anomalies.append("unreadable:" + relative)
                continue
            if stat.S_ISLNK(mode):
                anomalies.append("symlink:" + relative)
                continue
            if not stat.S_ISREG(mode):
                anomalies.append("special:" + relative)
                continue
            try:
                sha, size = _sha256(path)
            except OSError:
                anomalies.append("unreadable:" + relative)
                continue
            files[relative] = {"sha256": sha, "bytes": size}
            key = relative.casefold()
            if key in folded and folded[key] != relative:
                anomalies.append("case_collision:" + relative)
            folded.setdefault(key, relative)
    return {"entries": len(files), "bytes": sum(row["bytes"] for row in files.values()),
            "tree_sha256": tree_digest(files), "files": files, "anomalies": sorted(anomalies)}


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":  # pragma: no cover - directory handles are not fsync-able on Windows
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def copy_artifacts(source_root, target_root, inventory: dict) -> dict:
    """Copy exactly the inventoried files; resumable, never overwriting, verified by hash.

    A destination that already holds the same bytes is skipped (the resume case); one that holds
    different bytes refuses by path; a source whose bytes no longer match the sealed inventory
    refuses (it changed after the seal). Nothing is deleted on either side.
    """
    source_root, target_root = Path(source_root), Path(target_root)
    if inventory.get("anomalies"):
        raise MigrationRefused("artifact_anomalies", "inventory.anomalies")
    copied = skipped = 0
    for relative, row in sorted(inventory["files"].items()):
        source, target = source_root / relative, target_root / relative
        if target.is_symlink():
            raise MigrationRefused("artifact_target_symlink", relative)
        if target.exists():
            if _sha256(target) != (row["sha256"], row["bytes"]):
                raise MigrationRefused("artifact_target_different", relative)
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / (".zeus-copy-" + row["sha256"][:16] + ".tmp")
        h, size = hashlib.sha256(), 0
        with source.open("rb") as reader, temporary.open("wb") as writer:
            while chunk := reader.read(CHUNK):
                h.update(chunk)
                size += len(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if (h.hexdigest(), size) != (row["sha256"], row["bytes"]):
            temporary.unlink()
            raise MigrationRefused("artifact_source_changed", relative)
        try:
            os.link(temporary, target)  # fails if the name appeared meanwhile: never overwrite
        except FileExistsError:
            raise MigrationRefused("artifact_target_appeared", relative) from None
        finally:
            temporary.unlink()
        _fsync_directory(target.parent)
        copied += 1
    return {"copied": copied, "skipped": skipped, "entries": inventory["entries"],
            "output_sha256": inventory["tree_sha256"]}


# ----- PostgreSQL documents ----------------------------------------------------------------------
def bucket_inventory(records, schema: str) -> list:
    """Per-bucket count and digest of the store's documents, as `Transaction.records()` reads them."""
    buckets: dict = {}
    for record in records:
        buckets.setdefault(record["bucket"], []).append((record["id"], canonical(record["body"])))
    return [{"schema": schema, "bucket": bucket, "count": len(rows),
             "sha256": digest(["pg-bucket-v1", sorted(rows)])} for bucket, rows in sorted(buckets.items())]


def store_inventory(store, schema: str) -> list:
    with store.transaction() as tx:
        return bucket_inventory(tx.records(), schema)


def schema_store(dsn: str, schema: str):
    """A PostgresStore whose only search path is `schema`; a public fallback is refused first."""
    from codex_harness.adapters.fleet_runtime import lane_dsn, verify_lane_schema
    from codex_harness.adapters.store import PostgresStore
    from codex_harness.application.fleet import LaunchRefused

    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema) or schema == "public":
        raise MigrationRefused("schema_invalid", "schema")
    try:
        scoped = lane_dsn(dsn, schema)
        verify_lane_schema(scoped, schema)
    except LaunchRefused as exc:
        raise MigrationRefused(exc.reason_code, "schema") from None
    return PostgresStore(scoped)


def _docker_pg(container: str, user: str, argv: list, runner=run_process, timeout: int = 3600):
    """One PostgreSQL client tool inside the database container over its local socket: no DSN, no
    password and no network endpoint ever reaches argv. The container's own local auth decides."""
    for value, name in ((container, "container"), (user, "user")):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
            raise MigrationRefused("pg_tool_invalid", name)
    result = runner(["docker", "exec", container, *argv[:1], "-U", user, "-h", "/var/run/postgresql", *argv[1:]],
                    timeout=timeout)
    return result


def pg_dump(container: str, user: str, database: str, schema: str, path: str, runner=run_process) -> dict:
    """A custom-format logical dump of exactly one schema, written INSIDE the container at `path`."""
    for value, name in ((database, "database"), (schema, "schema")):
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
            raise MigrationRefused("pg_tool_invalid", name)
    result = _docker_pg(container, user, ["pg_dump", "-d", database, "-n", schema, "-Fc", "-f", path], runner)
    if result.returncode:
        raise MigrationRefused("pg_dump_failed", "exit_code")
    listing = _docker_pg(container, user, ["pg_restore", "-l", path], runner)
    checksum = runner(["docker", "exec", container, "sha256sum", path], timeout=600)
    if listing.returncode or checksum.returncode:
        raise MigrationRefused("pg_dump_unverified", "path")
    return {"schema": schema, "database": database, "path": path,
            "sha256": (checksum.stdout or "").split()[0],
            "toc_entries": sum(1 for line in (listing.stdout or "").splitlines() if line and not line.startswith(";"))}


def pg_restore(container: str, user: str, database: str, path: str, schema: str, rename_to: str,
               runner=run_process) -> dict:
    """Restore one schema dump into a STAGING database and rename it to the mapped target schema.

    Refused if either schema already exists there: a restore never merges into, or replaces, a
    schema, so an interrupted run is retried only after the operator drops the staging schema it
    left (the coordinator's checkpoint records which input it was)."""
    for value, name in ((database, "database"), (schema, "schema"), (rename_to, "rename_to")):
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
            raise MigrationRefused("pg_tool_invalid", name)
    probe = _docker_pg(container, user, ["psql", "-d", database, "-tAc",
                                         "SELECT count(*) FROM pg_namespace WHERE nspname IN ('" + schema + "','"
                                         + rename_to + "')"], runner)
    if probe.returncode or (probe.stdout or "").strip() != "0":
        raise MigrationRefused("pg_restore_schema_present", "schema")
    result = _docker_pg(container, user, ["pg_restore", "--exit-on-error", "--single-transaction",
                                          "--no-owner", "-d", database, path], runner)
    if result.returncode:
        raise MigrationRefused("pg_restore_failed", "exit_code")
    if rename_to != schema:
        renamed = _docker_pg(container, user, ["psql", "-d", database, "-v", "ON_ERROR_STOP=1", "-c",
                                               "ALTER SCHEMA " + schema + " RENAME TO " + rename_to], runner)
        if renamed.returncode:
            raise MigrationRefused("pg_rename_failed", "rename_to")
    return {"database": database, "schema": rename_to, "restored_from": schema}


# ----- Redis -------------------------------------------------------------------------------------
def _text(value):
    return value.decode("latin-1") if isinstance(value, bytes) else value


def _stream_state(client, key: str) -> tuple[dict, list]:
    info = client.xinfo_stream(key)
    groups, pel = [], []
    for group in client.xinfo_groups(key) or []:
        name = _text(group["name"])
        pending = client.xpending_range(key, name, min="-", max="+", count=1000000) or []
        pel.append([name, sorted([_text(row["message_id"]), _text(row["consumer"]), int(row["times_delivered"])]
                                 for row in pending)])
        groups.append({"name": name, "last_delivered_id": _text(group["last-delivered-id"]),
                       "pending": int(group["pending"]), "consumers": int(group["consumers"])})
    entries, cursor = [], "-"
    while True:
        page = client.xrange(key, min=cursor, max="+", count=STREAM_PAGE)
        rows = [[_text(entry_id), sorted([_text(k), _text(v)] for k, v in fields.items())]
                for entry_id, fields in page]
        if cursor != "-" and rows:
            rows = rows[1:]  # the inclusive start repeats the last entry of the previous page
        entries.extend(rows)
        if len(page) < STREAM_PAGE:
            break
        cursor = _text(page[-1][0])
    state = {"length": int(info["length"]), "last_generated_id": _text(info["last-generated-id"]),
             "groups": sorted(groups, key=lambda g: g["name"])}
    return state, [entries, sorted(pel)]


def _value(client, key: str, kind: str):
    if kind == "string":
        return _text(client.get(key))
    if kind == "hash":
        return sorted([_text(k), _text(v)] for k, v in client.hgetall(key).items())
    if kind == "set":
        return sorted(_text(v) for v in client.smembers(key))
    if kind == "zset":
        return [[_text(m), repr(s)] for m, s in client.zrange(key, 0, -1, withscores=True)]
    if kind == "list":
        return [_text(v) for v in client.lrange(key, 0, -1)]
    raise MigrationRefused("redis_type_unsupported", "type")


def redis_keys(client, namespaces) -> list:
    keys = set()
    for namespace in namespaces:
        if client.exists(namespace):
            keys.add(namespace)
        keys.update(_text(k) for k in client.scan_iter(match=namespace + ":*", count=1000))
    return sorted(keys)


def redis_inventory(client, namespaces) -> list:
    """One row per key under the namespaces: type, logical value digest, absolute expiry, streams."""
    rows = []
    for key in redis_keys(client, namespaces):
        kind = _text(client.type(key))
        if kind == "none":
            continue  # expired between SCAN and TYPE; the caller seals only a quiescent instance
        expiry = int(client.execute_command("PEXPIRETIME", key))
        stream = None
        if kind == "stream":
            stream, value = _stream_state(client, key)
        else:
            value = _value(client, key, kind)
        rows.append({"key": key, "type": kind, "sha256": digest(["redis-value-v1", kind, value]),
                     "expires_at_ms": expiry if expiry >= 0 else None, "stream": stream})
    return rows


def _server_ms(client) -> int:
    seconds, micros = client.time()
    return int(seconds) * 1000 + int(micros) // 1000


def copy_redis(source, target, keys) -> dict:
    """DUMP/RESTORE ABSTTL of exactly `keys`; resumable; never REPLACE, never extend an expiry."""
    restored = skipped = expired = 0
    for key in keys:
        if target.exists(key):
            if redis_inventory_row(source, key) != redis_inventory_row(target, key):
                raise MigrationRefused("redis_target_different", "key")
            skipped += 1
            continue
        payload = source.dump(key)
        if payload is None:
            raise MigrationRefused("redis_source_missing", "key")
        expiry = int(source.execute_command("PEXPIRETIME", key))
        if expiry >= 0 and expiry <= _server_ms(target):
            expired += 1  # really expired during the downtime; reported, not revived
            continue
        target.restore(key, expiry if expiry >= 0 else 0, payload, absttl=expiry >= 0)
        restored += 1
    return {"restored": restored, "skipped": skipped, "expired_in_downtime": expired, "keys": len(keys),
            "restored_at_ms": _server_ms(target)}


def redis_inventory_row(client, key: str):
    kind = _text(client.type(key))
    if kind == "none":
        return None
    if kind == "stream":
        state, value = _stream_state(client, key)
        return [kind, state, digest(["redis-value-v1", kind, value])]
    return [kind, digest(["redis-value-v1", kind, _value(client, key, kind)])]


# ----- the Linux systemd service target ----------------------------------------------------------
class SystemdHostTarget(HostTargetBase):
    """An owner-installed systemd unit, started and stopped by name; never written here.

    The unit is rendered from `urn:zeus:systemd-service:1` (`render-unit`) and installed by the
    owner. This adapter only runs `systemctl start|stop|is-active <service>.service`; no name, path
    or argument comes from a candidate. The unit runs the same `host_delivery service` entry point
    as the process target, so the descriptor, startup receipt and drain contract are unchanged.
    `KillMode=control-group` ends the service's processes; Docker containers it created live in the
    daemon's cgroup and are reconciled separately by run label (not by this stop).
    """

    kind = KIND_SYSTEMD

    def __init__(self, *, runner=run_process, timeout: int = 60, user_scope: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.runner, self.timeout, self.user_scope = runner, timeout, user_scope

    def _systemctl(self, *argv: str):
        prefix = ["systemctl", "--user"] if self.user_scope else ["systemctl"]
        return self.runner([*prefix, *argv], timeout=self.timeout)

    @staticmethod
    def unit(target: dict) -> str:
        return target["service"] + ".service"

    def running(self, target: dict) -> bool:
        result = self._systemctl("is-active", self.unit(target))
        state = (result.stdout or "").strip()
        if state in ("active", "activating", "deactivating", "reloading"):
            return True
        if state in ("inactive", "failed"):
            return False
        raise RuntimeError("systemd unit state unavailable")

    def stop(self, target: dict) -> dict:
        result = self._systemctl("stop", self.unit(target))
        deadline = time.monotonic() + STOP_TIMEOUT
        while self.running(target) and time.monotonic() < deadline:
            time.sleep(STOP_POLL)
        return {"stopped": not self.running(target), "exit_code": result.returncode}

    def _launch(self, target: dict, descriptor: dict, context) -> dict:
        result = self._systemctl("start", self.unit(target))
        if result.returncode:
            raise RuntimeError("systemd unit could not be started")
        record = {"service": target["service"], "started_at": _utcnow(),
                  "descriptor_sha256": descriptor_digest(descriptor)}
        _write_json(self.path(target, HOST_STATE_FILE), record)
        return {"started": True, "service": target["service"], "launch": record}


# ----- target layout -----------------------------------------------------------------------------
def layout_plan(root) -> list:
    root = Path(root)
    if not root.is_absolute():
        raise MigrationRefused("layout_invalid", "root")
    return [str(root / part) for part in LAYOUT]


def prepare_layout(root, *, apply: bool = False) -> dict:
    """The /srv/zeus directory layout; a dry run by default. Existing directories are kept as they
    are; a path that exists as something other than a directory refuses."""
    rows = []
    for path in map(Path, layout_plan(root)):
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

    return HostMigrations(schema_store(_env(args.dsn_env), args.schema))


def _read(path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def execute(args) -> dict:
    command = args.command
    if command == "validate":
        from codex_harness.domain.host_migration import manifest_digest, validate_manifest

        manifest = validate_manifest(_read(args.file))
        return {"valid": True, "migration_id": manifest["migration_id"], "manifest_sha256": manifest_digest(manifest)}
    if command == "plan":
        return _coordinator(args).plan(_read(args.file))
    if command == "advance":
        return _coordinator(args).advance(_read(args.file))
    if command == "checkpoint":
        return _coordinator(args).checkpoint(_read(args.file))
    if command == "status":
        return _coordinator(args).status(args.migration_id)
    if command == "rollback-plan":
        return _coordinator(args).rollback_plan(args.migration_id)
    if command == "artifact-inventory":
        inventory = artifact_inventory(args.root)
        return inventory if args.full else {k: v for k, v in inventory.items() if k != "files"}
    if command == "artifact-copy":
        inventory = artifact_inventory(args.source)
        if inventory["tree_sha256"] != args.expected_tree_sha256:
            raise MigrationRefused("artifact_inventory_changed", "expected_tree_sha256")
        return copy_artifacts(args.source, args.target, inventory)
    if command == "artifact-compare":
        return compare_trees(artifact_inventory(args.source), artifact_inventory(args.target))
    if command == "pg-inventory":
        return {"buckets": store_inventory(schema_store(_env(args.dsn_env), args.schema), args.schema)}
    if command == "pg-compare":
        source, target = _read(args.source), _read(args.target)
        return compare_buckets(source["buckets"], target["buckets"], _read(args.schema_map),
                               [tuple(pair) for pair in args.allow_delta or []])
    if command == "pg-dump":
        return pg_dump(args.container, args.user, args.database, args.schema, args.path)
    if command == "pg-restore":
        return pg_restore(args.container, args.user, args.database, args.path, args.schema, args.rename_to)
    if command == "redis-inventory":
        client = _redis_client(args.url_env, args.socket)
        return {"server_ms": _server_ms(client), "keys": redis_inventory(client, args.namespace)}
    if command == "redis-copy":
        source = _redis_client(args.source_url_env, args.source_socket)
        target = _redis_client(args.target_url_env, args.target_socket)
        before = redis_inventory(source, args.namespace)
        result = copy_redis(source, target, [row["key"] for row in before])
        result["comparison"] = compare_redis(before, redis_inventory(target, args.namespace),
                                             restored_at_ms=result["restored_at_ms"])
        return result
    if command == "render-unit":
        text = render_unit(_read(args.file))
        return {"unit": text, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    if command == "prepare-layout":
        return prepare_layout(args.root, apply=args.apply)
    raise MigrationRefused("command_unknown", "command")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m codex_harness.adapters.host_migration",
                                   description="Host migration coordinator and staged restore tools "
                                               "(INV-HOST-MIGRATION-001). Connection strings come from "
                                               "named environment variables only.")
    sub = root.add_subparsers(dest="command", required=True)

    def store_args(command):
        command.add_argument("--dsn-env", default="HARNESS_DATABASE_URL", help="Env var NAME holding the DSN")
        command.add_argument("--schema", required=True, help="The only search_path schema")

    sub.add_parser("validate").add_argument("--file", required=True)
    for name in ("plan", "advance", "checkpoint"):
        command = sub.add_parser(name)
        command.add_argument("--file", required=True)
        store_args(command)
    for name in ("status", "rollback-plan"):
        command = sub.add_parser(name)
        command.add_argument("--migration-id", required=True)
        store_args(command)
    command = sub.add_parser("artifact-inventory")
    command.add_argument("--root", required=True)
    command.add_argument("--full", action="store_true")
    command = sub.add_parser("artifact-copy")
    command.add_argument("--source", required=True)
    command.add_argument("--target", required=True)
    command.add_argument("--expected-tree-sha256", required=True)
    command = sub.add_parser("artifact-compare")
    command.add_argument("--source", required=True)
    command.add_argument("--target", required=True)
    store_args(sub.add_parser("pg-inventory"))
    command = sub.add_parser("pg-compare")
    command.add_argument("--source", required=True)
    command.add_argument("--target", required=True)
    command.add_argument("--schema-map", required=True)
    command.add_argument("--allow-delta", nargs=2, action="append", metavar=("SCHEMA", "BUCKET"))
    for name in ("pg-dump", "pg-restore"):
        command = sub.add_parser(name)
        command.add_argument("--container", required=True)
        command.add_argument("--user", default="postgres")
        command.add_argument("--database", required=True)
        command.add_argument("--schema", required=True)
        command.add_argument("--path", required=True, help="Dump path inside the container")
        if name == "pg-restore":
            command.add_argument("--rename-to", required=True)
    command = sub.add_parser("redis-inventory")
    command.add_argument("--url-env")
    command.add_argument("--socket")
    command.add_argument("--namespace", action="append", required=True)
    command = sub.add_parser("redis-copy")
    for side in ("source", "target"):
        command.add_argument("--" + side + "-url-env")
        command.add_argument("--" + side + "-socket")
    command.add_argument("--namespace", action="append", required=True)
    sub.add_parser("render-unit").add_argument("--file", required=True)
    command = sub.add_parser("prepare-layout")
    command.add_argument("--root", required=True)
    command.add_argument("--apply", action="store_true")
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        result = execute(args)
    except MigrationRefused as exc:
        print(json.dumps({"refused": exc.reason_code, "field": exc.field}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["SystemdHostTarget", "artifact_inventory", "bucket_inventory", "copy_artifacts", "copy_redis",
           "execute", "layout_plan", "main", "parser", "pg_dump", "pg_restore", "prepare_layout", "redis_inventory", "schema_store",
           "store_inventory"]
