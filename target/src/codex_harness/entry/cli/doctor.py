"""The `zeus doctor` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus doctor`)
Does not own: dispatch and composition (S10 unit C1)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:202-203 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--offline", action="store_true", help="Check installation without a database")
