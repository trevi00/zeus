"""CLI composition; offline review does not start any service."""
from pathlib import Path

from codex_harness.adapters.sdd import (
    device_probe,
    load_json,
    read_spec,
    render_review,
    replay_source,
    write_export,
)
from codex_harness.domain.model import digest
from codex_harness.domain.sdd import gate_report


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


def execute(args):
    command = args.sdd_command
    if command == "device-check":
        return device_probe()
    if command in {"inspect", "view", "export-replay", "register"}:
        spec, source = read_spec(args.file, args.git_revision)
        if command == "inspect":
            return {"valid": True, "source": source, "report": gate_report(spec)}
        if command in {"view", "export-replay"}:
            body = render_review(spec) if command == "view" else replay_source(spec)
            kind = "review" if command == "view" else "replay"
            return {**write_export(args.output, body, kind), "spec_hash": digest(spec), "acceptance_passed": False,
                    "status": "review_only" if command == "view" else "unexecuted_replay"}
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.configuration import runtime_dir
    from codex_harness.application.sdd import SDD
    from codex_harness.bootstrap import build
    service = SDD(build().store, FileArtifacts(runtime_dir() / "artifacts"))
    if command == "register":
        return service.register(spec, args.ticket, args.ticket_revision, source)
    if command == "status":
        return service.status(args.iteration_id)
    if command == "view-iteration":
        status = service.status(args.iteration_id)
        report = {**status["report"], "iteration_status": status["status"],
                  "notifications": status["notifications"], "events": status["events"]}
        return write_export(args.output, render_review(status["spec"], report))
    if command == "import-log":
        return service.observe(args.iteration_id, load_json(args.environment), load_json(args.events), args.source)
    if command == "propose":
        return service.propose(args.iteration_id, args.observation)
    if command == "advance":
        return service.request_advance(args.iteration_id, args.sequence)
    return service.record_transfer(args.iteration_id, load_json(args.file))
