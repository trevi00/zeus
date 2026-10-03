"""The `zeus index` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus index`), run (its knowledge-backed body)
Does not own: dispatch (entry.cli main) and composition (composition.cli_knowledge)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:250-251 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:874-875) with the imports remapped and the constructions replaced by `composition.cli_knowledge` builders (S10 unit C3).
"""


def add_parser(commands) -> None:
    index = commands.add_parser("index")
    index.add_argument("root", nargs="?", default=".")


def run(args) -> None:
    from codex_harness.composition.cli_knowledge import knowledge
    from codex_harness.entry.cli.output import emit
    emit(knowledge().index_python(args.root))
