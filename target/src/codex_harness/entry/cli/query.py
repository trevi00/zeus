"""The `zeus query` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus query`), run (its knowledge-backed body)
Does not own: dispatch (entry.cli main) and composition (composition.cli_knowledge)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:252-254 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:876-883) with the imports remapped and the constructions replaced by `composition.cli_knowledge` builders (S10 unit C3).
"""


def add_parser(commands) -> None:
    q = commands.add_parser("query")
    q.add_argument("text")
    q.add_argument("--semantic", action="store_true")


def run(args) -> None:
    from codex_harness.composition import cli_knowledge
    from codex_harness.entry.cli.output import emit
    knowledge = cli_knowledge.knowledge()
    if args.semantic:
        emit(knowledge.hybrid_query(args.text, cli_knowledge.embeddings()))
    else:
        emit(knowledge.query(args.text))
