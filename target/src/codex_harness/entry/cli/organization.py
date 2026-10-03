"""The `zeus organization` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus organization`), run (its store-free body)
Does not own: dispatch (entry.cli main) and composition (composition.cli, composition.configuration)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:211-211 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:636-708), minus its `return`, with the imports remapped (S10 unit C1).
"""


def add_parser(commands) -> None:
    commands.add_parser("organization")


def run(args) -> None:
    from dataclasses import asdict

    from codex_harness.composition.cli import organization
    from codex_harness.entry.cli import emit
    emit({"agents": [asdict(a) for a in organization().agents.values()]})
