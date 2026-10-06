"""The `zeus improve` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus improve`), run (its executor-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_executor, composition.cli_bus)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:233-236 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:845-855) with `service = build()` first, `build_executor` on `composition.cli_executor.executor` and `RedisBus(redis_url())` on `composition.cli_bus.bus()` (S10 unit C5d, R-c21, R-c8).
"""

from uuid import uuid4


def add_parser(commands) -> None:
    improve = commands.add_parser("improve")
    improve.add_argument("objective")
    improve.add_argument("--acceptance", action="append", required=True)
    improve.add_argument("--importance", choices=["simple", "important"])


def run(args) -> None:
    from codex_harness.composition import build, cli_bus, cli_executor
    from codex_harness.entry.cli.output import emit
    from codex_harness.kernel.message import envelope
    service = build()
    executor = cli_executor.executor(service)
    details = {"objective": args.objective, "acceptance_criteria": args.acceptance}
    if args.importance is not None:
        details["importance"] = args.importance
    message = envelope("task.assign", "conductor", "lead:improvement", "plan", details,
                       "improvement:" + str(uuid4()))
    message["where"]["revision"] = executor.git._git("rev-parse", "HEAD")
    message["how"]["acceptance_criteria"] = args.acceptance
    emit({"message_id": message["message_id"], "correlation_id": message["correlation_id"],
          "stream_id": cli_bus.bus().publish(message)})
