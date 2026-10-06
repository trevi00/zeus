"""The `zeus sdd` argument parser (M7 adapters/sdd_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus sdd`) and run (its body: M7 sdd_cli.execute and the emit of its result)
Does not own: dispatch (entry.cli main) and composition (composition.cli_tickets)
Entry points: add_parser, run
Contracts: none

Moved from M7 adapters/sdd_cli.py:16-43 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is `adapters/sdd_cli.py:44-79` (`execute`) with the `emit(execute(args))` of M7 `main` (cli.py:644-647); `service = SDD(build().store, ...)` is `cli_tickets.sdd(build())` (S10 unit C2c).
"""

from pathlib import Path


def add_parser(commands):
    parser = commands.add_parser("sdd", help="Strict specs, observation proposals and eight-stage preparation reports")
    sub = parser.add_subparsers(dest="sdd_command", required=True)
    sub.add_parser("device-check", help="Discover connected devices; never certify acceptance")
    for name in ("inspect", "view", "export-replay", "register"):
        p = sub.add_parser(name)
        p.add_argument("file", type=Path)
        p.add_argument("--git-revision")
        if name in {"view", "export-replay"}:
            p.add_argument("--output", type=Path, required=True)
        if name == "register":
            p.add_argument("--ticket", required=True)
            p.add_argument("--ticket-revision", type=int, required=True)
    for name in ("status", "view-iteration", "import-log", "propose", "advance", "transfer-record"):
        p = sub.add_parser(name)
        p.add_argument("iteration_id")
        if name == "view-iteration":
            p.add_argument("--output", type=Path, required=True)
        if name == "import-log":
            p.add_argument("--environment", type=Path, required=True)
            p.add_argument("--events", type=Path, required=True)
            p.add_argument("--source", required=True)
        if name == "propose":
            p.add_argument("--observation", required=True)
        if name == "advance":
            p.add_argument("--sequence", type=int, required=True)
        if name == "transfer-record":
            p.add_argument("--file", type=Path, required=True)


def run(args) -> None:
    from codex_harness.entry.cli.output import emit
    emit(_execute(args))


def _execute(args):
    from codex_harness.composition import cli_tickets
    from codex_harness.kernel.ids import digest
    from codex_harness.review.domain.sdd import gate_report
    command = args.sdd_command
    if command == "device-check":
        return cli_tickets.device_probe()
    if command in {"inspect", "view", "export-replay", "register"}:
        spec, source = cli_tickets.read_spec(args.file, args.git_revision)
        if command == "inspect":
            return {"valid": True, "source": source, "report": gate_report(spec)}
        if command in {"view", "export-replay"}:
            body = cli_tickets.render_review(spec) if command == "view" else cli_tickets.replay_source(spec)
            kind = "review" if command == "view" else "replay"
            return {**cli_tickets.write_export(args.output, body, kind), "spec_hash": digest(spec), "acceptance_passed": False,
                    "status": "review_only" if command == "view" else "unexecuted_replay"}
    from codex_harness.composition import build
    service = cli_tickets.sdd(build())
    if command == "register":
        return service.register(spec, args.ticket, args.ticket_revision, source)
    if command == "status":
        return service.status(args.iteration_id)
    if command == "view-iteration":
        status = service.status(args.iteration_id)
        report = {**status["report"], "iteration_status": status["status"],
                  "notifications": status["notifications"], "events": status["events"]}
        return cli_tickets.write_export(args.output, cli_tickets.render_review(status["spec"], report))
    if command == "import-log":
        return service.observe(args.iteration_id, cli_tickets.load_json(args.environment), cli_tickets.load_json(args.events), args.source)
    if command == "propose":
        return service.propose(args.iteration_id, args.observation)
    if command == "advance":
        return service.request_advance(args.iteration_id, args.sequence)
    return service.record_transfer(args.iteration_id, cli_tickets.load_json(args.file))
