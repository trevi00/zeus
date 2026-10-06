"""The host migration operator CLI process: `python -m codex_harness.entry.processes.host_migration <command> ...` (INV-HOST-MIGRATION-001).

Layer: entry
Owns: parser, main
Does not own: the command bodies (`composition.host_migration_cli.execute`), the effect functions (`delivery.adapters.host_migration`) and the policy (`delivery.domain.host_migration`)
Entry points: main, parser
Contracts: INV-HOST-MIGRATION-001

Moved from M7 `adapters/host_migration.py` `parser` (:1146-1284) and `main` (:1285-1293) (SOURCE e38aa722) by rule R-e5cd (S10 unit E5c), verbatim except the home of `MigrationRefused`. The M7 module path is a kept shim (the corrected S0 scan; DESIGN-s10 §16b, owner int44), so the program name stays M7's.
"""
from __future__ import annotations

import argparse
import json

from codex_harness.composition.host_migration_cli import execute
from codex_harness.delivery.domain.host_migration import MigrationRefused


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
    for name in ("plan", "advance", "checkpoint", "intend-activation", "activation-successor"):
        command = sub.add_parser(name)
        command.add_argument("--file", required=True)
        store_args(command)
    for name in ("status", "rollback-plan", "activation-write"):
        command = sub.add_parser(name)
        command.add_argument("--migration-id", required=True)
        store_args(command)
        if name == "activation-write":
            command.add_argument("--control-dir", required=True)
    command = sub.add_parser("activation-switch",
                             help="Receipt first, then `current`, under the coordinator transaction")
    command.add_argument("--migration-id", required=True)
    command.add_argument("--control-dir", required=True)
    command.add_argument("--releases-dir", required=True)
    command.add_argument("--managed-state-dir", required=True)
    command.add_argument("--expected-id", help="The effective activation id the switch must still find")
    command.add_argument("--check", action="store_true", help="Classify only; write nothing")
    store_args(command)
    command = sub.add_parser("observe-limited-active",
                             help="Read-only managed limited_active observation: prints {observation, evidence, "
                                  "transition_draft}; with --expect, {observation, comparison} only; writes, "
                                  "starts and submits nothing")
    command.add_argument("--migration-id", required=True)
    command.add_argument("--expected-id", required=True, help="The effective activation id the capture must find")
    command.add_argument("--target-id", required=True, help="The registered managed Fleet target")
    command.add_argument("--plan-id", required=True, help="The delivery plan whose owner canary admitted it")
    command.add_argument("--actor", required=True, help="The actor the transition draft names")
    command.add_argument("--root", required=True, help="ZEUS_AIBOX_ROOT: runtime/control, releases, managed state")
    command.add_argument("--config-file", help="Host configuration hashed into the draft identity "
                                               "(default <root>/config/zeus-aibox.env)")
    command.add_argument("--control-dsn-env", default="HARNESS_DATABASE_URL",
                         help="Env var NAME holding the control store DSN")
    command.add_argument("--control-schema", required=True, help="The control schema (owner actions, Fleet registry)")
    command.add_argument("--lane", help="The Fleet lane holding the delivery; omitted reads the control store")
    command.add_argument("--expect", help="Absolute path of an archived success output: re-read every source and "
                                          "compare (PH4-13); no draft or receipt is emitted")
    command.add_argument("--post-transition", action="store_true",
                         help="With --expect: the post-check after the recorded managed limited_active transition")
    store_args(command)
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


if __name__ == "__main__":
    raise SystemExit(main())
