"""`zeus audit-repair enable|disable|inspect|status`: the owner's entry point to the bounded repair
lineage of ONE rejected source audit analysis (INV-AUDIT-REPAIR-001).

Every subcommand here is store (and artifact) reading plus, for `enable`/`disable`, ONE narrow
activation row. None of them creates a task, publishes a message, enters an executor, a transport or
a provider, activates a release, merges, deploys or runs an audit action: the corrective successor
is admitted by the existing `zeus audit-service run` tick, and only while this audit is enabled.
Output is identifiers, fixed codes and counts; a refusal prints its code and the exception type,
never a model draft, a validator message, source text or a raw exception.
"""
from __future__ import annotations

from codex_harness.adapters.operation_cli import refusal

__all__ = ["add_parser", "execute", "refusal"]


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


def execute(service, args, repair=None) -> dict:
    """One command, one bounded result. `repair` is injected by the tests; the default wiring builds
    the same owner over this host's store and artifact root."""
    from codex_harness.adapters.audit_repair import build_repair

    try:
        owner = build_repair(service) if repair is None else repair
        command = args.audit_repair_command
        if command == "enable":
            result = owner.enable(args.audit_id, args.task_id, operator=args.operator)
        elif command == "disable":
            result = owner.disable(args.audit_id, operator=args.operator)
        elif command == "inspect":
            result = owner.inspect(args.audit_id, args.task_id)
        else:
            result = owner.status(args.audit_id)
    except Exception as exc:
        return refusal(exc)
    return {"audit_repair": command, **result, "exit_code": 0}
