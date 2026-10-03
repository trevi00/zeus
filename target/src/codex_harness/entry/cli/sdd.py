"""The `zeus sdd` argument parser (M7 adapters/sdd_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus sdd`)
Does not own: dispatch and composition (S10 unit C2)
Entry points: add_parser
Contracts: none

Moved from M7 adapters/sdd_cli.py:16-43 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

from pathlib import Path


def add_parser(commands):
    parser = commands.add_parser("sdd", help="Strict specs, observation proposals and eight-stage preparation reports")
    sub = parser.add_subparsers(dest="sdd_command", required=True)
    sub.add_parser("device-check", help="Discover connected devices; never certify acceptance")
    for name in ("inspect", "view", "export-replay", "register"):
        p = sub.add_parser(name)
        p.add_argument("file", type=Path)
        p.add_argument("--git-revision")
        if name in {"view", "export-replay"}:
            p.add_argument("--output", type=Path, required=True)
        if name == "register":
            p.add_argument("--ticket", required=True)
            p.add_argument("--ticket-revision", type=int, required=True)
    for name in ("status", "view-iteration", "import-log", "propose", "advance", "transfer-record"):
        p = sub.add_parser(name)
        p.add_argument("iteration_id")
        if name == "view-iteration":
            p.add_argument("--output", type=Path, required=True)
        if name == "import-log":
            p.add_argument("--environment", type=Path, required=True)
            p.add_argument("--events", type=Path, required=True)
            p.add_argument("--source", required=True)
        if name == "propose":
            p.add_argument("--observation", required=True)
        if name == "advance":
            p.add_argument("--sequence", type=int, required=True)
        if name == "transfer-record":
            p.add_argument("--file", type=Path, required=True)
