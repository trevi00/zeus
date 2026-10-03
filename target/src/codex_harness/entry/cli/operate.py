"""The `zeus operate` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus operate`)
Does not own: dispatch and composition (S10 unit C6)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:300-305 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

from pathlib import Path


def add_parser(commands) -> None:
    operate = commands.add_parser("operate", help="One bounded operation: worker, evidence gate, lead review; no conductor")
    operate_commands = operate.add_subparsers(dest="operate_command", required=True)
    operate_run = operate_commands.add_parser("run", help="Claim the manifest id and run it to a terminal receipt")
    operate_run.add_argument("--file", type=Path, required=True, help="Operation manifest JSON (urn:zeus:operation:1)")
    operate_status = operate_commands.add_parser("status", help="Read the saved receipt; store read only")
    operate_status.add_argument("operation_id")
