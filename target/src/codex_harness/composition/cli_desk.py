"""The `zeus desk` composition: the desk runner wiring, the effective ceilings and the lock-and-signal `run`.

Layer: composition
Owns: effective_ceilings, build_runner, run_desk, front_desk
Does not own: the argument shape and the command bodies (entry.cli.desk), the desk use cases (intake.application.frontdesk, coordination.application.desk_runner) and the executor builder (composition.operation)
Entry points: effective_ceilings, build_runner, run_desk, front_desk
Contracts: local-operations-desk-001

Moved from M7 `adapters/frontdesk_cli.py` (SOURCE e38aa722) by named rule R-c26 (S10 unit C6c): `effective_ceilings` (:35-44), `build_runner` (:47-67) and `run` (:70-109, here `run_desk`: the runtime
FileLock, the observer built before the rest of the wiring and the signal handlers) are M7's statements except the builder calls and the import homes of the target: `Fleet(store).registered()` is
`coordination.application.fleet.registry.FleetRegistry(store).registered()` (DESIGN-s5 §F), `FleetRefused` is `coordination.domain.fleet`, `FrontDesk` and `ACTION` are `intake.application.frontdesk`, `DeskRunner`
is `coordination.application.desk_runner`, `LEAD` is `coordination.domain.operation`, `revision` is `intake.domain.frontdesk`, `select_model` is `routing.domain.model_selection`, `BudgetedExecutor` is
`coordination.application.operation`, `build_executor` is `composition.operation`, `build_observer` and `build_collector` are `composition.observation`, `RedisBus` is `composition.cli_bus.bus` and
`Workflow` is `composition.cli.workflow`. `FrontDesk` takes coordination's `Outbox()` (R-f1) as `tests/ported/m7_intake.FrontDesk` wires it, and the `DeskRunner` reads the outbox flusher from its service, so it
is handed the service with `composition.cli_bus.flusher` (`Harness.flusher` of M7). Imports sit inside the functions, so importing this module stays light.
"""

import signal
from contextlib import suppress
from types import SimpleNamespace


def front_desk(service, base_revision: str):
    """M7 `FrontDesk(service, base)` with the outbox port wired (R-f1: coordination's `Outbox()`)."""
    from codex_harness.coordination.application.outbox import Outbox
    from codex_harness.intake.application.frontdesk import FrontDesk
    return FrontDesk(service, base_revision, outbox=Outbox())


def effective_ceilings(store) -> dict:
    """The CURRENT effective fleet budget, including its accounting mode; unregistered fleets keep
    the packaged runtime policy's conservative finite ceiling for this local turn."""
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.domain.fleet import FleetRefused

    try:
        return dict(FleetRegistry(store).registered()["config"]["budget"])
    except FleetRefused:
        return {"per_host": 1, "total": 1}


def build_runner(service, args, observer):
    """Wire the real services around an ALREADY built observer, so the caller can release it even
    when this wiring fails."""
    from codex_harness.composition import cli, cli_bus
    from codex_harness.composition.observation import build_collector
    from codex_harness.composition.queue_waits import ObservedDesk
    from codex_harness.composition.operation import build_executor
    from codex_harness.coordination.application.desk_runner import DeskRunner
    from codex_harness.coordination.application.operation import BudgetedExecutor
    from codex_harness.execution.adapters.call_budget import CallBudget
    from codex_harness.intake.domain.frontdesk import revision
    from codex_harness.routing.domain.model_selection import select_model

    base = revision(args.revision)
    desk = front_desk(service, base)
    # S10 F2-B: the claim is reported through the observer this runner is already built around (composition.queue_waits).
    desk = ObservedDesk(desk, observer)
    # No knowledge adapter: a conversational turn writes no ontology and promotes nothing.
    executor = build_executor(service, observer=observer, knowledge=False)
    # The explicit Codex model label comes from the existing routing, never from the browser.
    model = select_model("design").requested_model
    wrapped = BudgetedExecutor(executor, CallBudget(), effective_ceilings(service.store),
                               "frontdesk", model, labels=lambda kind, agent: ("codex", model))
    runner_service = SimpleNamespace(store=service.store, org=service.org, flusher=cli_bus.flusher(service))
    return DeskRunner(runner_service, desk, wrapped, cli_bus.bus(),
                      cli.workflow(service), observer=observer,
                      # The turns' own observations are drained into the store by this process.
                      collector=build_collector(service.store, observer))


def run_desk(service, args) -> dict:
    from filelock import FileLock, Timeout

    from codex_harness.composition.configuration import runtime_dir
    from codex_harness.composition.observation import build_observer
    from codex_harness.coordination.domain.operation import LEAD
    from codex_harness.intake.application.frontdesk import ACTION

    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(runtime / "frontdesk.lock"), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        return {"status": "refused", "reason_code": "desk_lock_busy", "exit_code": 1}
    observer = None
    installed = []  # (signal, previous handler) for each handler THIS run replaced
    try:
        # The observer exists before the rest of the wiring, so a failure while building the
        # executor, the bus or the budget still releases the spool AND this host lock.
        observer = build_observer(service.store, "cli.desk", role=LEAD)
        runner = build_runner(service, args, observer)
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                # Interrupt shutdown: no new turn is claimed; a claimed turn records its outcome.
                number = getattr(signal, name)
                installed.append((number, signal.signal(number, lambda *_: runner.stop())))
        summary = runner.run(once=bool(args.once))
    finally:
        # The handlers close over this run's runner: every exit, including an exception and a
        # partial installation, hands the process its previous handlers back.
        for number, previous in reversed(installed):
            with suppress(Exception):  # a restore failure never replaces the original outcome
                signal.signal(number, previous)
        if observer is not None:
            with suppress(Exception):  # a close failure never replaces the original outcome
                observer.close()
        lock.release()
    # A graceful interrupt and a normal idle `--once` run are completed commands; a run the store
    # stopped is a failure, and it must not be reported to the shell as a successful desk run.
    return {"desk": ACTION, "revision": args.revision, **summary,
            "exit_code": 1 if summary.get("failure") else 0}
