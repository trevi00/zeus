"""The release review policy a decision proposes against (M7 `application/decision_recovery.py`, part).

Layer: application
Context: coordination
Owns: release_review_policy (moved ahead in S4 unchanged: lead decision Option A, the policy the §2.9 decision
    unit's release proposal carries)
Does not own: `context` (the recovered-decision evidence projection: audit gate and research dispatch, S5/S8)
Entry points: release_review_policy
Contracts: INV-RELEASE-001
"""

from __future__ import annotations


def release_review_policy(candidate):
    checks = ['tests', 'cli_start', 'cli_file_task']
    if candidate.get('hook_id'):
        checks += ['hook_reproduction', 'hook_normal_case']
    return {'checks': checks, 'revision': candidate['base']}
