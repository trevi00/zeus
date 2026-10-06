"""The `zeus run-command` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus run-command`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition.cli, composition.configuration)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:221-223 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:828-836) with `service = build()` first, `service.prepare_command` on `composition.hook_units(service)`, `run_process` from `composition.cli` and the imports remapped (S10 unit C2b, R-c5).
"""

import argparse


def add_parser(commands) -> None:
    run = commands.add_parser("run-command")
    run.add_argument("--timeout", type=int, default=120)
    run.add_argument("argv", nargs=argparse.REMAINDER)


def run(args) -> None:
    import os

    from codex_harness.composition import build
    from codex_harness.composition import cli as composition
    from codex_harness.entry.cli.output import emit
    from codex_harness.kernel.errors import require
    service = build()
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    require(bool(argv), "Command argv required after --")
    command = composition.hook_units(service).prepare_command(argv, "windows" if os.name == "nt" else "linux")
    result = composition.run_process(command, timeout=args.timeout)
    emit({"argv": command, "exit_code": result.returncode, "stdout": result.stdout,
          "stderr": result.stderr})
    if result.returncode:
        raise SystemExit(result.returncode)
