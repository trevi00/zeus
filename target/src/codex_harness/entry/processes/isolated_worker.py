"""Entry of the in-container isolated worker (INV-ISOLATED-WORKER-001).

Layer: entry
Owns: nothing; M7's `__main__` body over the composition's `serve`
Entry points: main
Contracts: INV-ISOLATED-WORKER-001
"""
from __future__ import annotations

import sys

from codex_harness.composition.isolated_worker_entry import serve


def main() -> int:
    return serve(sys.stdin.buffer, sys.stdout.buffer)
