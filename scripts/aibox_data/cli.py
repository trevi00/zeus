"""Command line for the offline data-transfer tooling. Every command prints one JSON document.

Exit 0: the check passed / the report is complete. Exit 1: refused, mismatched or needs a decision.
Exit 2: usage error. Nothing here contacts PostgreSQL/Redis or changes admission or ledger state.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

from . import contracts, gates, inventory, mapping, transfer


def _load(path: str):
    return json.loads(Path(path).read_text("utf-8"))


def _pairs(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        name, sep, path = value.partition("=")
        if not sep or not name or not path or name in result:
            raise SystemExit(f"expected unique NAME=PATH, got {value!r}")
        result[name] = path
    return result


def _emit(value: dict, ok: bool, out: str | None = None) -> int:
    text = json.dumps(value, sort_keys=True, indent=1, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"written": out, "ok": ok, "digest": value.get("digest")}))
    else:
        print(text)
    return 0 if ok else 1


def _rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def run(args: argparse.Namespace) -> int:
    if args.command == "inventory":
        manifest = inventory.build_manifest(args.migration_id, _pairs(args.root),
                                            args.host or socket.gethostname())
        blocking = any(root["findings"]["case_collisions"]
                       or any(inventory.blocking_findings(root).values())
                       for root in manifest["roots"].values())
        return _emit(manifest, not blocking, args.out)
    if args.command == "verify-manifest":
        return _emit({"digest_valid": inventory.verify_manifest_digest(_load(args.manifest))},
                     inventory.verify_manifest_digest(_load(args.manifest)))
    if args.command == "verify-artifacts":
        report = inventory.verify_artifact_store(args.root)
        return _emit(report, report["valid"])
    if args.command == "scan-paths":
        report = inventory.scan_path_references(args.root)
        return _emit(report, True, args.out)
    if args.command == "stage":
        try:
            report = transfer.stage_root(_load(args.manifest), args.root_id, args.source, args.staging,
                                         args.work, args.limit_bytes)
        except transfer.TransferRefused as exc:
            return _emit({"status": "refused", "reason": exc.reason, "path": exc.path}, False)
        return _emit(report, report["status"] == "complete")  # blocked/interrupted/needs decision -> 1
    if args.command == "verify-staged":
        report = transfer.verify_staged(_load(args.manifest), args.root_id, args.staging, args.work)
        return _emit(report, report["match"])
    if args.command == "pg-inventory":
        meta = _load(args.meta)
        for name, path in _pairs(args.export).items():
            meta.setdefault("schemas", {}).setdefault(name, {})["buckets"] = \
                contracts.pg_schema_from_export(path)
        problems = contracts.validate_pg(meta, args.role)
        return _emit(meta if not problems else {"problems": problems}, not problems, args.out)
    if args.command == "compare-pg":
        report = contracts.compare_pg(_load(args.source), _load(args.target), _load(args.schema_map),
                                      _load(args.delta) if args.delta else None)
        return _emit(report, report["match"])
    if args.command == "compare-redis":
        report = contracts.compare_redis(_load(args.source), _load(args.target), args.tolerance_ms)
        return _emit(report, report["match"])
    if args.command == "pel-owners":
        report = contracts.check_pel_owners(_load(args.inventory), _load(args.owners))
        return _emit(report, report["valid"])
    if args.command == "plan-bindings":
        report = mapping.plan_binding_changes(_rows(args.rows), _load(args.allowlist))
        return _emit(report, report["valid"], args.out)
    if args.command == "gate":
        check = {"r0": gates.rollback_r0, "r1": gates.rollback_r1, "c": gates.retirement_gate_c}
        report = check[args.gate](_load(args.evidence))
        return _emit(report, report["eligible"])
    raise AssertionError(args.command)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="aibox_data", description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inventory", help="scan roots into a sealed file manifest")
    p.add_argument("--migration-id", required=True)
    p.add_argument("--root", action="append", required=True, metavar="ID=PATH")
    p.add_argument("--host")
    p.add_argument("--out")
    sub.add_parser("verify-manifest").add_argument("manifest")
    sub.add_parser("verify-artifacts").add_argument("root")
    p = sub.add_parser("scan-paths", help="report Windows absolute paths (no rewrite)")
    p.add_argument("root")
    p.add_argument("--out")
    for name in ("stage", "verify-staged"):
        p = sub.add_parser(name)
        p.add_argument("--manifest", required=True)
        p.add_argument("--root-id", required=True)
        p.add_argument("--staging", required=True)
        p.add_argument("--work", required=name == "stage",
                       help="migration-owned work dir (journal, partials) on the staging filesystem")
        if name == "stage":
            p.add_argument("--source", required=True)
            p.add_argument("--limit-bytes", type=int)
    p = sub.add_parser("pg-inventory", help="build a PG inventory from documents JSONL exports")
    p.add_argument("--meta", required=True)
    p.add_argument("--export", action="append", required=True, metavar="SCHEMA=JSONL")
    p.add_argument("--role", choices=["source", "target"], required=True)
    p.add_argument("--out")
    p = sub.add_parser("compare-pg")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--schema-map", required=True)
    p.add_argument("--delta")
    p = sub.add_parser("compare-redis")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--tolerance-ms", type=int, default=0)
    p = sub.add_parser("pel-owners")
    p.add_argument("--inventory", required=True)
    p.add_argument("--owners", required=True)
    p = sub.add_parser("plan-bindings")
    p.add_argument("--rows", required=True)
    p.add_argument("--allowlist", required=True)
    p.add_argument("--out")
    p = sub.add_parser("gate")
    p.add_argument("gate", choices=["r0", "r1", "c"])
    p.add_argument("--evidence", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        return run(args)
    except SystemExit as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        return 1
