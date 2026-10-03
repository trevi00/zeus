"""The `zeus audit-repair` argument parser (M7 adapters/audit_repair_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus audit-repair`)
Does not own: dispatch and composition (S10 unit C7)
Entry points: add_parser
Contracts: none

Moved from M7 adapters/audit_repair_cli.py:18-39 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    repair = commands.add_parser("audit-repair", help="Opt-in, inspect and report the ONE bounded "
                                 "corrective successor of a rejected source audit analysis")
    sub = repair.add_subparsers(dest="audit_repair_command", required=True)
    enable = sub.add_parser("enable", help="Scope this owner to ONE audit and ONE rejected task; "
                                           "creates no task and admits nothing by itself")
    enable.add_argument("--audit-id", required=True, dest="audit_id")
    enable.add_argument("--task-id", required=True, dest="task_id",
                        help="The rejected analysis task this correction is allowed to succeed")
    enable.add_argument("--operator", required=True,
                        help="Audit label, not authenticated identity")
    disable = sub.add_parser("disable", help="Close admission; recorded lineages and their evidence "
                                             "are untouched and a queued successor keeps its record")
    disable.add_argument("--audit-id", required=True, dest="audit_id")
    disable.add_argument("--operator", required=True)
    inspect = sub.add_parser("inspect", help="Read-only diagnosis of this audit's rejected analyses; "
                                             "creates no task and writes nothing")
    inspect.add_argument("--audit-id", required=True, dest="audit_id")
    inspect.add_argument("--task-id", default=None, dest="task_id")
    status = sub.add_parser("status", help="The opt-in, the lineages and the separate counts; "
                                           "store read only")
    status.add_argument("--audit-id", required=True, dest="audit_id")
