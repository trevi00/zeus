"""The `zeus cleanup` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus cleanup`)
Does not own: dispatch and composition (S10 unit C5)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:209-210 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("--apply", action="store_true")
