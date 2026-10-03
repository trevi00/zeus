"""The `zeus owner-actions` argument parser (M7 adapters/owner_actions.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus owner-actions`)
Does not own: dispatch and composition (S10 unit C8)
Entry points: add_parser
Contracts: INV-HOST-DELIVERY-FIRST-ACTIVATION-001, INV-OWNER-ACTIONS-001, INV-OWNER-ACTIONS-MIGRATION-001

Moved from M7 adapters/owner_actions.py:509-537 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""


def add_parser(commands) -> None:
    root = commands.add_parser("owner-actions", help="Server-owned research acceptance, delivery-plan and canary "
                                                     "handoffs (opt-in; approves nothing itself)")
    sub = root.add_subparsers(dest="owner_actions_command", required=True)
    register = sub.add_parser("register", help="Register the owner policy read at a commit "
                                               "(urn:zeus:owner-actions-policy:1 or :2)")
    register.add_argument("--lane", required=True)
    register.add_argument("--revision", required=True)
    register.add_argument("--path", required=True)
    tick = sub.add_parser("tick", help="One bounded pass; no model call and no write when idle")
    tick.add_argument("--policy", required=True)
    run = sub.add_parser("run", help="Gated wakeup loop over `tick` of every named policy in turn")
    run.add_argument("--policy", required=True, action="append",
                     help="A registered owner policy id; repeat it to tick several in this one process")
    run.add_argument("--interval", type=int, default=15)
    run.add_argument("--max-ticks", type=int, default=0, dest="max_ticks")
    status = sub.add_parser("status", help="Read the owner-action projection; store read only")
    status.add_argument("--policy", default=None)
    migrate = sub.add_parser("migrate", help="Record ONE owner-approved evaluator migration of a check-rejected "
                                             "merged release (INV-OWNER-ACTIONS-MIGRATION-001); tick advances it")
    migrate.add_argument("--document", required=True, help="JSON migration document (exact keys)")
    # INV-OWNER-ACTIONS-001 x INV-HOST-DELIVERY-FIRST-ACTIVATION-001: the typed owner canary recovery.
    recover = sub.add_parser("canary-recover", help="Return ONE halted owner canary to its SAME queued job after "
                             "the lane consumption retry (exact document and its sha256 evidence)")
    recover.add_argument("--document", required=True, help="JSON owner canary-recovery document (exact keys)")
    recover.add_argument("--evidence", required=True, help="sha256:<digest of the document>")
    assess_parser = sub.add_parser("assess", help="Guardian child: the guarded independent assessment of one row")
    assess_parser.add_argument("--decision", required=True)
    assess_parser.add_argument("--correlation", required=True)
