"""Entry of the hidden per-launch guardian process (INV-CONTINUATION-001).

Layer: entry
Owns: nothing; delegates to the one composition function
Entry points: main
Contracts: INV-CONTINUATION-001
"""
from __future__ import annotations

from codex_harness.composition.guarded_launch import guardian_command


def main(argv=None) -> int:
    return guardian_command()(argv)
