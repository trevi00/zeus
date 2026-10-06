"""The `zeus dlq` argument parser and body (S10 A5-1b, DESIGN-s10 §17a).

Layer: entry
Owns: add_parser (the argument shape of `zeus dlq`), run (its body)
Does not own: dispatch (entry.cli main) and composition (composition.cli_dlq)
Entry points: add_parser, run
Contracts: INV-MESSAGE-001

A declared target addition (no M7 counterpart; the `cli.parser` compare family declares it as an intended difference).
A refusal raises its code (`ContractError`), which `main` maps to exit 1; a message body is never printed.
"""


def add_parser(commands) -> None:
    dlq = commands.add_parser("dlq", help="Dead letters: list them, replay one entry exactly once")
    sub = dlq.add_subparsers(dest="dlq_command", required=True)
    sub.add_parser("list", help="The dead-letter entries grouped by source and entry id (no message body)")
    trim = sub.add_parser("trim", help="Delete the stream entries of replays completed longer than the retention ago")
    trim.add_argument("--retention-seconds", type=int, default=None,
                      help="the minimum age of a completed replay (default: the observation retention)")
    replay = sub.add_parser("replay", help="Publish one dead-lettered message again, once, with an audit record")
    replay.add_argument("--source", required=True, help="the full source stream name")
    replay.add_argument("--entry-id", required=True, help="the stream entry id of the failed delivery")
    replay.add_argument("--reason", required=True)
    replay.add_argument("--actor", required=True)


def run(args) -> None:
    from codex_harness.composition import cli_dlq
    from codex_harness.entry.cli.output import emit
    dead_letters = cli_dlq.dead_letters()
    if args.dlq_command == "list":
        emit(dead_letters.list())
    elif args.dlq_command == "trim":
        emit(dead_letters.trim() if args.retention_seconds is None
             else dead_letters.trim(retention_seconds=args.retention_seconds))
    else:
        emit(dead_letters.replay(args.source, args.entry_id, reason=args.reason, actor=args.actor))
