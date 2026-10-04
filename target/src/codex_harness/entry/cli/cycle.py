"""The `zeus cycle` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus cycle`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_cycle, composition.cli_bus, composition.observation, composition.operation)
Entry points: add_parser, run
Contracts: INV-LOCAL-CYCLE-001, INV-CYCLE-HANDOFF-001

Moved from M7 cli.py:291-299 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is M7 `cycle_command` (SOURCE cli.py:449-469) with `service = build()` first, `LocalCycle(...)` on `composition.cli_cycle.local_cycle`, `RedisBus(redis_url())` on `composition.cli_bus.bus()`, `Workflow(store, org)` on `composition.cli_cycle.serve_handler` and the imports remapped (S10 unit C5e, R-c22).
"""


def add_parser(commands) -> None:
    cycle = commands.add_parser("cycle", help="Bounded persistent execution loop over one correlation; no conductor")
    cycle_commands = cycle.add_subparsers(dest="cycle_command", required=True)
    for name in ("start", "status", "handoff", "step"):
        sub = cycle_commands.add_parser(name)
        sub.add_argument("cycle_id")
        if name == "start":
            sub.add_argument("--correlation", required=True)
            sub.add_argument("--max-executions", type=int, required=True,
                             help="Executor starts allowed through this cycle; not a billing count")


def run(args) -> None:
    from codex_harness.composition import build, cli_bus, cli_cycle
    from codex_harness.composition.observation import build_observer
    from codex_harness.entry.cli.output import emit
    service = build()
    if args.cycle_command == "start":
        emit(cli_cycle.local_cycle(service).start(args.cycle_id, args.correlation, args.max_executions))
    elif args.cycle_command == "status":
        row = cli_cycle.local_cycle(service).status(args.cycle_id)
        # Presentation only: derived here, never written back to the stored cycle row.
        emit({**row, "remaining_executions": max(0, row["max_executions"] - row["executions"])})
    elif args.cycle_command == "handoff":
        # INV-CYCLE-HANDOFF-001: store read only; no executor, observer, bus or provider is built.
        emit(cli_cycle.local_cycle(service).handoff(args.cycle_id))
    else:
        from codex_harness.composition.operation import build_executor
        observer = build_observer(service.store, "cli.cycle")
        executor = build_executor(service, observer=observer)
        cycle = cli_cycle.local_cycle(service, executor, cli_bus.bus(), cli_cycle.serve_handler(service), observer=observer)
        try:
            emit(cycle.step(args.cycle_id))
        finally:
            observer.close()
