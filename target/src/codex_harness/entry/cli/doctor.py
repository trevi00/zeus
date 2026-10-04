"""The `zeus doctor` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus doctor`), run (its store-free body, and the online body of `zeus doctor` without `--offline`)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli, composition.cli_bus, composition.configuration)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:202-203 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:636-708), minus its `return`, with the imports remapped (S10 unit C1). Without `--offline`, `run` is the M7 `main()` branch body (SOURCE cli.py:760-765) with `service = build()` first and `RedisBus(redis_url())` on `composition.bus()` (S10 unit C4, R-c8).
"""


def add_parser(commands) -> None:
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--offline", action="store_true", help="Check installation without a database")


def run(args) -> None:
    if not args.offline:
        from codex_harness.composition import build
        from codex_harness.composition import cli_bus as composition
        from codex_harness.entry.cli.output import emit
        service = build()
        with service.store.transaction() as tx:
            hooks = tx.scan("hooks")
        emit({"postgres": True, "redis": composition.bus().client.ping(),
              "organization_valid": True, "hooks": len(hooks),
              "active_hooks": sum(h["status"] == "active" for h in hooks)})
        return
    import shutil

    from codex_harness.composition.cli import resolve_codex
    from codex_harness.composition.configuration import (
        codex_auth,
        repository_root,
        runtime_dir,
    )
    from codex_harness.entry.cli.output import emit
    checks = {name: shutil.which(name) is not None for name in ("git", "uv", "docker")}
    checks.update(codex=resolve_codex() is not None, codex_auth=codex_auth().is_file(),
                  compose=(repository_root() / "compose.yaml").is_file())
    emit({"checks": checks, "repository": str(repository_root()),
          "runtime": str(runtime_dir()), "services_checked": False})
    if not all(checks.values()):
        raise SystemExit(1)
