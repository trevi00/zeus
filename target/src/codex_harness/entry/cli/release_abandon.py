"""The `zeus release-abandon` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus release-abandon`), run (its executor-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_executor, composition.cli_bus)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:205-208 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:742-746) with `service = build()` first, `build_executor` on `composition.cli_executor.executor` and `ReleaseRunner(service, executor.git, executor.artifacts, str(codex_auth()))` on `composition.cli_executor.release_runner` (S10 unit C5d, R-c21).
"""


def add_parser(commands) -> None:
    release = commands.add_parser("release-abandon")
    release.add_argument("release_id")
    release.add_argument("--reason", required=True)


def run(args) -> None:
    from codex_harness.composition import build, cli_executor
    from codex_harness.entry.cli.output import emit
    service = build()
    executor = cli_executor.executor(service)
    emit(cli_executor.release_runner(service, executor).abandon(args.release_id, args.reason))
