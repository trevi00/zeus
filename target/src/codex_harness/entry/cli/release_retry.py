"""The `zeus release-retry` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus release-retry`)
Does not own: dispatch and composition (S10 unit C2)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:205-208 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    release = commands.add_parser("release-retry")
    release.add_argument("release_id")
    release.add_argument("--reason", required=True)
