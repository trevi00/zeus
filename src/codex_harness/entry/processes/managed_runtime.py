"""Entry of the managed Fleet child processes: `launch|entry|supervise --state-dir DIR ...` (HOST-RUNTIME.md).

Layer: entry
Owns: nothing but M7's argument parsing; delegates to composition. The `supervise` subcommand runs with the
    production Fleet gate (`fleet_gate`, M7's default gate); the wired `supervise` function is re-exported for the
    unit's ExecStart snippet that imports it by module name
Entry points: main, supervise
Contracts: INV-HOST-DELIVERY-001
"""
from __future__ import annotations

import argparse
import sys

from codex_harness.composition.managed_runtime import entry, fleet_gate, launch, supervise
from codex_harness.delivery.domain.managed_runtime import WORKLOADS


def main(argv=None) -> int:
    """`python -m codex_harness.adapters.managed_runtime launch|entry|supervise --state-dir DIR ...`."""
    parser = argparse.ArgumentParser(prog="codex_harness.adapters.managed_runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    launcher = sub.add_parser("launch")
    launcher.add_argument("--state-dir", required=True, dest="state_dir")
    launcher.add_argument("--descriptor-sha256", required=True, dest="descriptor_sha256")
    launcher.add_argument("--workload", required=True, choices=list(WORKLOADS))
    child = sub.add_parser("entry")
    child.add_argument("--state-dir", required=True, dest="state_dir")
    child.add_argument("--workload", required=True, choices=list(WORKLOADS))
    supervised = sub.add_parser("supervise")
    supervised.add_argument("--state-dir", required=True, dest="state_dir")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.command == "launch":
        return launch(args.state_dir, args.descriptor_sha256, args.workload)
    if args.command == "supervise":
        return supervise(args.state_dir, gate=fleet_gate)
    return entry(args.state_dir, args.workload)


__all__ = ["main", "supervise"]
