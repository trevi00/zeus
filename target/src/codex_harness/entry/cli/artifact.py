"""The `zeus artifact` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus artifact`), run (its executor-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_executor, composition.cli_bus)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:245-249 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:870-873) with `service = build()` first and `build_executor` on `composition.cli_executor.executor` (S10 unit C5d, R-c21).
"""


def add_parser(commands) -> None:
    artifact = commands.add_parser("artifact")
    artifact.add_argument("reference")
    artifact.add_argument("--start", type=int, default=0)
    artifact.add_argument("--length", type=int, default=8000)
    artifact.add_argument("--search")


def run(args) -> None:
    from codex_harness.composition import build, cli_executor
    from codex_harness.entry.cli.output import emit
    service = build()
    artifacts = cli_executor.executor(service).artifacts
    emit(artifacts.search(args.reference, args.search) if args.search
         else artifacts.read(args.reference, args.start, args.length))
