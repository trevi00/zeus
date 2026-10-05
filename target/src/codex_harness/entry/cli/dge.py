"""The `zeus dge` argument parser (M7 adapters/dge_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus dge`), run (its body: M7 dge_command) and the private register, submit, status, execute and repository_identity (M7 dge_cli)
Does not own: dispatch (entry.cli main) and composition (composition.cli_research)
Entry points: add_parser, run
Contracts: INV-DGE-001

Moved from M7 adapters/dge_cli.py:69-78 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is M7 `cli.py` `dge_command` (:486-493) and
`_repository_identity` (:25-28), `_register` (:48-55), `_submit` (:58-61), `_status` (:64-66) and `_execute` (:81-90) are `adapters/dge_cli.py` (R-c12, S10 unit C7b): the bodies are M7's
verbatim except that the service is built first (as M7 `main()` did), `read_document` and `refusal` are `entry.cli.operation`, the repository is `composition.configuration.repository_root` and the git source and the
use case are the builders of `composition.cli_research`.
"""

from pathlib import Path


def add_parser(commands) -> None:
    dge = commands.add_parser("dge", help="Research-bound design control: register packet, submit debate event, status")
    sub = dge.add_subparsers(dest="dge_command", required=True)
    reg = sub.add_parser("register", help="Verify pinned sources through git and register the packet (urn:zeus:research-packet:1)")
    reg.add_argument("--file", type=Path, required=True)
    put = sub.add_parser("submit", help="Record one operator-submitted debate event (urn:zeus:debate-event:1)")
    put.add_argument("session_id")
    put.add_argument("--file", type=Path, required=True)
    show = sub.add_parser("status", help="Safe session summary; store read only")
    show.add_argument("session_id")


def run(args) -> None:
    """INV-DGE-001: exit 0 only for a recorded, replayed or read result; refusals print a code and a
    type, never packet text, payloads, DSNs or raw exceptions."""
    from codex_harness.composition import build
    from codex_harness.entry.cli.output import emit
    service = build()
    result = _execute(service, args)
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def _repository_identity(repository) -> str:
    """The same resolved-repository digest `operate` records in its identity, so the claim-time
    gate compares like with like; the path itself is never stored."""
    from codex_harness.kernel.ids import digest
    return digest(str(Path(repository).resolve()))


def _register(service, args) -> dict:
    from codex_harness.composition import cli_research
    from codex_harness.composition.configuration import repository_root
    from codex_harness.entry.cli.operation import read_document
    from codex_harness.research.application.dge import DebateSessions
    from codex_harness.research.domain.dge import validate_packet
    packet = validate_packet(read_document(args.file, "Research packet"))
    repository = repository_root()
    bound = cli_research.verify_sources(packet, cli_research.git_source(repository))
    result = cli_research.debate_sessions(service).register(packet, _repository_identity(repository), bound)
    return {"status": "registered", "cached": result["cached"], "exit_code": 0,
            "session": DebateSessions._safe(result["session"])}


def _submit(service, args) -> dict:
    from codex_harness.composition import cli_research
    from codex_harness.entry.cli.operation import read_document
    event = read_document(args.file, "Debate event")
    result = cli_research.debate_sessions(service).submit(args.session_id, event)
    return {**result, "exit_code": 0}


def _status(service, args) -> dict:
    from codex_harness.composition import cli_research
    # Store read only: no executor, observer, bus, budget or provider is built.
    return {**cli_research.debate_sessions(service).status(args.session_id), "exit_code": 0}


def _execute(service, args) -> dict:
    """Fixed-code failure rendering; exit 0 only for a recorded, replayed or read result."""
    from codex_harness.entry.cli.operation import refusal
    try:
        if args.dge_command == "register":
            return _register(service, args)
        if args.dge_command == "submit":
            return _submit(service, args)
        return _status(service, args)
    except Exception as exc:
        return refusal(exc)
