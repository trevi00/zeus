"""The `zeus execution-recovery` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus execution-recovery`)
Does not own: dispatch and composition (S10 unit C2)
Entry points: add_parser
Contracts: none

Moved from M7 cli.py:186-199 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

from pathlib import Path


def add_parser(commands) -> None:
    recovery = commands.add_parser('execution-recovery', help='Explicit trusted local operator recovery; no human attestation')
    actions = recovery.add_subparsers(dest='recovery_action', required=True)
    prepare = actions.add_parser('prepare')
    prepare.add_argument('task_id')
    prepare.add_argument('--bucket', choices=['tasks', 'decisions_pending'], default='tasks')
    prepare.add_argument('--operation', choices=['migrate', 'resume', 'repair'], required=True)
    prepare.add_argument('--max-attempts', type=int, required=True, help='Total ceiling including attempts already spent')
    prepare.add_argument('--deadline', help='Future aware ISO timestamp; existing deadline cannot be removed')
    prepare.add_argument('--reason', required=True)
    prepare.add_argument('--operator', required=True, help='Audit label, not authenticated identity')
    prepare.add_argument('--evidence', action='append', required=True, help='Existing sha256 artifact reference')
    prepare.add_argument('--output', type=Path, required=True)
    apply = actions.add_parser('apply')
    apply.add_argument('--packet', type=Path, required=True)
