"""The `zeus continuation` argument parser (M7 adapters/continuation_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus continuation`)
Does not own: dispatch and composition (S10 unit C8)
Entry points: add_parser
Contracts: none

Moved from M7 adapters/continuation_cli.py:30-62 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

from pathlib import Path


def add_parser(commands) -> None:
    root = commands.add_parser("continuation", help="Opt-in conductor continuation over finite operations")
    sub = root.add_subparsers(dest="continuation_command", required=True)
    register = sub.add_parser("register", help="Register one owner policy read at a commit (urn:zeus:continuation-policy:1)")
    register.add_argument("--lane", required=True, help="Lane whose repository holds the policy")
    register.add_argument("--revision", required=True, help="40-hex commit the policy is read at")
    register.add_argument("--path", required=True, help="Repository-relative policy path")
    tick = sub.add_parser("tick", help="One bounded continuation pass; no model call when idle")
    tick.add_argument("--policy", required=True)
    status = sub.add_parser("status", help="Read the continuation projection; store read only")
    status.add_argument("--policy", default=None)
    identity = sub.add_parser("identity", help="Print a lane's session archive identity for authoring the policy")
    identity.add_argument("--lane", required=True)
    conduct = sub.add_parser("conduct", help="Lane side: the guarded conductor review of one accepted operation")
    conduct.add_argument("--file", type=Path, required=True, help="The operation's frozen manifest JSON")
    research = sub.add_parser("research-accept", help="Owner: record one scoped research receipt "
                              "(urn:zeus:continuation-research-receipt:1, or :2 for a mixed-cause family) for an "
                              "exact research intent")
    research.add_argument("--file", type=Path, required=True, help="The owner's receipt JSON")
    supplement = sub.add_parser("research-supplement", help="Owner: record one typed research scope supplement "
                                "(urn:zeus:continuation-research-scope-supplement:1); releases nothing by itself")
    supplement.add_argument("--file", type=Path, required=True, help="The owner's supplement JSON")
    ownership = sub.add_parser("ownership-reconcile", help="Owner: bind one admitted continuation successor to its "
                               "origin's Portfolio target through the persisted intent lineage")
    ownership.add_argument("--intent", required=True, help="The successor's continuation intent id")
    capacity = sub.add_parser("capacity-grant", help="Owner: one-use capacity for ONE exact evidence_repair intent "
                              "refused for correction_budget_exhausted (urn:zeus:continuation-capacity-grant:1); "
                              "the budget itself never grows")
    capacity.add_argument("--file", type=Path, required=True, help="The owner's grant JSON")
    requalify = sub.add_parser("delivery-requalify", help="Owner: supersede ONE delivery intent whose plan was "
                               "withdrawn by one fresh operation on the current main "
                               "(urn:zeus:continuation-delivery-requalification:1); never automatic")
    requalify.add_argument("--file", type=Path, required=True, help="The owner's requalification JSON")
