"""The `zeus execute-one` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus execute-one`), run (its executor-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_executor, composition.cli_bus)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:237-238 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:856-861) with `service = build()` first, `build_executor` on `composition.cli_executor.executor` and `service.flush_outbox(RedisBus(redis_url()), audit=)` on `composition.cli_bus.flusher(service).flush(bus(), audit=)` (S10 unit C5d, R-c21, R-c8).
"""


def add_parser(commands) -> None:
    execute = commands.add_parser("execute-one")
    execute.add_argument("--agent", required=True)


def run(args) -> None:
    from codex_harness.composition import build, cli_bus, cli_executor
    from codex_harness.composition.observation import build_observer
    from codex_harness.entry.cli.output import emit
    service = build()
    observer = build_observer(service.store, "cli.execute-one", args.agent)
    executor = cli_executor.executor(service, observer=observer)
    emit(executor.execute_one(args.agent) or executor.decide_one(args.agent) or {"status": "idle"})
    cli_bus.flusher(service).flush(cli_bus.bus(), audit=observer.audit_system)
    observer.close()
