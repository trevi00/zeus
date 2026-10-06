"""The `zeus audit-repair` argument parser (M7 adapters/audit_repair_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus audit-repair`), run (its body: M7 audit_repair_command) and _execute (M7 audit_repair_cli.execute)
Does not own: dispatch (entry.cli main) and composition (composition.audit_repair)
Entry points: add_parser, run
Contracts: INV-AUDIT-REPAIR-001

Moved from M7 adapters/audit_repair_cli.py:18-39 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is M7 `cli.py` `audit_repair_command` (:602-613) and `_execute` is `adapters/audit_repair_cli.py:42-60` (`execute`), both verbatim except that the service is built first (as M7 `main()` did), `refusal` is `entry.cli.operation.refusal` and the repair owner is `composition.audit_repair.build_repair` (S10 unit C7a, R-c11).
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


def run(args) -> None:
    """INV-AUDIT-REPAIR-001: exit 0 only for a completed owner command; refusals print a code and a
    type, never a model draft, a validator message, source text or a raw exception."""
    from codex_harness.composition import build
    from codex_harness.entry.cli.operation import refusal
    from codex_harness.entry.cli.output import emit
    service = build()
    try:
        result = _execute(service, args)
    except Exception as exc:
        emit(refusal(exc))
        raise SystemExit(1) from exc
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def _execute(service, args, repair=None) -> dict:
    """One command, one bounded result. `repair` is injected by the tests; the default wiring builds
    the same owner over this host's store and artifact root."""
    from codex_harness.composition.audit_repair import build_repair
    from codex_harness.entry.cli.operation import refusal

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
