"""The `zeus project-graph` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus project-graph`), run (its knowledge-backed body)
Does not own: dispatch (entry.cli main) and composition (composition.cli_knowledge)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:257-257 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:888-889) with the imports remapped and the constructions replaced by `composition.cli_knowledge` builders (S10 unit C3).
"""


def add_parser(commands) -> None:
    commands.add_parser("project-graph")


def run(args) -> None:
    from codex_harness.composition import build
    from codex_harness.composition.cli_knowledge import knowledge
    from codex_harness.entry.cli.output import emit
    service = build()
    emit(knowledge().project_runtime(service.store, service.org))
