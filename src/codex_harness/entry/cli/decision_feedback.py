"""The `zeus decision-feedback` argument parser (M7 adapters/decision_feedback_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus decision-feedback`), run (its body: M7 decision_feedback_command) and the private collect, status, report and execute (M7 decision_feedback_cli)
Does not own: dispatch (entry.cli main) and composition (composition.cli_research)
Entry points: add_parser, run
Contracts: INV-DECISION-FEEDBACK-001

Moved from M7 adapters/decision_feedback_cli.py:47-62 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is M7 `cli.py`
`decision_feedback_command` (:616-623) and `_collect` (:21-32), `_status` (:35-37), `_report` (:40-44) and `_execute` (:65-74) are `adapters/decision_feedback_cli.py` (R-c12, S10 unit C7b): the bodies are M7's verbatim
except that the service is built first (as M7 `main()` did), `refusal` is `entry.cli.operation.refusal`, the repository identity is `entry.cli.dge._repository_identity` (M7 `dge_cli.repository_identity`) and the git
source, the registry loader, the evidence reader and the use case are the builders of `composition.cli_research`.
"""


def add_parser(commands) -> None:
    feedback = commands.add_parser("decision-feedback",
                                   help="Join recorded conductor decisions with actual run outcomes and report "
                                        "unverified recurring-work candidates; read-only, no model")
    sub = feedback.add_subparsers(dest="decision_feedback_command", required=True)
    gather = sub.add_parser("collect", help="One bounded collection against a Git-pinned procedure registry")
    gather.add_argument("--registry", required=True, help="Repository-relative registry path (urn:zeus:procedure-registry:1)")
    gather.add_argument("--revision", required=True, help="The 40-hex commit the registry is read from; the working tree is never read")
    gather.add_argument("--limit", type=int, default=100, help="Source runs scanned by this collection (default 100)")
    gather.add_argument("--after", help="Continuation cursor: the last run id of the previous page")
    show = sub.add_parser("status", help="Bounded counts of observations, groups, candidates and conflicts")
    show.add_argument("--limit", type=int, default=100)
    out = sub.add_parser("report", help="Candidate evidence, outcome counts, conflicts and the named limits")
    out.add_argument("--limit", type=int, default=100)
    out.add_argument("--after", help="Continuation cursor: the last candidate id of the previous page")
    out.add_argument("--collection", help="Include one stored collection receipt by id")


def run(args) -> None:
    """INV-DECISION-FEEDBACK-001: exit 0 only for a recorded or read result; refusals print a code and
    a type, never registry content, row bodies, payloads, DSNs or raw exceptions."""
    from codex_harness.composition import build
    from codex_harness.entry.cli.output import emit
    service = build()
    result = _execute(service, args)
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def _collect(service, args) -> dict:
    from codex_harness.composition import cli_research
    from codex_harness.composition.configuration import repository_root
    from codex_harness.entry.cli.dge import _repository_identity
    repository = repository_root()
    loaded = cli_research.load_registry(cli_research.git_source(repository), args.revision, args.registry)
    # The executor's own artifact store, read-only: the artifact behind each decision's execution_ref
    # is what grants evidence credit, and a matching reference string alone never does.
    evidence = cli_research.execution_evidence()
    receipt = cli_research.decision_feedback(service, evidence).collect(
        registry=loaded["registry"], registry_revision=loaded["revision"], registry_path=loaded["path"],
        registry_sha256=loaded["sha256"], repository=_repository_identity(repository),
        limit=args.limit, after=args.after or "")
    return {**receipt, "status": "collected", "exit_code": 0}


def _status(service, args) -> dict:
    from codex_harness.composition import cli_research
    # Store read only.
    return {**cli_research.decision_feedback(service).status(limit=args.limit), "status": "read", "exit_code": 0}


def _report(service, args) -> dict:
    from codex_harness.composition import cli_research
    # Store read only.
    return {**cli_research.decision_feedback(service).report(limit=args.limit, after=args.after or "",
                                                              collection_id=args.collection),
            "status": "read", "exit_code": 0}


def _execute(service, args) -> dict:
    """Fixed-code failure rendering; exit 0 only for a recorded or read result."""
    from codex_harness.entry.cli.operation import refusal
    try:
        if args.decision_feedback_command == "collect":
            return _collect(service, args)
        if args.decision_feedback_command == "status":
            return _status(service, args)
        return _report(service, args)
    except Exception as exc:
        return refusal(exc)
