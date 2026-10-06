"""Entry of the `zeus-supervisor` process (S10 unit E3, R-e3).

Layer: entry
Owns: the argument shape of the supervisor
Entry points: main
Contracts: INV-OBSERVATION-001

Moved from M7 `supervisor.py` `main()` (SOURCE e38aa722:209-216): the parser statements are M7's verbatim; the rest of `main()` is
`composition.supervisor.run`.
"""
import argparse
from pathlib import Path

from codex_harness.composition import supervisor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--research", action="store_true")
    parser.add_argument("--releases", action="store_true")
    parser.add_argument("--repository", type=Path)
    args = parser.parse_args()
    supervisor.run(args)
