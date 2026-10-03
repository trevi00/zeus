"""The `zeus serve` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus serve`)
Does not own: dispatch and composition (S10 unit C5)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:224-227 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    s = commands.add_parser("serve")
    s.add_argument("--agent", required=True)
    s.add_argument("--once", action="store_true")
    s.add_argument("--execute", action="store_true")
