"""`zeus fleet register|enqueue|run|pause|resume|authorize-budget|status`: thin wiring around
application.fleet. `authorize-budget` is the operator's explicit grant under the trusted local CLI;
nothing in the dispatcher or a model run calls it."""
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
    sub.add_parser("status", help="Read the fleet projection; store read only")


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
    from codex_harness.adapters.fleet_runtime import LaneLauncher

    fleet = Fleet(service.store)
    config = fleet.registered()["config"]
    runner = FleetRunner(fleet, LaneLauncher(config, settings()))
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            # Graceful stop: admission closes, owned children are drained, nothing is killed.
            signal.signal(getattr(signal, name), lambda *_: runner.stop())
    return {**runner.run(once=bool(args.once)), "exit_code": 0}


def status(service, args) -> dict:
    # Store read only: no executor, observer, bus, budget or provider is built.
    fleet = Fleet(service.store)
    return {**fleet.status(), "reconciliation_required": fleet.reconciliation_required(), "exit_code": 0}


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
    if command == "authorize-budget":
        grant = Fleet(service.store).authorize_budget(args.per_host, args.total, args.expected_total,
                                                      mode=getattr(args, "mode", None))
        return {**grant, "exit_code": 0}
    return status(service, args)
