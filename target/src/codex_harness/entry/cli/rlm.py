"""The `zeus rlm` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus rlm`)
Does not own: dispatch and composition (S10 unit C5)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:258-261 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    rlm = commands.add_parser("rlm")
    rlm.add_argument("reference")
    rlm.add_argument("question")
    rlm.add_argument("--max-calls", type=int, default=8)
