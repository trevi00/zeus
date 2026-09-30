"""RF-RT, S5 part (addendum A1 v2): the research-first admission disposition persists across restart.

Layer: application
Context: coordination
Owns: bucket research_admissions (one record per task and action: the current state, the latest disposition, the
    evaluation history and a recorded resolution)
Does not own: the research package store, its freshness/version and applicability policy (research, S8: the injected
    `policy`), the consult point (execution.RunTask, S4), the production wiring (S10)
Entry points: PersistedResearchAdmission.admit, PersistedResearchAdmission.resolve
Contracts: INV-RESEARCH-001, INV-RESEARCH-004 (addendum A1 v2 RF-RT)

A declared S5 addition (no M7 code). It implements S4's `execution.ports.ResearchAdmission` structurally and joins the
caller's unit (§2.9 rule 2): RunTask opens the admission transaction before any provider effect.
- A non-admitting disposition (`research`, `blocked`) is *holding*: every later consult, after any restart, answers
  it from the record without asking the policy again, so no design/implementation is dispatched (an unresolved
  material contradiction stays blocked).
- Only a recorded resolution (`resolve`, naming its evidence) releases a holding record; the next consult then runs
  the ordinary admission check.
- An admitting disposition (`admit`, `exempt`) is recorded with its reason and re-evaluated on every consult, because
  freshness and version changes are the policy's (S8) to judge.
- An absent policy or an unknown disposition refuses (CE-9: never an invented admission) and writes nothing.
"""

from __future__ import annotations

import re

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import digest, utcnow

BUCKET = "research_admissions"
ADMITTING = frozenset({"admit", "exempt"})
DISPOSITIONS = ADMITTING | {"research", "blocked"}
HOLDING, ADMITTED, RESOLVED = "holding", "admitted", "resolved"
EVIDENCE_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


def admission_key(task_id: str, action: str) -> str:
    return digest({"task": task_id, "action": action})


class PersistedResearchAdmission:
    """The persisted side of research-first admission; `policy.admit(tx, lease, action)` is research's (S8)."""

    def __init__(self, policy=None, *, clock=None):
        self.policy, self.clock = policy, clock

    def admit(self, tx, lease: dict, action: str) -> dict:
        key = admission_key(lease["id"], action)
        record = tx.get(BUCKET, key)
        if record is not None and record["state"] == HOLDING:
            # Restart and redelivery answer from the durable record; the policy is not asked again.
            return {"disposition": record["disposition"], "reason": record["reason"], "persisted": True}
        require(self.policy is not None, "Research admission policy is not wired")
        decided = self.policy.admit(tx, lease, action)
        disposition = decided.get("disposition") if isinstance(decided, dict) else None
        require(disposition in DISPOSITIONS, "Unknown research admission disposition")
        reason = str(decided.get("reason"))
        at = utcnow(self.clock)
        history = list((record or {}).get("history") or []) + [{"disposition": disposition, "reason": reason, "at": at}]
        tx.put(BUCKET, key, {"id": key, "task_id": lease["id"], "action": action,
                             "state": ADMITTED if disposition in ADMITTING else HOLDING,
                             "disposition": disposition, "reason": reason, "history": history,
                             "resolution": (record or {}).get("resolution"), "updated_at": at})
        return {"disposition": disposition, "reason": reason, "persisted": False}

    def resolve(self, tx, task_id: str, action: str, *, resolution_ref: str, actor: str) -> dict:
        """Release a holding record on a recorded resolution (its evidence reference); the next consult re-evaluates."""
        record = tx.get(BUCKET, admission_key(task_id, action))
        require(record is not None and record["state"] == HOLDING, "No holding research admission to resolve")
        require(isinstance(resolution_ref, str) and EVIDENCE_REF.fullmatch(resolution_ref) is not None,
                "A resolution must name its evidence reference")
        require(isinstance(actor, str) and bool(actor.strip()), "A resolution must name its actor")
        at = utcnow(self.clock)
        record.update(state=RESOLVED, updated_at=at,
                      resolution={"ref": resolution_ref, "actor": actor, "at": at,
                                  "released": {"disposition": record["disposition"], "reason": record["reason"]}})
        tx.put(BUCKET, record["id"], record)
        return record
