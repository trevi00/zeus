"""The `zeus artifact` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus artifact`)
Does not own: dispatch and composition (S10 unit C5)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:245-249 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    artifact = commands.add_parser("artifact")
    artifact.add_argument("reference")
    artifact.add_argument("--start", type=int, default=0)
    artifact.add_argument("--length", type=int, default=8000)
    artifact.add_argument("--search")
