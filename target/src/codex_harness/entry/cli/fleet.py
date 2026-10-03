"""The `zeus fleet` argument parser (M7 adapters/fleet_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus fleet`)
Does not own: dispatch and composition (S10 unit C8)
Entry points: add_parser
Contracts: none

Moved from M7 adapters/fleet_cli.py:25-77 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

from pathlib import Path

from codex_harness.kernel.usage import MODES


def add_parser(commands) -> None:
    fleet = commands.add_parser("fleet", help="Bounded multi-lane admission of operation manifests; no conductor")
    sub = fleet.add_subparsers(dest="fleet_command", required=True)
    register = sub.add_parser("register", help="Register the one host fleet configuration (urn:zeus:fleet:1)")
    register.add_argument("--file", type=Path, required=True)
    enqueue = sub.add_parser("enqueue", help="Queue one validated operation manifest on a lane")
    enqueue.add_argument("--lane", required=True)
    enqueue.add_argument("--file", type=Path, required=True, help="Operation manifest JSON")
    enqueue.add_argument("--after", action="append", default=[], help="Job id that must be accepted first; repeatable")
    run = sub.add_parser("run", help="Admit and dispatch queued jobs up to max_parallel")
    run.add_argument("--once", action="store_true", help="Drain runnable work, then exit")
    sub.add_parser("pause", help="Stop new admissions; running work finishes")
    sub.add_parser("resume", help="Allow new admissions again")
    grant = sub.add_parser("authorize-budget", help="Operator grant of higher effective ceilings; idle fleet only")
    grant.add_argument("--per-host", type=int, required=True, dest="per_host")
    grant.add_argument("--total", type=int, required=True)
    grant.add_argument("--expected-total", type=int, required=True, dest="expected_total",
                       help="The current effective total; refused when it no longer matches")
    grant.add_argument("--mode", choices=list(MODES), default=None,
                       help="Accounting mode for new work: finite (numbers are ceilings) or subscription "
                            "(every call recorded, numbers retained as migration metadata); omitted keeps the current mode")
    delivery = sub.add_parser("record-delivery", help="Record the owner's merge/deploy evidence for an "
                              "accepted job (urn:zeus:owner-delivery:1); trusted owner CLI only")
    delivery.add_argument("--job", required=True, help="Existing accepted fleet job id")
    delivery.add_argument("--file", type=Path, required=True, help="Owner delivery document JSON")
    reconcile = sub.add_parser("reconcile-interrupted", help="Settle one interrupted job from proven-dead "
                               "evidence (urn:zeus:fleet-recovery-evidence:1); paused fleet, owner CLI only")
    reconcile.add_argument("--file", type=Path, required=True, help="Owner recovery evidence document JSON")
    reconcile.add_argument("--docker", default="docker", help="Docker client used to inspect the named container")
    relocate = sub.add_parser("relocate", help="Move lane repository/runtime paths to verified copies "
                              "(urn:zeus:fleet-relocation:1); paused, idle fleet, owner CLI only")
    relocate.add_argument("--file", type=Path, required=True, help="Owner relocation request document JSON")
    relocate.add_argument("--journal", type=Path, required=True,
                          help="Service lifecycle journal of the Fleet CLI; the runner must be stopped in it")
    relocate.add_argument("--docker", default="docker", help="Docker client used to inspect retained lane runs")
    migrate = sub.add_parser("migrate-host", help="Rebind every lane's repository/runtime/schema to this "
                             "target host after a host migration restore (urn:zeus:fleet-host-migration:1); "
                             "paused, idle fleet, owner CLI only")
    migrate.add_argument("--file", type=Path, required=True, help="Owner host migration request document JSON")
    migrate.add_argument("--journal", type=Path, required=True,
                         help="Service lifecycle journal of the Fleet service; the runner must be stopped in it")
    migrate.add_argument("--docker", default="docker", help="Docker client used to inspect retained lane runs")
    sub.add_parser("status", help="Read the fleet projection; store read only")
    backlog = sub.add_parser("backlog", help="Approved Git-pinned backlog: register, tick, status")
    backlog_sub = backlog.add_subparsers(dest="backlog_command", required=True)
    backlog_register = backlog_sub.add_parser("register", help="Register one owner-approved plan read at a commit")
    backlog_register.add_argument("--lane", required=True, help="Lane whose repository holds the plan")
    backlog_register.add_argument("--revision", required=True, help="40-hex commit the plan is read at")
    backlog_register.add_argument("--path", required=True, help="Repository-relative plan path")
    backlog_tick = backlog_sub.add_parser("tick", help="Select and admit at most one eligible successor")
    backlog_tick.add_argument("--plan", required=True, help="Registered plan id")
    backlog_status = backlog_sub.add_parser("status", help="Read the backlog projection; store read only")
    backlog_status.add_argument("--plan", default=None, help="One plan id; omitted reads every registered plan")
