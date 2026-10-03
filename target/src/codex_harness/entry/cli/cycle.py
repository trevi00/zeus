"""The `zeus cycle` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus cycle`)
Does not own: dispatch and composition (S10 unit C5)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:291-299 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    cycle = commands.add_parser("cycle", help="Bounded persistent execution loop over one correlation; no conductor")
    cycle_commands = cycle.add_subparsers(dest="cycle_command", required=True)
    for name in ("start", "status", "handoff", "step"):
        sub = cycle_commands.add_parser(name)
        sub.add_argument("cycle_id")
        if name == "start":
            sub.add_argument("--correlation", required=True)
            sub.add_argument("--max-executions", type=int, required=True,
                             help="Executor starts allowed through this cycle; not a billing count")
