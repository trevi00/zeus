"""The `zeus validate` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus validate`), run (its store-free body)
Does not own: dispatch (entry.cli main) and composition (composition.cli, composition.configuration)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:212-213 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:636-708), minus its `return`, with the imports remapped (S10 unit C1).
"""


def add_parser(commands) -> None:
    v = commands.add_parser("validate")
    v.add_argument("file")


def run(args) -> None:
    import json
    from pathlib import Path

    from codex_harness.composition.cli import organization, validate_message
    from codex_harness.entry.cli import emit
    message = validate_message(json.loads(Path(args.file).read_text(encoding="utf-8")))
    organization().authorize(message)
    emit({"valid": True, "message_id": message["message_id"]})
