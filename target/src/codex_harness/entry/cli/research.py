"""The `zeus research` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus research`)
Does not own: dispatch and composition (S10 unit C5)
Entry points: add_parser
Contracts: INV-DISCOVERY-PRESSURE-001

Moved from M7 cli.py:228-232 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    research = commands.add_parser("research")
    research.add_argument("source", choices=["github", "geeknews"])
    # INV-DISCOVERY-PRESSURE-001: why this fetch happens; carried in the task and checked before any fetch.
    research.add_argument("--intent", required=True,
                          choices=["proactive", "user_request", "incident", "existing_work_result", "task_required"])
