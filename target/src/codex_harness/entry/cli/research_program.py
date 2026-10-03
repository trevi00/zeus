"""The `zeus research-program` argument parser (M7 adapters/research_program_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus research-program`)
Does not own: dispatch and composition (S10 unit C6)
Entry points: add_parser
Contracts: INV-DISCOVERY-PRESSURE-001

Moved from M7 adapters/research_program_cli.py:29-55 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

from pathlib import Path

from codex_harness.research.domain.discovery_pressure import INTENTS


def add_parser(commands) -> None:
    program = commands.add_parser("research-program", help="Finite discovery program: local + live feeds -> dedup -> "
                                                           "<=1 council per tick; operator-authorized bounds")
    sub = program.add_subparsers(dest="research_program_command", required=True)
    register = sub.add_parser("register", help="Register one immutable program config (urn:zeus:research-program:1); no models")
    register.add_argument("--file", type=Path, required=True)
    run = sub.add_parser("run", help="Run up to N collection ticks under the program bounds")
    run.add_argument("program_id")
    run.add_argument("--ticks", type=int, required=True, help="Requested cap for this invocation; never above max_cycles")
    # INV-DISCOVERY-PRESSURE-001: why this run fetches external feeds; no default and no inference.
    run.add_argument("--intent", required=True, choices=INTENTS,
                     help="proactive (pressure-gated) or an exempt reason: user_request, incident, "
                          "existing_work_result, task_required")
    run.add_argument("--cycle-owner", default=None, dest="cycle_owner",
                     help="64-hex owner token of the ONE cycle this run reserves (--ticks 1 only): the owner-actions "
                          "launch id, so its observer binds the cycle to that launch and never to a number alone")
    for name, text in (("status", "Safe read-only projection; store read only"), ("pause", "Block new ticks; an owned cycle finishes"),
                       ("resume", "Allow new ticks again (paused only)")):
        sub.add_parser(name, help=text).add_argument("program_id")
    recover = sub.add_parser("recover", help="Owner request (urn:zeus:research-dispatch-recovery:1): authorize ONE "
                                             "replacement of a proven pre-provider failed dispatch; version 2 "
                                             "(execution_revocation) revokes instead of proving; version 3 "
                                             "(settled_read_only_successor) succeeds a current failed "
                                             "read-only council once; urn:zeus:research-dispatch-followup:1 "
                                             "(accepted_evidence_followup) follows up an accepted report-only "
                                             "dispatch for new authoritative members once; no models")
    recover.add_argument("--file", type=Path, required=True)
