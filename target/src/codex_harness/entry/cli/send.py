"""The `zeus send` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus send`)
Does not own: dispatch and composition (S10 unit C4)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:219-220 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    send = commands.add_parser("send")
    send.add_argument("file")
