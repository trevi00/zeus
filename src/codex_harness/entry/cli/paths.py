"""The `zeus paths` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus paths`), run (its store-free body)
Does not own: dispatch (entry.cli main) and composition (composition.cli, composition.configuration)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:183-183 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:636-708), minus its `return`, with the imports remapped (S10 unit C1).
"""


def add_parser(commands) -> None:
    commands.add_parser("paths", help="Resolved local paths and persistent namespace; no service access")


def run(args) -> None:
    from codex_harness.composition.configuration import repository_root, runtime_dir, settings
    from codex_harness.entry.cli.output import emit
    config = settings()
    emit({"repository": str(repository_root()), "runtime": str(runtime_dir()),
          "compose_project": config.get("COMPOSE_PROJECT_NAME", "codex-harness"),
          "redis_namespace": config.get("HARNESS_REDIS_NAMESPACE", "codex-harness")})
