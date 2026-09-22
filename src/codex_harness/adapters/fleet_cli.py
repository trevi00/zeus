"""`zeus fleet register|enqueue|run|pause|resume|authorize-budget|status|backlog`: thin wiring
around application.fleet. `authorize-budget` is the operator's explicit grant under the trusted
local CLI; nothing in the dispatcher or a model run calls it. `backlog register|tick|status`
(INV-FLEET-BACKLOG-001) admits already approved Git-pinned work through the same `Fleet.enqueue`;
it adds no executor, no scheduler process and no authority of its own."""
from __future__ import annotations

import signal
from pathlib import Path

from codex_harness.adapters.operation_cli import GitSource, bind_goal, read_manifest, refusal
from codex_harness.adapters.providers import packaged_policy
from codex_harness.application.fleet import Fleet, FleetRunner
from codex_harness.domain.fleet import FleetRefused, lane_of, validate_config
from codex_harness.domain.operation import validate_manifest
from codex_harness.domain.usage_policy import MODES

__all__ = ["add_parser", "execute", "refusal"]


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


def check_resolved(config: dict) -> dict:
    """Adapter-side filesystem facts the grammar cannot know: each path is its own resolution and
    every repository is an existing directory. Runtime roots may not exist yet."""
    for index, lane in enumerate(config["lanes"]):
        for key in ("repository", "runtime"):
            path = Path(lane[key])
            if path.resolve() != path:
                raise FleetRefused("path_unresolved", "lanes[" + str(index) + "]." + key)
        if not Path(lane["repository"]).is_dir():
            raise FleetRefused("repository_missing", "lanes[" + str(index) + "].repository")
    return config


def register(service, args) -> dict:
    config = check_resolved(validate_config(read_manifest(args.file)))
    return {**Fleet(service.store).register(config), "exit_code": 0}


def enqueue(service, args) -> dict:
    fleet = Fleet(service.store)
    lane = lane_of(fleet.registered()["config"], args.lane)
    manifest = validate_manifest(read_manifest(args.file), packaged_policy())
    # The goal is bound at the configured lane repository, never at the current directory.
    goal = bind_goal(manifest, GitSource(lane["repository"]))
    return {**fleet.enqueue(args.lane, manifest, goal, args.after), "exit_code": 0}


def run(service, args) -> dict:
    from codex_harness.adapters.configuration import settings
    from codex_harness.adapters.fleet_backlog import backlog_ticker, configured_plan
    from codex_harness.adapters.fleet_runtime import LaneLauncher
    from codex_harness.adapters.portfolio import portfolio_reconciler

    fleet = Fleet(service.store)
    config = fleet.registered()["config"]
    host = settings()
    # Opt-in only (INV-FLEET-BACKLOG-001): without the host plan setting the runner keeps its exact
    # previous behaviour and never selects work of its own.
    plan_id = configured_plan(host)
    backlog_tick = None if plan_id is None else backlog_ticker(service.store, config, plan_id)
    # The bounded portfolio pass is wired here, in the adapter: the runner keeps no portfolio
    # dependency and a reconciliation outage never blocks admission (operating-portfolio-001).
    runner = FleetRunner(fleet, LaneLauncher(config, host), reconcile=portfolio_reconciler(service.store),
                         backlog=backlog_tick)
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            # Graceful stop: admission closes, owned children are drained, nothing is killed.
            signal.signal(getattr(signal, name), lambda *_: runner.stop())
    return {**runner.run(once=bool(args.once)), "exit_code": 0}


def record_delivery(service, args) -> dict:
    """The owner states what they verified from a preserved receipt. This CLI is the only writer:
    no web request and no model run records a delivery, and recording one changes no job status."""
    document = read_manifest(args.file)
    return {**Fleet(service.store).record_delivery(args.job, document), "exit_code": 0}


def status(service, args) -> dict:
    # Store read only: no executor, observer, bus, budget or provider is built.
    fleet = Fleet(service.store)
    return {**fleet.status(), "reconciliation_required": fleet.reconciliation_required(), "exit_code": 0}


def backlog(service, args) -> dict:
    """`zeus fleet backlog register|tick|status`. Git reads and manifest validation happen in the
    adapter, outside every store transaction; admission itself is the unchanged `Fleet.enqueue`."""
    from codex_harness.adapters.fleet_backlog import register_plan, tick_plan
    from codex_harness.application.fleet_backlog import FleetBacklog
    from codex_harness.domain.fleet_backlog import FAILED_OUTCOMES

    command = args.backlog_command
    if command == "register":
        config = Fleet(service.store).registered()["config"]
        return {**register_plan(service.store, config, args.lane, args.revision, args.path), "exit_code": 0}
    if command == "tick":
        config = Fleet(service.store).registered()["config"]
        result = tick_plan(service.store, config, args.plan)
        return {**result, "exit_code": 1 if result["outcome"] in FAILED_OUTCOMES else 0}
    plan_id = getattr(args, "plan", None)
    projection = FleetBacklog(service.store).status(plan_id)
    # A named plan that is not registered is a refusal; listing every plan is a successful read
    # even when nothing is registered yet.
    return {**projection, "exit_code": 1 if plan_id is not None and not projection["registered"] else 0}


def execute(service, args) -> dict:
    command = args.fleet_command
    if command == "register":
        return register(service, args)
    if command == "enqueue":
        return enqueue(service, args)
    if command == "run":
        return run(service, args)
    if command == "pause":
        return {**Fleet(service.store).pause(), "exit_code": 0}
    if command == "resume":
        return {**Fleet(service.store).resume(), "exit_code": 0}
    if command == "record-delivery":
        return record_delivery(service, args)
    if command == "backlog":
        return backlog(service, args)
    if command == "authorize-budget":
        grant = Fleet(service.store).authorize_budget(args.per_host, args.total, args.expected_total,
                                                      mode=getattr(args, "mode", None))
        return {**grant, "exit_code": 0}
    return status(service, args)
