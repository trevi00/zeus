"""The `zeus desk` root: the argument parser and the command bodies (M7 adapters/frontdesk_cli.py, cli.py desk_command).

Layer: entry
Owns: add_parser (the argument shape of `zeus desk`), run (its body: M7 desk_command) and the private _status, _execute and _desk_refusal (M7 frontdesk_cli)
Does not own: dispatch (entry.cli main) and the desk wiring, ceilings and the lock-and-signal run (composition.cli_desk)
Entry points: add_parser, run
Contracts: local-operations-desk-001

Moved from M7 adapters/frontdesk_cli.py:25-32 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
`run` is M7 `cli.py` `desk_command` (:564-575) and `_status`, `_execute` and `_desk_refusal` are `adapters/frontdesk_cli.py` `status` (:112-114), `execute` (:117-120) and `desk_refusal` (:123-128) (R-c26, S10 unit C6c): the
bodies are M7's verbatim except that the service is built first (as M7 `main()` did), `refusal` is `entry.cli.operation`, `revision` and `DeskRefused` are `intake.domain.frontdesk`, `FrontDesk` is built by
`composition.cli_desk.front_desk` (it wires the outbox port) and the lock-and-signal `run` is `composition.cli_desk.run_desk` (it builds adapters an entry module may not import).
"""


def add_parser(commands) -> None:
    desk = commands.add_parser("desk", help="Local front-door conversation runner; no conductor, no retries")
    sub = desk.add_subparsers(dest="desk_command", required=True)
    run = sub.add_parser("run", help="Own the desk and process queued local requests one at a time")
    run.add_argument("--revision", required=True, help="Full 40-hex base revision every request is answered at")
    run.add_argument("--once", action="store_true", help="Process what is queued now, then exit")
    status = sub.add_parser("status", help="Read desk sessions; store read only")
    status.add_argument("--revision", required=True, help="Full 40-hex base revision of this desk")


def run(args) -> None:
    """local-operations-desk-001: exit 0 only for a completed command; refusals print a code and a
    type, never conversation text, paths, DSNs, raw exceptions or provider output."""
    from codex_harness.composition import build
    from codex_harness.entry.cli.output import emit
    service = build()
    try:
        result = _execute(service, args)
    except Exception as exc:
        emit(_desk_refusal(exc))
        raise SystemExit(1) from exc
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def _status(service, args) -> dict:
    from codex_harness.composition import cli_desk
    from codex_harness.intake.domain.frontdesk import revision
    # Store read only: no executor, observer, bus, budget or provider is built.
    return {**cli_desk.front_desk(service, revision(args.revision)).sessions(), "exit_code": 0}


def _execute(service, args) -> dict:
    from codex_harness.composition import cli_desk
    if args.desk_command == "run":
        return cli_desk.run_desk(service, args)
    return _status(service, args)


def _desk_refusal(exc: Exception) -> dict:
    """What the CLI prints for a failure: a code and a type, never conversation text or raw errors."""
    from codex_harness.entry.cli.operation import refusal
    from codex_harness.intake.domain.frontdesk import DeskRefused
    if isinstance(exc, DeskRefused):
        return {"status": "refused", "reason_code": exc.reason_code, "error_type": type(exc).__name__,
                "exit_code": 1}
    return refusal(exc)
