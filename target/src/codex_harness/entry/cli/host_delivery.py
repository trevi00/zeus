"""The `zeus host-delivery` argument parser (M7 adapters/host_delivery.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus host-delivery`)
Does not own: dispatch and composition (S10 unit C8)
Entry points: add_parser
Contracts: none

Moved from M7 adapters/host_delivery.py:1096-1137 and LANE_HELP at adapters/host_delivery.py:1092-1093 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

from pathlib import Path

from codex_harness.delivery.domain.host_delivery import WITHDRAW_REASONS

LANE_HELP = ("One registered Fleet lane whose store, repository and runtime own this delivery; "
             "omitted keeps the control store. The Fleet activation gate stays the control store's")


def add_parser(commands) -> None:
    delivery = commands.add_parser("host-delivery",
                                   help="Durable delivery of a reviewed release to a host target; "
                                        "opt-in, reuses Releases approval and the ReleaseQueue fence")
    sub = delivery.add_subparsers(dest="delivery_command", required=True)
    targets = sub.add_parser("register-targets",
                             help="Register the owner's authorized host target registry "
                                  "(urn:zeus:host-delivery-targets:1); host configuration only")
    targets.add_argument("--file", type=Path, required=True)
    register = sub.add_parser("register", help="Register one owner-approved plan read at a commit")
    register.add_argument("--revision", required=True, help="40-hex commit the plan is read at")
    register.add_argument("--path", required=True, help="Repository-relative plan path")
    tick = sub.add_parser("tick", help="Advance at most one delivery by at most one stage")
    tick.add_argument("--plan", default=None, help="One registered plan id; omitted selects one")
    run_command = sub.add_parser("run", help="Bounded tick loop; an empty queue idles without "
                                             "provider calls")
    run_command.add_argument("--once", action="store_true", help="One tick, then exit")
    run_command.add_argument("--interval", type=int, default=15, help="Seconds between ticks")
    run_command.add_argument("--max-ticks", type=int, default=0, dest="max_ticks",
                             help="Stop after this many ticks; 0 runs until stopped")
    status = sub.add_parser("status", help="Read the delivery projection; store read only")
    status.add_argument("--plan", default=None, help="One plan id; omitted reads every plan")
    withdraw = sub.add_parser("withdraw", help="Owner: retire one delivery the host never reached, on "
                                               "staleness observed now; plan, request and PR are kept")
    withdraw.add_argument("--plan", required=True, help="The registered plan id")
    withdraw.add_argument("--plan-sha256", required=True, dest="plan_sha256",
                          help="The registered plan digest (from status)")
    withdraw.add_argument("--reason", required=True, choices=WITHDRAW_REASONS)
    withdraw.add_argument("--evidence", required=True, help="sha256:<64 hex> reference of the owner decision")
    resume = sub.add_parser("resume", help="Owner: move a delivery that merged a never verified release and "
                                           "halted before the host back to verification (one transaction)")
    resume.add_argument("--plan", required=True, help="The registered plan id")
    resume.add_argument("--plan-sha256", required=True, dest="plan_sha256",
                        help="The registered plan digest (from status)")
    resume.add_argument("--evidence", required=True, help="sha256:<64 hex> reference of the owner decision")
    resume.add_argument("--document", default=None,
                        help="A typed recovery document (urn:zeus:host-delivery-first-activation:1, "
                             "urn:zeus:host-delivery-consumption-retry:1, -generation-restart:1 or "
                             "-consumption-rearm:1, by its kind); "
                             "--evidence must be sha256 of its canonical JSON")
    for command in (targets, register, tick, run_command, status, withdraw, resume):
        command.add_argument("--lane", default=None, help=LANE_HELP)
