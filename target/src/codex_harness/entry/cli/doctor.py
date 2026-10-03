"""The `zeus doctor` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus doctor`), run (its store-free body)
Does not own: dispatch (entry.cli main) and composition (composition.cli, composition.configuration)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:202-203 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:636-708), minus its `return`, with the imports remapped (S10 unit C1).
"""


def add_parser(commands) -> None:
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--offline", action="store_true", help="Check installation without a database")


def run(args) -> None:
    if not args.offline:
        raise RuntimeError("zeus doctor without --offline is composed in S10 unit C2")
    import shutil

    from codex_harness.composition.cli import resolve_codex
    from codex_harness.composition.configuration import (
        codex_auth,
        repository_root,
        runtime_dir,
    )
    from codex_harness.entry.cli import emit
    checks = {name: shutil.which(name) is not None for name in ("git", "uv", "docker")}
    checks.update(codex=resolve_codex() is not None, codex_auth=codex_auth().is_file(),
                  compose=(repository_root() / "compose.yaml").is_file())
    emit({"checks": checks, "repository": str(repository_root()),
          "runtime": str(runtime_dir()), "services_checked": False})
    if not all(checks.values()):
        raise SystemExit(1)
