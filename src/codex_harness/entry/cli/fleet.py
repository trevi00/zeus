"""The `zeus fleet` root: the argument parser and the command bodies (M7 adapters/fleet_cli.py, cli.py fleet_command).

Layer: entry
Owns: add_parser (the argument shape of `zeus fleet`), run (its body: M7 fleet_command) and the private _check_resolved, _register, _enqueue, _record_delivery, _grant_permit, _status, _backlog and _execute (M7 fleet_cli)
Does not own: dispatch (entry.cli main), the runner, the backlog and recovery wiring (composition.cli_fleet, composition.fleet_backlog) and the shared helpers (entry.cli.operation)
Entry points: add_parser, run
Contracts: INV-FLEET-001, INV-FLEET-BACKLOG-001

Moved from M7 adapters/fleet_cli.py:25-77 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
`run` is M7 `cli.py` `fleet_command` (:496-507) and `_check_resolved`, `_register`, `_enqueue`, `_record_delivery`, `_status`, `_backlog` and `_execute` are `adapters/fleet_cli.py` `check_resolved` (:108-118), `register` (:121-123), `enqueue` (:126-132),
`record_delivery` (:191-195), `status` (:318-321), `backlog` (:324-343) and `execute` (:346-372) (R-c28, S10 unit C8b-2): the bodies are M7's verbatim except that the service is built first (as M7 `main()` did), `Fleet(store)` is the
split owner of the method (the table of `composition.cli_fleet`), `GitSource` is `composition.cli_research.git_source`, `packaged_policy` is `composition.cli_operation`'s and `bind_goal`, `read_manifest` and `refusal` are `entry.cli.operation`'s
(`bind_goal` is looked up through that module at call time). The `run`, `reconcile-interrupted`, `relocate` and `migrate-host` branches call `composition.cli_fleet`; the three owner documents are read here (`read_manifest`, which
composition may not import) and handed over. Imports sit inside the functions, so importing this module stays light.
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
    grant_permit = sub.add_parser("grant-permit", help="Grant and acknowledge the one-use admission permit of the "
                                  "OA delivery canary a digest-bound template names (urn:zeus:fleet-admission-permit:1); "
                                  "owner-paused fleet, trusted owner CLI only")
    grant_permit.add_argument("--template", required=True, help="sha256 digest of the approved template document")
    grant_permit.add_argument("--file", type=Path, required=True, help="The approved template document JSON")
    admit_permit = sub.add_parser("admit-permit", help="Claim, launch and settle the one job of a granted admission "
                                  "permit; owner-paused fleet, trusted owner CLI only")
    admit_permit.add_argument("--permit", required=True, help="Permit id")
    admit_permit.add_argument("--max-wait-seconds", type=int, default=900, dest="max_wait_seconds",
                              help="Bound of the wait for the one launched job; a child still running is never killed")
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


def run(args) -> None:
    """INV-FLEET-001: exit 0 only for a completed command; refusals print a code and a type, never
    manifests, paths, schemas, DSNs, raw exceptions or process output."""
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


def _check_resolved(config: dict) -> dict:
    """Adapter-side filesystem facts the grammar cannot know: each path is its own resolution and
    every repository is an existing directory. Runtime roots may not exist yet."""
    from codex_harness.coordination.domain.fleet import FleetRefused

    for index, lane in enumerate(config["lanes"]):
        for key in ("repository", "runtime"):
            path = Path(lane[key])
            if path.resolve() != path:
                raise FleetRefused("path_unresolved", "lanes[" + str(index) + "]." + key)
        if not Path(lane["repository"]).is_dir():
            raise FleetRefused("repository_missing", "lanes[" + str(index) + "].repository")
    return config


def _register(service, args) -> dict:
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.domain.fleet import validate_config
    from codex_harness.entry.cli.operation import read_manifest

    config = _check_resolved(validate_config(read_manifest(args.file)))
    return {**FleetRegistry(service.store).register(config), "exit_code": 0}


def _enqueue(service, args) -> dict:
    from codex_harness.composition.cli_operation import packaged_policy
    from codex_harness.composition.cli_research import git_source
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.domain.fleet import lane_of
    from codex_harness.coordination.domain.operation import validate_manifest
    from codex_harness.entry.cli.operation import bind_goal, read_manifest

    fleet = FleetRegistry(service.store)
    lane = lane_of(fleet.registered()["config"], args.lane)
    manifest = validate_manifest(read_manifest(args.file), packaged_policy())
    # The goal is bound at the configured lane repository, never at the current directory.
    goal = bind_goal(manifest, git_source(lane["repository"]))
    return {**fleet.enqueue(args.lane, manifest, goal, args.after), "exit_code": 0}


def _record_delivery(service, args) -> dict:
    """The owner states what they verified from a preserved receipt. This CLI is the only writer:
    no web request and no model run records a delivery, and recording one changes no job status."""
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.entry.cli.operation import read_manifest

    document = read_manifest(args.file)
    return {**FleetRegistry(service.store).record_delivery(args.job, document), "exit_code": 0}


def _grant_permit(service, args) -> dict:
    """INV-FLEET-001 (FA-SPEC A2): the digest on argv names the approved template; the document is validated against
    it before any store read, and the binding and deadline are derived from the store, never from argv."""
    from codex_harness.coordination.application.fleet.admission_permit import FleetAdmissionPermits
    from codex_harness.entry.cli.operation import read_manifest

    return {**FleetAdmissionPermits(service.store).grant_admission_permit(args.template, read_manifest(args.file)),
            "exit_code": 0}


def _status(service, args) -> dict:
    from codex_harness.coordination.application.fleet.registry import FleetRegistry

    # Store read only: no executor, observer, bus, budget or provider is built.
    fleet = FleetRegistry(service.store)
    return {**fleet.status(), "reconciliation_required": fleet.reconciliation_required(), "exit_code": 0}


def _backlog(service, args) -> dict:
    """`zeus fleet backlog register|tick|status`. Git reads and manifest validation happen in the
    adapter, outside every store transaction; admission itself is the unchanged `FleetRegistry.enqueue`."""
    from codex_harness.composition.fleet_backlog import register_plan, tick_plan
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.application.fleet_backlog import FleetBacklog
    from codex_harness.intake.domain.backlog import FAILED_OUTCOMES

    command = args.backlog_command
    if command == "register":
        config = FleetRegistry(service.store).registered()["config"]
        return {**register_plan(service.store, config, args.lane, args.revision, args.path), "exit_code": 0}
    if command == "tick":
        config = FleetRegistry(service.store).registered()["config"]
        result = tick_plan(service.store, config, args.plan)
        return {**result, "exit_code": 1 if result["outcome"] in FAILED_OUTCOMES else 0}
    plan_id = getattr(args, "plan", None)
    projection = FleetBacklog(service.store).status(plan_id)
    # A named plan that is not registered is a refusal; listing every plan is a successful read
    # even when nothing is registered yet.
    return {**projection, "exit_code": 1 if plan_id is not None and not projection["registered"] else 0}


def _execute(service, args) -> dict:
    from codex_harness.composition import cli_fleet
    from codex_harness.coordination.application.fleet.pause import FleetPause
    from codex_harness.entry.cli.operation import read_manifest

    command = args.fleet_command
    if command == "register":
        return _register(service, args)
    if command == "enqueue":
        return _enqueue(service, args)
    if command == "run":
        return cli_fleet.run_fleet(service, args)
    if command == "pause":
        return {**FleetPause(service.store).pause(), "exit_code": 0}
    if command == "resume":
        return {**FleetPause(service.store).resume(), "exit_code": 0}
    if command == "record-delivery":
        return _record_delivery(service, args)
    if command == "backlog":
        return _backlog(service, args)
    if command == "grant-permit":
        return _grant_permit(service, args)
    if command == "admit-permit":
        return cli_fleet.admit_permit(service, args)
    if command == "reconcile-interrupted":
        return cli_fleet.reconcile_interrupted(service, args, read_manifest(args.file))
    if command == "relocate":
        return cli_fleet.relocate(service, args, read_manifest(args.file))
    if command == "migrate-host":
        return cli_fleet.migrate_host(service, args, read_manifest(args.file))
    if command == "authorize-budget":
        grant = FleetPause(service.store).authorize_budget(args.per_host, args.total, args.expected_total,
                                                           mode=getattr(args, "mode", None))
        return {**grant, "exit_code": 0}
    return _status(service, args)
