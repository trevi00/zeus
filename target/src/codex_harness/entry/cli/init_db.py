"""The `zeus init-db` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus init-db`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:185-185 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:715-717) with `service = build()` first and the imports remapped (S10 unit C2a).
"""


def add_parser(commands) -> None:
    commands.add_parser("init-db")


def run(args) -> None:
    from codex_harness.composition import build
    from codex_harness.entry.cli.output import emit
    service = build()
    receipt = service.store.migrate()
    emit({"migrated": True, "applied": receipt["applied"], "already_applied": receipt["already_applied"], "tool": receipt["tool"]})
