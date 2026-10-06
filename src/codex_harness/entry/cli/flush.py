"""The `zeus flush` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus flush`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_bus, composition.observation)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:218-218 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:820-823) with `service = build()` first, `service.flush_outbox(bus, audit=)` on `composition.flusher(service).flush(bus, audit=)` and the imports remapped (S10 unit C4, R-c8).
"""


def add_parser(commands) -> None:
    commands.add_parser("flush")


def run(args) -> None:
    from codex_harness.composition import build
    from codex_harness.composition import cli_bus as composition
    from codex_harness.composition.observation import build_observer
    from codex_harness.entry.cli.output import emit
    service = build()
    observer = build_observer(service.store, "cli.flush")
    emit(composition.flusher(service).flush(composition.bus(), audit=observer.audit_system))
    observer.close()
