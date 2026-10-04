"""The `zeus research` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus research`), run (its executor-backed body)
Does not own: dispatch (entry.cli main) and composition (composition, composition.cli_executor, composition.cli_bus)
Entry points: add_parser, run
Contracts: INV-DISCOVERY-PRESSURE-001

Moved from M7 cli.py:228-232 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is the M7 `main()` branch body (SOURCE cli.py:839-844) with `service = build()` first, `build_executor` on `composition.cli_executor.executor` and `RedisBus(redis_url())` on `composition.cli_bus.bus()` (S10 unit C5d, R-c21, R-c8).
"""

from uuid import uuid4


def add_parser(commands) -> None:
    research = commands.add_parser("research")
    research.add_argument("source", choices=["github", "geeknews"])
    # INV-DISCOVERY-PRESSURE-001: why this fetch happens; carried in the task and checked before any fetch.
    research.add_argument("--intent", required=True,
                          choices=["proactive", "user_request", "incident", "existing_work_result", "task_required"])


def run(args) -> None:
    from codex_harness.composition import build, cli_bus, cli_executor
    from codex_harness.entry.cli.output import emit
    from codex_harness.kernel.message import envelope
    service = build()
    executor = cli_executor.executor(service)
    message = envelope("task.assign", "lead:research", "worker:" + args.source, "research",
                       {"source": args.source, "intent": args.intent}, "research:" + str(uuid4()))
    message["where"]["revision"] = executor.git._git("rev-parse", "HEAD")
    emit({"message": message, "stream_id": cli_bus.bus().publish(message)})
