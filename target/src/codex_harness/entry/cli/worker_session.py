"""The `zeus worker-session` argument parser (M7 adapters/worker_sessions.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus worker-session`)
Does not own: dispatch and composition (S10 unit C7)
Entry points: add_parser
Contracts: none

Moved from M7 adapters/worker_sessions.py:272-279 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    session = commands.add_parser("worker-session", help="Durable Claude task sessions: read-only status, explicit close")
    sub = session.add_subparsers(dest="worker_session_command", required=True)
    status = sub.add_parser("status", help="Bounded status; ids, hashes and states only (store read only)")
    status.add_argument("--task-id", default=None)
    close = sub.add_parser("close", help="Close an archival_pending session after its bound promotion receipt "
                                         "re-verifies in the evidence store; archives are retained")
    close.add_argument("--task-id", required=True)
