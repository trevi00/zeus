"""File/CLI boundary for externally signed ticket acceptance."""
from pathlib import Path

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.configuration import repository_root, runtime_dir
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.sdd import load_json, parse_json
from codex_harness.adapters.ticket_authority import TicketAuthority
from codex_harness.application.ticket_lifecycle import TicketLifecycle
from codex_harness.domain.model import canonical, require


def build_lifecycle(tickets):
    runtime = runtime_dir()
    artifacts = FileArtifacts(runtime / "artifacts")
    git = GitWorkspace(str(repository_root()), str(runtime / "workspaces"))
    return TicketLifecycle(tickets, artifacts, TicketAuthority(git, artifacts))


def execute(tickets, args):
    life = build_lifecycle(tickets)
    if args.ticket_command == "evidence":
        document, ticket = load_json(args.file), tickets.get(args.ticket_id)
        require(isinstance(document, dict) and document.get("ticket_id") == ticket["id"]
                and document.get("revision") == ticket["revision"] and document.get("content_hash") == ticket["content_hash"],
                "Evidence must identify the current ticket revision")
        result = life.artifacts.put(canonical(document), "operator-imported-ticket-evidence")
        return {**result, "authority": "unverified_observation_only"}
    if args.ticket_command == "prepare-close":
        prepared = life.prepare(args.ticket_id, load_json(args.file))
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(prepared["signing_payload"].encode("utf-8"))
        return {k: v for k, v in prepared.items() if k != "signing_payload"} | {"signing_file": str(output)}
    if args.ticket_command in {"close", "review-close"}:
        with args.packet.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        require(len(raw) <= 1024 * 1024, "Closure packet exceeds budget")
        packet = parse_json(raw.decode("utf-8"))
        require(isinstance(packet, dict) and packet.get("ticket_id") == args.ticket_id
                and raw == canonical(packet).encode("utf-8"), "Ticket identity or canonical signing bytes mismatch")
        if args.ticket_command == "review-close":
            from codex_harness.adapters.sdd import write_export
            from codex_harness.adapters.ticket_review import render_ticket_review
            require(not args.output.resolve().is_relative_to(life.artifacts.root), "Review output must be outside artifact storage")
            review = life.review(packet)
            return {**write_export(args.output, render_ticket_review(review, str(args.packet.resolve()))),
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
