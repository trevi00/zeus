"""The `zeus release-retry` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus release-retry`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:205-208 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:748-750) with `service = build()` first and the imports remapped (S10 unit C2a).
"""


def add_parser(commands) -> None:
    release = commands.add_parser("release-retry")
    release.add_argument("release_id")
    release.add_argument("--reason", required=True)


def run(args) -> None:
    from codex_harness.composition import build
    from codex_harness.composition.cli import release_queue
    from codex_harness.entry.cli.output import emit
    service = build()
    emit(release_queue(service).retry(args.release_id, args.reason))
