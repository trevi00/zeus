"""The `zeus goal` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus goal`)
Does not own: dispatch and composition (S10 unit C2)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:382-388 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

from pathlib import Path


def add_parser(commands) -> None:
    goal = commands.add_parser("goal", help="Goal manifest progress: read-only report and same-definition compare")
    goal_commands = goal.add_subparsers(dest="goal_command", required=True)
    report = goal_commands.add_parser("report", help="Observe criterion closure state; no completion authority")
    report.add_argument("manifest", type=Path)
    compare = goal_commands.add_parser("compare", help="Gained/regressed criteria between two reports of one definition")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
