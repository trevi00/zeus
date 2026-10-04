"""The `zeus ticket` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus ticket`), run (its body: M7 ticket_command) and _lifecycle_command (M7 ticket_cli.execute)
Does not own: dispatch (entry.cli main) and composition (composition.cli_tickets)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:334-381 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is M7 `ticket_command` (SOURCE cli.py:411-446) and `_lifecycle_command` is `adapters/ticket_cli.py:22-61` (`execute`) verbatim; object constructions are the builders of `composition.cli_tickets` (S10 unit C2c). `ticket dispatch` needs the executor's git HEAD and is composed in S10 unit C5 (R-c9): it refuses until then.
"""

import json
from pathlib import Path


def add_parser(commands) -> None:
    ticket = commands.add_parser("ticket", help="Versioned review topics and explicit GitHub issue sync")
    ticket_commands = ticket.add_subparsers(dest="ticket_command", required=True)
    ticket_commands.add_parser("list")
    create = ticket_commands.add_parser("create")
    create.add_argument("--file", type=Path, required=True)
    create.add_argument("--author", default="operator")
    for name in ("show", "export", "update", "review", "dispatch", "sync", "pull", "evidence", "prepare-close", "close", "reopen", "review-close"):
        sub = ticket_commands.add_parser(name)
        sub.add_argument("ticket_id")
        if name == "show":
            sub.add_argument("--revision", type=int)
        if name in {"update", "review", "dispatch"}:
            sub.add_argument("--revision", type=int, required=True)
        if name == "dispatch":
            sub.add_argument("--goal-manifest", type=Path, help="Goal manifest JSON; requires --criterion")
            sub.add_argument("--criterion", help="Criterion id in the goal manifest; requires --goal-manifest")
        if name == "update":
            sub.add_argument("--file", type=Path, required=True)
            sub.add_argument("--reason", required=True)
            sub.add_argument("--author", default="operator")
        if name == "review":
            sub.add_argument("--reviewer", required=True)
            sub.add_argument("--provider", required=True)
            sub.add_argument("--verdict", choices=["support", "changes_requested", "question"], required=True)
            sub.add_argument("--summary", required=True)
            sub.add_argument("--evidence", action="append", required=True)
        if name in {"sync", "pull"}:
            sub.add_argument("--repo", required=True, help="GitHub owner/repository")
        if name == "sync":
            sub.add_argument("--preview", action="store_true", help="Print projection; no network or state changes")
            sub.add_argument("--reconcile-observation", help="Explicitly replace the observed title/body with the local projection")
            sub.add_argument("--revision", type=int, help="Required current revision when reconciling")
        if name in {"evidence", "prepare-close"}:
            sub.add_argument("--file", type=Path, required=True)
        if name == "prepare-close":
            sub.add_argument("--output", type=Path, required=True, help="New canonical packet file for external signing")
        if name == "close":
            sub.add_argument("--packet", type=Path, required=True)
            sub.add_argument("--signature", action="append", required=True, help="PRINCIPAL=SIGNATURE_FILE; repeat per signer")
        if name == "review-close":
            sub.add_argument("--packet", type=Path, required=True)
            sub.add_argument("--output", type=Path, required=True, help="Read-only HTML review; never grants approval")
        if name == "reopen":
            sub.add_argument("--revision", type=int, required=True)
            sub.add_argument("--sequence", type=int, required=True)
            sub.add_argument("--reason", required=True)
            sub.add_argument("--expected-state", choices=["closed", "open", "dispatched"], default="closed",
                             help="Use open/dispatched explicitly to reconcile a new external close")


def run(args) -> None:
    from codex_harness.composition import build, cli_tickets
    from codex_harness.entry.cli.output import emit
    from codex_harness.intake.application.tickets import render_ticket
    tickets = cli_tickets.tickets(build())
    command = args.ticket_command
    if command == "list":
        emit(tickets.list())
    elif command == "create":
        emit(tickets.create(json.loads(args.file.read_text("utf-8")), args.author))
    elif command == "update":
        emit(tickets.update(args.ticket_id, args.revision, json.loads(args.file.read_text("utf-8")),
                            args.reason, args.author))
    elif command == "review":
        emit(tickets.review(args.ticket_id, args.revision, args.reviewer, args.provider,
                            args.verdict, args.summary, args.evidence))
    elif command == "show":
        emit(tickets.get(args.ticket_id, args.revision))
    elif command == "export" or (command == "sync" and args.preview):
        print(render_ticket(tickets.get(args.ticket_id)), end="")
    elif command == "dispatch":
        raise RuntimeError("zeus ticket dispatch is composed in S10 unit C5")  # R-c9
    elif command in {"evidence", "prepare-close", "close", "reopen", "review-close"}:
        emit(_lifecycle_command(tickets, args))
    else:
        lifecycle = cli_tickets.ticket_lifecycle(tickets)
        github = cli_tickets.github_tickets(tickets, lifecycle)
        if command == "sync":
            emit(github.sync(args.ticket_id, args.repo,
                            reconcile_observation=args.reconcile_observation, expected_revision=args.revision))
        else:
            emit(github.pull(args.ticket_id, args.repo))


def _lifecycle_command(tickets, args):
    from codex_harness.composition import cli_tickets
    from codex_harness.kernel.errors import require
    from codex_harness.kernel.ids import canonical
    life = cli_tickets.ticket_lifecycle(tickets)
    if args.ticket_command == "evidence":
        document, ticket = cli_tickets.load_json(args.file), tickets.get(args.ticket_id)
        require(isinstance(document, dict) and document.get("ticket_id") == ticket["id"]
                and document.get("revision") == ticket["revision"] and document.get("content_hash") == ticket["content_hash"],
                "Evidence must identify the current ticket revision")
        result = life.artifacts.put(canonical(document), "operator-imported-ticket-evidence")
        return {**result, "authority": "unverified_observation_only"}
    if args.ticket_command == "prepare-close":
        prepared = life.prepare(args.ticket_id, cli_tickets.load_json(args.file))
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(prepared["signing_payload"].encode("utf-8"))
        return {k: v for k, v in prepared.items() if k != "signing_payload"} | {"signing_file": str(output)}
    if args.ticket_command in {"close", "review-close"}:
        with args.packet.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        require(len(raw) <= 1024 * 1024, "Closure packet exceeds budget")
        packet = cli_tickets.parse_json(raw.decode("utf-8"))
        require(isinstance(packet, dict) and packet.get("ticket_id") == args.ticket_id
                and raw == canonical(packet).encode("utf-8"), "Ticket identity or canonical signing bytes mismatch")
        if args.ticket_command == "review-close":
            require(not args.output.resolve().is_relative_to(life.artifacts.root), "Review output must be outside artifact storage")
            review = life.review(packet)
            return {**cli_tickets.write_export(args.output, cli_tickets.render_ticket_review(review, str(args.packet.resolve()))),
                    "packet_ref": review["packet_ref"], "approval_granted": False}
        ref = life.artifacts.put(raw.decode("utf-8"), "externally-signed-ticket-packet")["ref"]
        signatures = []
        for value in args.signature:
            principal, separator, path = value.partition("=")
            require(separator and principal and path, "Use --signature PRINCIPAL=SIGNATURE_FILE")
            with Path(path).open("rb") as stream:
                body = stream.read(16385)
            require(len(body) <= 16384, "Signature exceeds budget")
            signatures.append({"principal": principal,
                "signature_ref": life.artifacts.put(body.decode("utf-8"), "external-ticket-signature")["ref"]})
        return life.close(ref, signatures)
    return life.reopen(args.ticket_id, args.revision, args.sequence, args.reason, args.expected_state)
