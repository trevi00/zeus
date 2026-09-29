"""Shared S4 scenario steps (`coordination.decision_guards`): the decision-side owner operations ReviewDecisions
calls before any provider and before committing (lead decision Option A): ExecutionRecovery.validate_decision
on the paths that return or refuse before the related-evidence digest, and release_review_policy.

Layer: harness (never shipped)

`api.recovery(store)` is the side's ExecutionRecovery (the target injects the related-evidence projection;
these steps never reach it), `api.release_review_policy`. Values/refusals are compared.
"""

from __future__ import annotations

import hashlib
import json


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def run(api) -> dict:
    store = api.MemoryStore()
    recovery = api.recovery(store)
    base = {"id": "d1", "phase": "review_lead", "actor": "lead:improvement", "input": {}, "attempt": 0, "generation": 0}
    packet = {"bucket": "decisions_pending", "task_id": "d1"}
    ref = digest(packet)
    with store.transaction() as tx:
        tx.put("execution_recoveries", ref, {"id": ref, "packet": packet, "previous": {"generation": 1}})
        tx.put("execution_recoveries", "other", {"id": "other", "packet": {"bucket": "tasks", "task_id": "d1"}})
        out = {"validate": {
            "no_receipt": call(recovery.validate_decision, tx, base),
            "sequence_without_receipt": call(recovery.validate_decision, tx, {**base, "recovery_sequence": 1}),
            "budget_ref_without_receipt": call(recovery.validate_decision, tx, {**base, "retry_budget": {"recovery_ref": "x"}}),
            "receipt_not_text": call(recovery.validate_decision, tx, {**base, "recovery_receipt": 7}),
            "receipt_missing": call(recovery.validate_decision, tx, {**base, "recovery_receipt": "nope"}),
            "receipt_mismatched": call(recovery.validate_decision, tx, {**base, "recovery_receipt": "other"}),
            "generation_changed": call(recovery.validate_decision, tx, {**base, "recovery_receipt": ref,
                                                                         "retry_budget": {"recovery_ref": ref},
                                                                         "recovery_sequence": 1, "generation": 1}),
            "sequence_changed": call(recovery.validate_decision, tx, {**base, "recovery_receipt": ref,
                                                                       "retry_budget": {"recovery_ref": ref},
                                                                       "recovery_sequence": 2, "generation": 2}),
        }}
    out["release_review_policy"] = [call(api.release_review_policy, c) for c in (
        {"base": "b" * 40}, {"base": "b" * 40, "hook_id": "h1"}, {})]
    return out
