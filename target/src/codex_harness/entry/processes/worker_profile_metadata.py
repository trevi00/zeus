"""Entry of the read-only worker-profile metadata command (INV-WORKER-PROFILE-001).

Layer: entry
Owns: nothing; delegates to the one composition function
Entry points: main
Contracts: INV-WORKER-PROFILE-001
"""
from __future__ import annotations

from codex_harness.composition.worker_profile_metadata import metadata_command


def main(argv=None) -> int:
    return metadata_command()(argv)
