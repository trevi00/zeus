"""The `zeus cleanup` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus cleanup`), run (its executor-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_executor, composition.cli_bus)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:209-210 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:779-783) with `service = build()` first, `build_executor` on `composition.cli_executor.executor` and `ArtifactMaintenance` on `composition.cli_executor.artifact_maintenance` (S10 unit C5d, R-c21).
"""


def add_parser(commands) -> None:
    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("--apply", action="store_true")


def run(args) -> None:
    from codex_harness.composition import build, cli_executor
    from codex_harness.entry.cli.output import emit
    service = build()
    executor = cli_executor.executor(service)
    emit(cli_executor.artifact_maintenance(service, executor.artifacts).collect(apply=args.apply))
