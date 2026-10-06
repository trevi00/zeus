"""The `zeus worker-session` argument parser (M7 adapters/worker_sessions.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus worker-session`), run (its body: M7 worker_session_command), _execute and _refusal (M7 worker_sessions.execute and refusal)
Does not own: dispatch (entry.cli main) and composition (composition.cli_sessions)
Entry points: add_parser, run
Contracts: INV-WORKER-SESSION-001

Moved from M7 adapters/worker_sessions.py:272-279 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is M7 `cli.py` `worker_session_command` (:524-533), `_execute` is `adapters/worker_sessions.py:288-297` (`execute`) and `_refusal` is :300-303 (`refusal`), verbatim except that the service is built first (as M7 `main()` did) and the archives, the evidence store and the owner are the builders of `composition.cli_sessions` (S10 unit C7a, R-c11).
"""


def add_parser(commands) -> None:
    session = commands.add_parser("worker-session", help="Durable Claude task sessions: read-only status, explicit close")
    sub = session.add_subparsers(dest="worker_session_command", required=True)
    status = sub.add_parser("status", help="Bounded status; ids, hashes and states only (store read only)")
    status.add_argument("--task-id", default=None)
    close = sub.add_parser("close", help="Close an archival_pending session after its bound promotion receipt "
                                         "re-verifies in the evidence store; archives are retained")
    close.add_argument("--task-id", required=True)


def run(args) -> None:
    """INV-WORKER-SESSION-001: read-only status and explicit close; refusals print a code and a
    type, never transcript bytes, archive paths, DSNs or raw exceptions."""
    from codex_harness.composition import build
    from codex_harness.entry.cli.output import emit
    service = build()
    try:
        result = _execute(service, args)
    except Exception as exc:
        emit(_refusal(exc))
        raise SystemExit(1) from exc
    emit(result)


def _execute(service, args, archives=None, evidence=None) -> dict:
    from codex_harness.composition import cli_sessions
    archives = archives or cli_sessions.session_archives()
    if args.worker_session_command == "status":
        # Store reads only: no evidence store is opened (or created) for a status read.
        return {**cli_sessions.worker_sessions(service, archives).status(args.task_id), "exit_code": 0}
    owner = cli_sessions.worker_sessions(service, archives,
                                         evidence=evidence if evidence is not None else cli_sessions.evidence_store())
    row = owner.close(args.task_id)
    return {"closed": row["state"] == "closed", "task_id": args.task_id, "state": row["state"],
            "archive_retained": (row.get("cleanup") or {}).get("archive_retained"), "exit_code": 0}


def _refusal(exc) -> dict:
    """A code and a type; never a path, transcript text or a raw exception message."""
    return {"refused": True, "reason": getattr(exc, "reason", None) or "error", "error_type": type(exc).__name__,
            "exit_code": 1}
