"""The `zeus run-command` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus run-command`)
Does not own: dispatch and composition (S10 unit C2)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:221-223 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

import argparse


def add_parser(commands) -> None:
    run = commands.add_parser("run-command")
    run.add_argument("--timeout", type=int, default=120)
    run.add_argument("argv", nargs=argparse.REMAINDER)
