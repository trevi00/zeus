"""The `zeus context` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus context`), run (its knowledge-backed body)
Does not own: dispatch (entry.cli main) and composition (composition.cli_knowledge)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:262-265 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:905-914) with the imports remapped and the constructions replaced by `composition.cli_knowledge` builders (S10 unit C3).
"""


def add_parser(commands) -> None:
    context = commands.add_parser("context")
    context.add_argument("query")
    context.add_argument("--agent", default="worker:implementation")
    context.add_argument("--budget", type=int, default=12000)


def run(args) -> None:
    from dataclasses import asdict

    from codex_harness.composition import build
    from codex_harness.composition.cli_knowledge import knowledge
    from codex_harness.context.domain.packet import ContextItem, compile_context
    from codex_harness.entry.cli.output import emit
    from codex_harness.kernel.ids import digest
    service = build()
    actor = service.org.actor(args.agent)
    hits = knowledge().query(args.query)
    items = [ContextItem(h["id"], h["body"], h["source_ref"], h["revision"]) for h in hits]
    snapshot = digest(sorted({h["properties"].get("snapshot", h["revision"]) for h in hits}))
    packet = compile_context(actor.id, "query:" + args.query, snapshot,
                             {"role": actor.role, "objective": args.query,
                              "acceptance_criteria": ["Return grounded evidence"],
                              "policy": "bootstrap-v1"}, items, args.budget, 2000)
    emit(asdict(packet))
