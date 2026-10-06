"""The host migration operator CLI's command bodies: the coordinator store, the file readers and `execute` (INV-HOST-MIGRATION-001).

Layer: composition
Owns: execute, schema_store and the private _env, _redis_client, _coordinator, _read, _checked, _schema
Does not own: the argument shape and `main` (`entry.processes.host_migration`), the evidence command (`composition.host_migration_evidence_cli`), `canonical_module` (`composition.canonical_tools`), the effect functions (`delivery.adapters.host_migration`) and the policy (`delivery.domain.host_migration`)
Entry points: execute, schema_store
Contracts: INV-HOST-MIGRATION-001

Moved from M7 `adapters/host_migration.py` (SOURCE e38aa722) by rule R-e5cd (S10 unit E5c): `_env` (:1009), `_redis_client` (:1016), `_coordinator` (:1024), `_read` (:1030), `_checked` (:1034), `execute` (:1039-1145) and, from the owner decision of resume 1, `_schema` and `schema_store` (:143-162). Bodies are M7's verbatim except these declared differences:
* Homes: `HostMigrations` is `delivery.application.host_migration`'s, `MigrationRefused` and `evidence_receipt` `delivery.domain.host_migration`'s, the effect functions `delivery.adapters.host_migration`'s, `lane_dsn` and `verify_lane_schema` `coordination.adapters.fleet_runtime`'s, `LaunchRefused` `coordination.domain.fleet`'s, `PostgresStore` `storage.adapters.postgres_store`'s, `observe_command` `composition.host_migration_evidence_cli`'s and `canonical_module` `composition.canonical_tools`'s.
* The runner bindings M7 defaulted (the effect functions now require them, S7 V6): `run_canonical` and `pg_compare_schema` get `process_groups.run` (M7 `subprocess.run` through the chokepoint, as `composition.owner_actions`); `pg_dump_database`, `pg_restore_database` and `switch_effect` get `process_groups.run_process` (M7 `runner=run_process`). `redis_inventory` gets `canonical_module=canonical_module`.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from codex_harness.composition.canonical_tools import canonical_module
from codex_harness.composition.host_migration_evidence_cli import observe_command
from codex_harness.delivery.adapters.host_migration import (
    IDENT,
    INCONSISTENT,
    catalog_digest,
    copy_redis,
    pg_catalog,
    pg_compare_schema,
    pg_coverage_receipt,
    pg_dump_database,
    pg_export,
    pg_restore_database,
    prepare_layout,
    redis_inventory,
    run_canonical,
    switch_effect,
    write_activation,
    write_fence,
)
from codex_harness.delivery.domain.host_migration import SOURCE_PUBLIC, MigrationRefused, evidence_receipt
from codex_harness.host_os.adapters import process_groups


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _schema(schema: str, role: str) -> str:
    if role not in ("source", "target") or not IDENT.fullmatch(schema):
        raise MigrationRefused("schema_invalid", "schema")
    if schema == SOURCE_PUBLIC and role != "source":
        raise MigrationRefused("public_schema", "schema")
    return schema


def schema_store(dsn: str, schema: str, role: str = "target"):
    """A PostgresStore whose only search path is `schema`; the lane rule refuses any fallback."""
    from codex_harness.coordination.adapters.fleet_runtime import lane_dsn, verify_lane_schema
    from codex_harness.coordination.domain.fleet import LaunchRefused
    from codex_harness.storage.adapters.postgres_store import PostgresStore

    _schema(schema, role)
    try:
        scoped = lane_dsn(dsn, schema)
        verify_lane_schema(scoped, schema)
    except LaunchRefused as exc:
        raise MigrationRefused(exc.reason_code, "schema") from None
    return PostgresStore(scoped)


def _canonical(argv: list, **named) -> dict:
    """M7's `run_canonical(argv, ...)`, whose `runner=subprocess.run` default is the chokepoint's `run`."""
    return run_canonical(argv, runner=process_groups.run, **named)


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
    from codex_harness.delivery.application.host_migration import HostMigrations

    return HostMigrations(schema_store(_env(args.dsn_env), args.schema, "target"))


def _read(path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _checked(outcome: dict) -> tuple[dict, bool]:
    """A delegated run: the receipt decides the exit, the result is shown beside it unchanged."""
    return outcome, outcome["receipt"]["ok"]


def execute(args) -> tuple[dict, bool]:
    command = args.command
    if command == "validate":
        from codex_harness.delivery.domain.host_migration import manifest_digest, validate_manifest

        manifest = validate_manifest(_read(args.file))
        return {"valid": True, "migration_id": manifest["migration_id"],
                "manifest_sha256": manifest_digest(manifest)}, True
    if command in ("plan", "advance", "checkpoint", "intend-activation", "activation-successor"):
        coordinator = _coordinator(args)
        method = {"plan": coordinator.plan, "advance": coordinator.advance, "checkpoint": coordinator.checkpoint,
                  "intend-activation": coordinator.intend_activation,
                  "activation-successor": coordinator.record_successor}[command]
        return method(_read(args.file)), True
    if command == "activation-switch":
        if not args.check and not args.expected_id:
            # The head the operator validated is rechecked under the coordinator lock before a write.
            raise MigrationRefused("expected_id_required", "expected_id")
        # The effect first: a non-POSIX host is refused before the coordinator store is opened.
        effect = switch_effect(args.control_dir, args.releases_dir, args.managed_state_dir, check=args.check,
                              runner=process_groups.run_process)
        result = _coordinator(args).activation_switch(args.migration_id, effect, expected_id=args.expected_id)
        return result, result["classification"] != INCONSISTENT
    if command == "observe-limited-active":
        # Read-only producer of the managed limited_active receipts (INV-HOST-MIGRATION-001); no apply mode.
        return observe_command(args)
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
        return _checked(_canonical(argv))
    if command == "artifact-stage":
        return _checked(_canonical(["stage", "--manifest", args.manifest, "--root-id", args.root_id,
                                       "--source", args.source, "--staging", args.staging, "--work", args.work],
                                      subject="root=" + args.root_id))
    if command == "artifact-verify":
        argv = ["verify-staged", "--manifest", args.manifest, "--root-id", args.root_id, "--staging", args.staging]
        if args.work:
            argv += ["--work", args.work]
        return _checked(_canonical(argv, subject="root=" + args.root_id))
    if command == "pg-export":
        return pg_export(_env(args.dsn_env), args.schema, args.role, args.meta_out, args.rows_out), True
    if command == "pg-inventory":
        argv = ["pg-inventory", "--meta", args.meta, "--role", args.role, "--out", args.out]
        for export in args.export:
            argv += ["--export", export]
        return _checked(_canonical(argv))
    if command == "pg-compare-schema":
        return _checked(pg_compare_schema(_read(args.source), _read(args.target), _read(args.schema_map),
                                          args.source_schema, _read(args.delta) if args.delta else None,
                                          runner=process_groups.run))
    if command == "pg-coverage":
        return _checked(pg_coverage_receipt(_read(args.schema_map), [_read(path) for path in args.receipt]))
    if command == "pg-dump-db":
        return pg_dump_database(args.container, args.user, args.database, args.path,
                                  runner=process_groups.run_process), True
    if command == "pg-catalog":
        catalog = pg_catalog(_env(args.dsn_env), args.database)
        Path(args.out).write_text(json.dumps(catalog, sort_keys=True, indent=1) + "\n", encoding="utf-8", newline="\n")
        return {"written": args.out, "catalog_sha256": catalog_digest(catalog),
                "schemas": len(catalog["schemas"])}, True
    if command == "pg-compare-catalog":
        from codex_harness.delivery.domain.host_migration import compare_catalogs

        report = compare_catalogs(_read(args.source), _read(args.target), _read(args.schema_map))
        return {"result": report, "receipt": evidence_receipt(
            "pg-catalog", None, 0 if report["match"] else 1, report["match"],
            _sha256_bytes(json.dumps(report, sort_keys=True).encode()))}, report["match"]
    if command == "pg-restore-db":
        return pg_restore_database(args.container, args.user, _env(args.dsn_env), args.database, args.path,
                                   args.archive_sha256, _read(args.source_catalog), _read(args.schema_map),
                                   args.receipt, reverse=args.reverse, recover=args.recover,
                                   runner=process_groups.run_process), True
    if command == "redis-inventory":
        document = redis_inventory(_redis_client(args.url_env, args.socket), args.namespace,
                                    canonical_module=canonical_module)
        Path(args.out).write_text(json.dumps(document, sort_keys=True, indent=1) + "\n", encoding="utf-8", newline="\n")
        return {"written": args.out, "keys": len(document["keys"]), "streams": len(document["streams"])}, True
    if command == "redis-copy":
        source = _redis_client(args.source_url_env, args.source_socket)
        target = _redis_client(args.target_url_env, args.target_socket)
        before = redis_inventory(source, args.namespace, canonical_module=canonical_module)
        copied = copy_redis(source, target, sorted(before["keys"]))
        after = redis_inventory(target, args.namespace, canonical_module=canonical_module)
        with tempfile.TemporaryDirectory(prefix="zeus-redis-compare-") as work:
            for name, document in (("source", before), ("target", after)):
                (Path(work) / (name + ".json")).write_text(json.dumps(document), encoding="utf-8", newline="\n")
            outcome = _canonical(["compare-redis", "--source", str(Path(work) / "source.json"),
                                     "--target", str(Path(work) / "target.json")])
        return {**outcome, "copy": copied}, outcome["receipt"]["ok"]
    if command == "compare-redis":
        return _checked(_canonical(["compare-redis", "--source", args.source, "--target", args.target]))
    if command == "pel-owners":
        return _checked(_canonical(["pel-owners", "--inventory", args.inventory, "--owners", args.owners]))
    if command == "gate":
        return _checked(_canonical(["gate", args.gate, "--evidence", args.evidence], check="gate-" + args.gate))
    if command == "prepare-layout":
        return prepare_layout(args.root, apply=args.apply), True
    raise MigrationRefused("command_unknown", "command")


