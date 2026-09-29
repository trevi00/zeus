"""The durable, fenced task graph (the part S4 moved ahead: guards and the execution-identity helpers).

Layer: application
Context: coordination
Owns: ClaimGuardRefused, check_expected, require_expected, CONTAINED_PROVIDER_CAUSES and the static
    `Workflow._attempt_outcome` / `Workflow._same_execution` (M7 `application/workflow.py`, moved ahead in S4
    unchanged: lead decision Option A; execution_time's deadline containment records the attempt outcome)
Does not own: submit, claim, _owned, heartbeat, remaining_seconds, complete, fail, cancel, handle and the rest of
    M7 `Workflow` (S4 continues with claim/owned/complete/fail once their clock/ticket/adoption/parking ports
    are wired; S5 the rest)
Entry points: ClaimGuardRefused, check_expected, require_expected, CONTAINED_PROVIDER_CAUSES, Workflow
Contracts: INV-LOCAL-CYCLE-001, INV-METRIC-001, INV-EXECUTION-IDENTITY-001
"""

from __future__ import annotations

from codex_harness.kernel.errors import ContractError, require


class ClaimGuardRefused(ContractError):
    """The row the claim policy would take is not the one the caller pre-selected."""


def check_expected(tx, bucket: str, expected: dict | None) -> None:
    """INV-LOCAL-CYCLE-001: an optional execution guard, validated inside the claim transaction
    before any row is claimed. `expected` names the row (`id`), its `correlation_id` and the
    `statuses` it may still be in. Unguarded callers (`expected is None`) keep the existing policy."""
    if expected is None:
        return
    require(isinstance(expected, dict) and isinstance(expected.get("id"), str)
            and isinstance(expected.get("correlation_id"), str)
            and isinstance(expected.get("statuses"), (set, frozenset, list, tuple)), "Invalid execution guard")
    row = tx.get(bucket, expected["id"])
    if row is None:
        raise ClaimGuardRefused("Expected execution missing: " + expected["id"])
    message = row.get("message")
    correlation = message.get("correlation_id") if isinstance(message, dict) else None
    if correlation != expected["correlation_id"]:
        raise ClaimGuardRefused("Expected execution correlation changed: " + expected["id"])
    if row.get("status") not in set(expected["statuses"]):
        raise ClaimGuardRefused("Expected execution status changed: " + expected["id"] + " is " + str(row.get("status")))


def require_expected(row: dict, expected: dict | None) -> None:
    """The row about to be claimed must be the guarded one; anything else is refused unclaimed."""
    if expected is not None and row["id"] != expected["id"]:
        raise ClaimGuardRefused("Claim policy selected " + str(row["id"]) + " instead of " + expected["id"])


# Provider refusals of the execution's own credential (INV-RECURRENCE-001 containment; never a retry).
# A read-only profile breach is contained as well: the model reached for a tool outside its read-only
# profile, and replaying the task would spend another real call on the same breach (INV-CLAUDE-WORKER-001).
CONTAINED_PROVIDER_CAUSES = frozenset({"codex-provider-usage-limit-exceeded", "claude-provider-usage-limit-exceeded",
                                       "claude-provider-authentication-failed",
                                       "claude-provider-read-only-violation"})


class Workflow:
    """Durable, fenced task graph. External work never holds a database transaction."""

    @staticmethod
    def _attempt_outcome(task, status, at, error=None):
        # INV-METRIC-001: retain failures across retries; never invent legacy outcomes.
        if task['attempt'] and not any(r['attempt'] == task['attempt']
                                      for r in task.get('attempt_outcomes', [])):
            task.setdefault('attempt_outcomes', []).append(
                {'attempt': task['attempt'], 'status': status, 'at': at, 'error': error})

    @staticmethod
    def _same_execution(current, task):
        keys = ('id', 'generation', 'attempt', 'lease_owner', 'agent', 'actor', 'recovery_sequence')
        for key in keys:
            default = 0 if key == 'recovery_sequence' else None
            left, right = current.get(key, default), task.get(key, default)
            if type(left) is not type(right) or left != right:
                return False
        return True
