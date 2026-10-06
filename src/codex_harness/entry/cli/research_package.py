"""The `zeus research-package` argument parser and body (GAP #20; DESIGN-s10 §14 G20-D6).

Layer: entry
Owns: add_parser (the argument shape of `zeus research-package`), run (its body)
Does not own: dispatch (entry.cli main) and composition (composition.cli_research_package)
Entry points: add_parser, run
Contracts: INV-RESEARCH-001, INV-RESEARCH-004 (addendum A1 v2 RF-RT)

A declared target addition (RF-RT has no M7 counterpart; the `cli.parser` compare family declares it as an intended
difference). Exit 0 only for a recorded or read result; a refusal prints a code and a type, never the document.
"""

from pathlib import Path


def add_parser(commands) -> None:
    package = commands.add_parser("research-package", help="Research packages: record, accept, withdraw, exempt, status")
    sub = package.add_subparsers(dest="research_package_command", required=True)
    record = sub.add_parser("record", help="Record one research package document as a draft version")
    record.add_argument("--file", type=Path, required=True)
    accept = sub.add_parser("accept", help="Accept a draft version and release the holds it answers")
    accept.add_argument("key")
    accept.add_argument("version", type=int)
    accept.add_argument("--decision-ref", required=True, help="sha256:<64 hex> of the acceptance decision")
    withdraw = sub.add_parser("withdraw", help="Withdraw a draft or accepted version")
    withdraw.add_argument("key")
    withdraw.add_argument("version", type=int)
    withdraw.add_argument("--reason", required=True)
    status = sub.add_parser("status", help="Versions, current package and exemption of a research key; store read only")
    status.add_argument("key")
    exempt = sub.add_parser("exempt", help="Declare a research key exempt from research-first admission")
    exempt.add_argument("key")
    exempt.add_argument("--class", dest="exemption_class", required=True)
    exempt.add_argument("--reason", required=True)
    unexempt = sub.add_parser("unexempt", help="Withdraw the declared exemption of a research key")
    unexempt.add_argument("key")
    unexempt.add_argument("--reason", required=True)


def run(args) -> None:
    from codex_harness.composition import build
    from codex_harness.entry.cli.output import emit
    service = build()
    result = _execute(service, args)
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def _execute(service, args) -> dict:
    """Fixed-code failure rendering; exit 0 only for a recorded or read result."""
    from codex_harness.entry.cli.operation import refusal
    try:
        return {**_command(service, args), "exit_code": 0}
    except Exception as exc:
        return refusal(exc)


def _command(service, args) -> dict:
    from codex_harness.composition import cli_research_package as composed
    from codex_harness.entry.cli.operation import read_document
    command = args.research_package_command
    if command == "status":
        return composed.status(service, args.key)
    if command == "accept":
        return composed.accept_and_resolve(service, args.key, args.version, args.decision_ref)
    owner = composed.packages(service)
    with service.store.transaction() as tx:
        if command == "record":
            row = owner.record(tx, read_document(args.file, "Research package file"))
        elif command == "withdraw":
            row = owner.withdraw(tx, args.key, args.version, args.reason)
        elif command == "exempt":
            row = owner.exempt(tx, args.key, args.exemption_class, args.reason, composed.OPERATOR)
            return {"key": row["key"], "class": row["class"], "active": row["active"]}
        else:
            row = owner.unexempt(tx, args.key, args.reason, composed.OPERATOR)
            return {"key": row["key"], "class": row["class"], "active": row["active"]}
    return {"key": row["key"], "version": row["version"], "status": row["status"]}
