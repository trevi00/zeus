"""The `zeus rebase` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus rebase`), run (its executor-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_executor, composition.cli_bus)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:242-244 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:865-869) with `service = build()` first, `build_executor` on `composition.cli_executor.executor`, `executor.workflow.request_rebase` on `composition.cli.messages(service).request_rebase` and `service.flush_outbox(RedisBus(redis_url()))` on `composition.cli_bus.flusher(service).flush(bus())` (S10 unit C5d, R-c21, R-c8).
"""


def add_parser(commands) -> None:
    rebase = commands.add_parser("rebase")
    rebase.add_argument("task_id")
    rebase.add_argument("--onto", default="HEAD")


def run(args) -> None:
    from codex_harness.composition import build, cli_bus, cli_executor
    from codex_harness.composition import cli as composition
    from codex_harness.entry.cli.output import emit
    service = build()
    executor = cli_executor.executor(service)
    revision = executor.git._git("rev-parse", "--verify", args.onto + "^{commit}")
    # M7's `Workflow.request_rebase` is the target `MessageHandler.request_rebase` (S5, composition.cli.messages, C2a).
    emit(composition.messages(service).request_rebase(args.task_id, revision))
    cli_bus.flusher(service).flush(cli_bus.bus())
