"""The `zeus ticket` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus ticket`)
Does not own: dispatch and composition (S10 unit C2)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:334-381 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

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
