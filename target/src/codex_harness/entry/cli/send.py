"""The `zeus send` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus send`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli, composition.cli_bus)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:219-220 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:824-827) with `service = build()` first, `RedisBus(redis_url())` on `composition.bus()` and the imports remapped (S10 unit C4, R-c8).
"""


def add_parser(commands) -> None:
    send = commands.add_parser("send")
    send.add_argument("file")


def run(args) -> None:
    import json
    from pathlib import Path

    from codex_harness.composition import build, cli_bus
    from codex_harness.composition import cli as composition
    from codex_harness.entry.cli.output import emit
    service = build()
    message = composition.validate_message(json.loads(Path(args.file).read_text(encoding="utf-8")))
    service.org.authorize(message)
    emit({"stream_id": cli_bus.bus().publish(message)})
