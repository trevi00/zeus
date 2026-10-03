"""The `zeus demo` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus demo`)
Does not own: dispatch and composition (S10 unit C2)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:214-215 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    d = commands.add_parser("demo")
    d.add_argument("--scope", default="bootstrap/windows/codex")
