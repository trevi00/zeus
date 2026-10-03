"""The `zeus index` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus index`)
Does not own: dispatch and composition (S10 unit C3)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:250-251 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    index = commands.add_parser("index")
    index.add_argument("root", nargs="?", default=".")
