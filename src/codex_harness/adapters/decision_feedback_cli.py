"""`zeus decision-feedback collect|status|report`: thin wiring around DecisionFeedback
(INV-DECISION-FEEDBACK-001).

`collect` reads the Git-pinned registry through git argv, the execution artifacts of the decisions it
joins through the same read-only content-addressed store the executor wrote them to, and then touches
PostgreSQL only. No executor, bus, budget, observer, provider, knowledge adapter or network client is
built by any of these commands, and none of them writes a task, an incident, a hook, a release or a
graph node. The repository identity comes from the trusted CLI settings, the same digest `operate`
records.
"""
from __future__ import annotations

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.autonomous_evidence import ExecutionEvidence
from codex_harness.adapters.decision_feedback import load_registry
from codex_harness.adapters.dge_cli import repository_identity
from codex_harness.adapters.operation_cli import GitSource, refusal
from codex_harness.application.decision_feedback import DecisionFeedback


def collect(service, args) -> dict:
    from codex_harness.adapters.configuration import repository_root, runtime_dir
    repository = repository_root()
    loaded = load_registry(GitSource(repository), args.revision, args.registry)
    # The executor's own artifact store, read-only: the artifact behind each decision's execution_ref
    # is what grants evidence credit, and a matching reference string alone never does.
    evidence = ExecutionEvidence(FileArtifacts(str(runtime_dir() / "artifacts")))
    receipt = DecisionFeedback(service.store, evidence=evidence).collect(
        registry=loaded["registry"], registry_revision=loaded["revision"], registry_path=loaded["path"],
        registry_sha256=loaded["sha256"], repository=repository_identity(repository),
        limit=args.limit, after=args.after or "")
    return {**receipt, "status": "collected", "exit_code": 0}


def status(service, args) -> dict:
    # Store read only.
    return {**DecisionFeedback(service.store).status(limit=args.limit), "status": "read", "exit_code": 0}


def report(service, args) -> dict:
    # Store read only.
    return {**DecisionFeedback(service.store).report(limit=args.limit, after=args.after or "",
                                                     collection_id=args.collection),
            "status": "read", "exit_code": 0}


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


def execute(service, args) -> dict:
    """Fixed-code failure rendering; exit 0 only for a recorded or read result."""
    try:
        if args.decision_feedback_command == "collect":
            return collect(service, args)
        if args.decision_feedback_command == "status":
            return status(service, args)
        return report(service, args)
    except Exception as exc:
        return refusal(exc)


__all__ = ["add_parser", "collect", "execute", "report", "status"]
