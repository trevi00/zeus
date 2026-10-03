"""The `zeus audit-service` argument parser (M7 adapters/audit_service.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus audit-service`)
Does not own: dispatch and composition (S10 unit C6)
Entry points: add_parser
Contracts: none

Moved from M7 adapters/audit_service.py:221-236 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    service = commands.add_parser("audit-service", help="Run ONE selected source audit through the "
                                  "existing scheduler, Workflow and executor; no release activation")
    sub = service.add_subparsers(dest="audit_service_command", required=True)
    run_command = sub.add_parser("run", help="Own this runtime and execute the selected audit's "
                                 "partition assignments one at a time")
    run_command.add_argument("--audit-id", required=True, dest="audit_id",
                             help="The explicitly selected audit; unrelated audits are never executed")
    run_command.add_argument("--max-tasks", type=int, default=None, dest="max_tasks",
                             help="Finite acceptance mode: stop after N successful task completions "
                                  "(1..100). Not a subscription call cap; queued successors are kept")
    run_command.add_argument("--once", action="store_true",
                             help="Do the work that is ready now, then exit instead of waiting")
    status_command = sub.add_parser("status", help="Read the service state and the durable audit "
                                    "records; store read only")
    status_command.add_argument("--audit-id", required=True, dest="audit_id")
