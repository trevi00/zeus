"""The `zeus observe` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus observe`)
Does not own: dispatch and composition (S10 unit C4)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:277-285 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    observe = commands.add_parser("observe", help="Observation logs: collect the spool, report status, reconcile")
    observe_commands = observe.add_subparsers(dest="observe_command", required=True)
    observe_commands.add_parser("collect", help="Move durable spool records into PostgreSQL and acknowledge them")
    observe_commands.add_parser("status", help="Counts, process health, pending terminations, orphans; read-only")
    reconcile = observe_commands.add_parser("reconcile", help="Operator decision for a pending termination record")
    reconcile.add_argument("record_id")
    reconcile.add_argument("--resolution", choices=["rerun", "discard"], required=True)
    reconcile.add_argument("--operator", required=True, help="Audit label, not authenticated identity")
    reconcile.add_argument("--reason", required=True)
