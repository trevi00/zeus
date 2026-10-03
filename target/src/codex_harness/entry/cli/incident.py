"""The `zeus incident` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus incident`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition.cli, composition.configuration)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:216-217 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:818-819) with `service = build()` first, `service.record_incident` on `composition.incidents(service)` and the imports remapped (S10 unit C2b, R-c5).
"""


def add_parser(commands) -> None:
    i = commands.add_parser("incident")
    i.add_argument("file")


def run(args) -> None:
    import json
    from pathlib import Path

    from codex_harness.composition import build
    from codex_harness.composition import cli as composition
    from codex_harness.entry.cli.output import emit
    service = build()
    emit(composition.incidents(service).record_incident(
        composition.validate_message(json.loads(Path(args.file).read_text(encoding="utf-8")))))
