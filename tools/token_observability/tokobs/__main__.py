"""tokobs command line: `scan`, `render`, `report`, `serve`, `lint-deploy`.

Purpose: argparse entry that only invokes the use-case modules. Layer: tooling. Owns: exit codes (0 ok, 1 not found
or refused input, 2 usage, 75 another collector holds the lock). Does-not-own: any policy.
Implements: ACCEPTANCE A18, A57 (`lint-deploy`: exit 0 clean, 1 violations, 2 unreadable or invalid JSON); DESIGN §3.1 (`scan --data DIR --source-root A_ROOT`), §4 (`report --task`, `report --invocation`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .collector import scan_once
from .config import ConfigError, load_registry, validate_root
from .deploy_lint import lint_compose, lint_inspect
from .ledger import EXIT_BUSY, CollectorBusy, LedgerError, collector_lock, open_ledger
from .render import render
from .report import invocation_report, render_report, task_report
from .s1_routine import parse_at
from .serve import SCAN_INTERVAL_SECONDS


def _now(text: str | None) -> int:
    if text is None:
        return int(time.time())
    return parse_at(text) or int(text)  # `--now` is a test/replay hook: ISO `…Z` or epoch seconds


def _serve(ns: argparse.Namespace) -> int:
    from .serve import Service
    try:
        service = Service(
            ns.listen, data=ns.data, source_root=Path(validate_root(ns.source_root)) if ns.source_root else None,
            fixture=ns.fixture, interval=ns.interval, registry=load_registry(ns.task_classes),
            live_since=ns.live_since, s9_dir=ns.s9_dir, deferred_file=ns.deferred_file)
    except ValueError as exc:
        print(f"tokobs: {exc}", file=sys.stderr)
        return 2
    service.start()
    try:
        service.wait()
    finally:
        service.stop()
    return 0


def _lint_deploy(ns: argparse.Namespace) -> int:
    source = ns.compose_json or ns.inspect_json
    try:
        text = sys.stdin.read() if str(source) == "-" else Path(source).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError) as exc:  # unreadable file/stdin, invalid JSON or encoding
        print(f"tokobs: {exc}", file=sys.stderr)
        return 2
    if ns.compose_json:
        violations = lint_compose(data) if isinstance(data, dict) else None
    else:
        violations = lint_inspect(data) if isinstance(data, list) else None
    if violations is None:
        print("tokobs: JSON has the wrong top-level type", file=sys.stderr)
        return 2
    for line in violations:
        print(line)
    return 1 if violations else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tokobs")
    sub = parser.add_subparsers(dest="cmd", required=True)
    scan = sub.add_parser("scan", help="one bounded scan under DIR/ledger.lock")
    scan.add_argument("--data", required=True, type=Path)
    scan.add_argument("--source-root", required=True)
    scan.add_argument("--task-classes", type=Path)
    scan.add_argument("--now")
    scan.add_argument("--live-since", type=int, help="explicit §3.9 live_since (C-W1-7); stored once")
    rend = sub.add_parser("render", help="write data.prom and health.prom atomically")
    rend.add_argument("--data", required=True, type=Path)
    rend.add_argument("--now")
    rep = sub.add_parser("report", help="print one task's invocations, contributions and corrections")
    rep.add_argument("--data", required=True, type=Path)
    which = rep.add_mutually_exclusive_group(required=True)
    which.add_argument("--task")
    which.add_argument("--invocation", help="a canonical invocation ID or a Codex run stem (no task binding)")
    srv = sub.add_parser("serve", help="periodic scan under the flock + /metrics (DESIGN §3, §7)")
    srv.add_argument("--listen", required=True, help="ADDR:PORT, an IP address (never a hostname)")
    srv.add_argument("--data", type=Path)
    srv.add_argument("--source-root")
    srv.add_argument("--fixture", action="store_true", help="serve a static sample; read no worker input")
    srv.add_argument("--task-classes", type=Path)
    srv.add_argument("--s9-dir", type=Path, help="directory holding monitoring.json (read-only)")
    srv.add_argument("--deferred-file", type=Path, help="S4/OTel-shaped rows to count, never ingest (§3.10)")
    srv.add_argument("--live-since", type=int)
    srv.add_argument("--interval", type=float, default=float(SCAN_INTERVAL_SECONDS))
    lint = sub.add_parser("lint-deploy", help="A57 static lint of compose or `docker inspect` JSON (- is stdin)")
    which_json = lint.add_mutually_exclusive_group(required=True)
    which_json.add_argument("--compose-json", type=Path)
    which_json.add_argument("--inspect-json", type=Path)
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if ns.cmd == "lint-deploy":
        return _lint_deploy(ns)
    try:
        if ns.cmd == "scan":
            validate_root(ns.source_root)
            scan_once(ns.data, Path(ns.source_root), now=_now(ns.now), registry=load_registry(ns.task_classes),
                      live_since=ns.live_since)
        elif ns.cmd == "serve":
            return _serve(ns)
        elif ns.cmd == "render":
            now = _now(ns.now)
            with collector_lock(ns.data):
                ledger = open_ledger(ns.data)
                try:
                    result = render(ledger, ns.data, now)
                finally:
                    ledger.close()
            if result.refused:
                print(f"render refused: {result.series_count} series", file=sys.stderr)
                return 1
        else:
            ledger = open_ledger(ns.data, create=False)
            try:
                report = task_report(ledger, ns.task) if ns.task else invocation_report(ledger, ns.invocation)
            finally:
                ledger.close()
            if report is None:
                print("no such task" if ns.task else "no such invocation", file=sys.stderr)
                return 1
            sys.stdout.write(render_report(report))
    except CollectorBusy:
        print("another collector holds ledger.lock", file=sys.stderr)
        return EXIT_BUSY
    except (LedgerError, ConfigError, OSError, ValueError) as exc:
        print(f"tokobs: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
