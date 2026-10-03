"""The `zeus improve` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus improve`)
Does not own: dispatch and composition (S10 unit C5)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:233-236 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    improve = commands.add_parser("improve")
    improve.add_argument("objective")
    improve.add_argument("--acceptance", action="append", required=True)
    improve.add_argument("--importance", choices=["simple", "important"])
