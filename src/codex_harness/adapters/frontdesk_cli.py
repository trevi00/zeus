"""`zeus desk run --revision <40hex> [--once]`: the one local front-door runner.

Thin wiring of the real services around `application.frontdesk`: a runtime FileLock so exactly one
runner owns the desk on this host, the existing executor (no knowledge adapter), the existing
Redis bus, Workflow, observer, collector and the machine call ledger through `BudgetedExecutor`.
The ceilings are the CURRENT effective fleet accounting mode, so a subscription fleet records its
provider calls instead of being refused by stale ceiling numbers.

Nothing here retries a failed or uncertain turn, takes over a running owner, merges, deploys or
promotes an answer to knowledge.
"""
from __future__ import annotations

import signal

from codex_harness.adapters.operation_cli import refusal
from codex_harness.application.frontdesk import ACTION, LEAD, DeskRunner, FrontDesk
from codex_harness.domain.frontdesk import DeskRefused, revision
from codex_harness.domain.model_routing import select_model

__all__ = ["add_parser", "desk_refusal", "execute", "refusal"]


def add_parser(commands) -> None:
    desk = commands.add_parser("desk", help="Local front-door conversation runner; no conductor, no retries")
    sub = desk.add_subparsers(dest="desk_command", required=True)
    run = sub.add_parser("run", help="Own the desk and process queued local requests one at a time")
    run.add_argument("--revision", required=True, help="Full 40-hex base revision every request is answered at")
    run.add_argument("--once", action="store_true", help="Process what is queued now, then exit")
    status = sub.add_parser("status", help="Read desk sessions; store read only")
    status.add_argument("--revision", required=True, help="Full 40-hex base revision of this desk")


def effective_ceilings(store) -> dict:
    """The CURRENT effective fleet budget, including its accounting mode; unregistered fleets keep
    the packaged runtime policy's conservative finite ceiling for this local turn."""
    from codex_harness.application.fleet import Fleet
    from codex_harness.domain.fleet import FleetRefused

    try:
        return dict(Fleet(store).registered()["config"]["budget"])
    except FleetRefused:
        return {"per_host": 1, "total": 1}


def build_runner(service, args):
    from codex_harness.adapters.bus import RedisBus
    from codex_harness.adapters.call_budget import CallBudget
    from codex_harness.application.operation import BudgetedExecutor
    from codex_harness.application.workflow import Workflow
    from codex_harness.bootstrap import build_executor, build_observer, redis_url

    base = revision(args.revision)
    desk = FrontDesk(service, base)
    observer = build_observer(service.store, "cli.desk", role=LEAD)
    # No knowledge adapter: a conversational turn writes no ontology and promotes nothing.
    executor = build_executor(service, observer=observer, knowledge=False)
    # The explicit Codex model label comes from the existing routing, never from the browser.
    model = select_model("design").requested_model
    wrapped = BudgetedExecutor(executor, CallBudget(), effective_ceilings(service.store),
                               "frontdesk", model, labels=lambda kind, agent: ("codex", model))
    runner = DeskRunner(service, desk, wrapped, RedisBus(redis_url()),
                        Workflow(service.store, service.org), observer=observer)
    return runner, observer


def run(service, args) -> dict:
    from filelock import FileLock, Timeout

    from codex_harness.adapters.configuration import runtime_dir

    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(runtime / "frontdesk.lock"), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        return {"status": "refused", "reason_code": "desk_lock_busy", "exit_code": 1}
    runner, observer = build_runner(service, args)
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            # Interrupt shutdown: no new turn is claimed; a claimed turn records its own outcome.
            signal.signal(getattr(signal, name), lambda *_: runner.stop())
    try:
        summary = runner.run(once=bool(args.once))
    finally:
        observer.close()
        lock.release()
    return {"desk": ACTION, "revision": args.revision, **summary, "exit_code": 0}


def status(service, args) -> dict:
    # Store read only: no executor, observer, bus, budget or provider is built.
    return {**FrontDesk(service, revision(args.revision)).sessions(), "exit_code": 0}


def execute(service, args) -> dict:
    if args.desk_command == "run":
        return run(service, args)
    return status(service, args)


def desk_refusal(exc: Exception) -> dict:
    """What the CLI prints for a failure: a code and a type, never conversation text or raw errors."""
    if isinstance(exc, DeskRefused):
        return {"status": "refused", "reason_code": exc.reason_code, "error_type": type(exc).__name__,
                "exit_code": 1}
    return refusal(exc)
