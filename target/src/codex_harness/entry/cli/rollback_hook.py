"""The `zeus rollback-hook` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus rollback-hook`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition.cli, composition.configuration)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:286-288 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:918-920) with `service = build()` first, `service.rollback` on `composition.hook_units(service)` and the imports remapped (S10 unit C2b, R-c5).
"""


def add_parser(commands) -> None:
    rollback = commands.add_parser("rollback-hook")
    rollback.add_argument("hook_id")
    rollback.add_argument("--reason", required=True)


def run(args) -> None:
    from codex_harness.composition import build
    from codex_harness.composition import cli as composition
    from codex_harness.entry.cli.output import emit
    service = build()
    composition.hook_units(service).rollback(args.hook_id, args.reason)
    emit({"rolled_back": args.hook_id})
