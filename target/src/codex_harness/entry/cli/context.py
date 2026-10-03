"""The `zeus context` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus context`)
Does not own: dispatch and composition (S10 unit C3)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:262-265 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    context = commands.add_parser("context")
    context.add_argument("query")
    context.add_argument("--agent", default="worker:implementation")
    context.add_argument("--budget", type=int, default=12000)
