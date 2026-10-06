"""Entry of the launched delivery service: `service --state-dir DIR [--max-seconds N]` (INV-HOST-DELIVERY-001).

Layer: entry
Owns: nothing but M7's argument parsing; delegates to the one composition function
Entry points: main
Contracts: INV-HOST-DELIVERY-001
"""
from __future__ import annotations

import argparse
import sys

from codex_harness.composition.delivery_service import serve_service

SERVICE_MAX_SECONDS = 900


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="codex_harness.adapters.host_delivery")
    sub = parser.add_subparsers(dest="command", required=True)
    service = sub.add_parser("service")
    service.add_argument("--state-dir", required=True, dest="state_dir")
    service.add_argument("--max-seconds", type=int, default=SERVICE_MAX_SECONDS, dest="max_seconds")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return serve_service(args.state_dir, args.max_seconds)
