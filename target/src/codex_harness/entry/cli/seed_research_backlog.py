"""The `zeus seed-research-backlog` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus seed-research-backlog`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition.cli, composition.configuration)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:200-201 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:751-759) with `service = build()` first, the audits on `composition.research_audits(service, artifacts)` (M7 `ResearchAudits(store, None, FileArtifacts(dir), Workflow(store, org))`) and the imports remapped (S10 unit C2b, R-c5).
"""


def add_parser(commands) -> None:
    seed = commands.add_parser("seed-research-backlog")
    seed.add_argument("--artifacts", required=True)


def run(args) -> None:
    from codex_harness.composition import build
    from codex_harness.composition import cli as composition
    from codex_harness.entry.cli.output import emit
    service = build()
    audits = composition.research_audits(service, composition.artifacts(args.artifacts))
    records = audits.seed_backlog()
    emit([{k: r[k] for k in ("id", "repository", "priority", "status", "activation",
                             "reviewed_paths")} for r in records])
