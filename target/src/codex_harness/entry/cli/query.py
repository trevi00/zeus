"""The `zeus query` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus query`)
Does not own: dispatch and composition (S10 unit C3)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:252-254 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    q = commands.add_parser("query")
    q.add_argument("text")
    q.add_argument("--semantic", action="store_true")
