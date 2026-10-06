"""The `zeus cancel` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus cancel`), run (its store-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:239-241 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:862-864) with `service = build()` first and the imports remapped (S10 unit C2a).
"""


def add_parser(commands) -> None:
    cancel = commands.add_parser("cancel")
    cancel.add_argument("task_id")
    cancel.add_argument("--reason", required=True)


def run(args) -> None:
    from codex_harness.composition import build
    from codex_harness.composition.cli import messages
    from codex_harness.entry.cli.output import emit
    service = build()
    messages(service).cancel(args.task_id, "conductor", args.reason)
    emit({"cancelled": args.task_id})
