"""Entry of the fixed monitor frontend checks command (INV-EVIDENCE-001).

Layer: entry
Owns: nothing; delegates to the one composition function
Entry points: main
Contracts: INV-EVIDENCE-001
"""
from __future__ import annotations

from codex_harness.composition.monitor_frontend_checks import frontend_checks_command


def main(argv=None) -> int:
    return frontend_checks_command()(argv)
