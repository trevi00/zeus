"""The `zeus seed-research-backlog` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus seed-research-backlog`)
Does not own: dispatch and composition (S10 unit C2)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:200-201 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    seed = commands.add_parser("seed-research-backlog")
    seed.add_argument("--artifacts", required=True)
