"""The `zeus decision-feedback` argument parser (M7 adapters/decision_feedback_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus decision-feedback`)
Does not own: dispatch and composition (S10 unit C7)
Entry points: add_parser
Contracts: none

Moved from M7 adapters/decision_feedback_cli.py:47-62 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
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
