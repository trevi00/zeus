"""The `zeus dge` argument parser (M7 adapters/dge_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus dge`)
Does not own: dispatch and composition (S10 unit C7)
Entry points: add_parser
Contracts: none

Moved from M7 adapters/dge_cli.py:69-78 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

from pathlib import Path


def add_parser(commands) -> None:
    dge = commands.add_parser("dge", help="Research-bound design control: register packet, submit debate event, status")
    sub = dge.add_subparsers(dest="dge_command", required=True)
    reg = sub.add_parser("register", help="Verify pinned sources through git and register the packet (urn:zeus:research-packet:1)")
    reg.add_argument("--file", type=Path, required=True)
    put = sub.add_parser("submit", help="Record one operator-submitted debate event (urn:zeus:debate-event:1)")
    put.add_argument("session_id")
    put.add_argument("--file", type=Path, required=True)
    show = sub.add_parser("status", help="Safe session summary; store read only")
    show.add_argument("session_id")
