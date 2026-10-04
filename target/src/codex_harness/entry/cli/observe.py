"""The `zeus observe` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus observe`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_bus, composition.observation)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:277-285 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is M7 `observe_command` (SOURCE cli.py:157-172) with `service = build()` first `SpoolDirectory(observation_root())` on `composition.cli_bus.spool()` (an entry module may not import an adapter) and the imports remapped (S10 unit C4).
"""


def add_parser(commands) -> None:
    observe = commands.add_parser("observe", help="Observation logs: collect the spool, report status, reconcile")
    observe_commands = observe.add_subparsers(dest="observe_command", required=True)
    observe_commands.add_parser("collect", help="Move durable spool records into PostgreSQL and acknowledge them")
    observe_commands.add_parser("status", help="Counts, process health, pending terminations, orphans; read-only")
    reconcile = observe_commands.add_parser("reconcile", help="Operator decision for a pending termination record")
    reconcile.add_argument("record_id")
    reconcile.add_argument("--resolution", choices=["rerun", "discard"], required=True)
    reconcile.add_argument("--operator", required=True, help="Audit label, not authenticated identity")
    reconcile.add_argument("--reason", required=True)


def run(args) -> None:
    from codex_harness.composition import build, cli_bus
    from codex_harness.composition.observation import build_collector, build_observer
    from codex_harness.entry.cli.output import emit
    from codex_harness.observation.application.observations import status_report
    service = build()
    if args.observe_command == "collect":
        observer = build_observer(service.store, "cli.observe")
        result = build_collector(service.store, observer).collect()
        observer.close()
        emit(result)
    elif args.observe_command == "status":
        emit(status_report(service.store, cli_bus.spool()))
    else:
        observer = build_observer(service.store, "cli.observe", "operator")
        emit(observer.resolve_termination(args.record_id, resolution=args.resolution, operator=args.operator,
                                          reason=args.reason))
        observer.close()
