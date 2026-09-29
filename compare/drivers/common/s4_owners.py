"""Shared S4 scenario steps (`coordination.execution_owners`): the moved-ahead coordination owner operations
the S4 units write (lead decision Option A): execution fences, execution budget and execution notices.

Layer: harness (never shipped)

`api` supplies MemoryStore, the side's `fence`, `budget` and `notices` modules, `org` (the packaged
organization) and `now` (an aware datetime from the scripted clock). Every step reports its value or its
refusal, and the store's final records (bucket, key, sha256 of the canonical body) are compared.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

NOW = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    return {"value": value}


def row(status="failed", agent="worker:implementation", attempt=1, generation=1, **extra):
    return {"id": "task-1", "agent": agent, "status": status, "attempt": attempt, "generation": generation,
            "message": {"correlation_id": "corr-1"}, **extra}


def records(store) -> list:
    with store.transaction() as tx:
        rows = tx.records()
    return sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)


def run(api) -> dict:
    out = {}
    store = api.MemoryStore()
    fence, budget, notices = api.fence, api.budget, api.notices
    with store.transaction() as tx:
        out["fence"] = {
            "unused": call(fence.require_unused, tx, "tasks", "t1"),
            "advance_1": call(fence.advance, tx, "tasks", "t1", 1, "o1"),
            "current": call(fence.current, tx, "tasks", "t1"),
            "require_current_ok": call(fence.require_current, tx, "tasks", "t1", 1, "o1"),
            "require_current_stale": call(fence.require_current, tx, "tasks", "t1", 0, "o1"),
            "require_current_other_owner": call(fence.require_current, tx, "tasks", "t1", 1, "o2"),
            "require_current_no_fence": call(fence.require_current, tx, "tasks", "t9", 3),
            "advance_regress": call(fence.advance, tx, "tasks", "t1", 1, "o2"),
            "advance_zero": call(fence.advance, tx, "tasks", "t1", 0),
            "advance_2": call(fence.advance, tx, "tasks", "t1", 2, "o2"),
            "unused_after": call(fence.require_unused, tx, "tasks", "t1"),
            "key": fence.key("decisions_pending", "d1"), "bucket": fence.BUCKET,
        }
    out["budget"] = {
        "positive": [call(budget.positive_integer, v, "N") for v in (1, 0, True, "2")],
        "aware": [call(lambda v: budget.aware_time(v).isoformat(), v) for v in (NOW, datetime(2026, 1, 1))],
        "deadline": [call(lambda v: None if budget.deadline_time(v) is None else budget.deadline_time(v).isoformat(), v)
                     for v in (None, "2026-01-02T00:00:00+00:00", "2026-01-02T00:00:00", "", "nope", 7)],
    }
    with store.transaction() as tx:
        fresh = row(status="running", attempt=0)
        tx.put("tasks", "task-1", fresh)
        out["budget"]["retry_first_default"] = call(budget.retry_limit, tx, fresh, "tasks", None, NOW, api.org)
        out["budget"]["retry_conflict"] = call(budget.retry_limit, tx, fresh, "tasks", 5, NOW, api.org)
        out["budget"]["retry_bad"] = call(budget.retry_limit, tx, fresh, "tasks", 0, NOW, api.org)
        legacy = row(status="running", attempt=2)
        legacy["id"] = "task-2"
        tx.put("tasks", "task-2", legacy)
        out["budget"]["retry_legacy_blocks"] = call(budget.retry_limit, tx, legacy, "tasks", None, NOW, api.org)
        out["budget"]["legacy_row"] = {k: legacy.get(k) for k in ("status", "error")}
        blocked = row(status="running")
        blocked["id"] = "task-3"
        out["budget"]["block"] = call(lambda: budget.block_execution(tx, blocked, "tasks", "RecoveryContextChanged",
                                                                     NOW, api.org))
    with store.transaction() as tx:
        at = NOW.isoformat()
        failed = row()
        failed["id"] = "task-4"
        first = notices.record(tx, api.org, failed, "tasks", "execution_failed", at)
        again = notices.record(tx, api.org, failed, "tasks", "execution_failed", at)
        out["notices"] = {
            "first": {k: first.get(k) for k in ("id", "transition", "authority", "observer", "source_hash")},
            "message": {k: first["message"][k] for k in ("message_id", "type", "who", "what", "when", "why")},
            "idempotent": again == first,
            "unknown_reason_quarantined": {k: v for k, v in notices.record(
                tx, api.org, failed, "tasks", "no_such_reason", at).items() if k != "source"},
            "succeeded_without_proof": notices.record(tx, api.org, row(status="succeeded"), "tasks",
                                                      "research_required", at).get("status"),
            "decision_notice": notices.record(tx, api.org, {**{k: v for k, v in row(status="blocked").items()
                                                               if k != "agent"}, "actor": "lead:improvement",
                                                            "id": "d-1"}, "decisions_pending", "execution_failed",
                                              at)["message"]["who"],
            "receive": call(notices.receive, tx, first["message"]),
            "receive_again": call(notices.receive, tx, first["message"]),
            "receive_unproven": call(notices.receive, tx, {**first["message"], "message_id": "x" * 64}),
            "reasons": sorted(notices.REASONS), "failed_states": sorted(notices.FAILED_STATES),
        }
    out["receive_foreign_wrong_type"] = call(notices.receive_foreign, store, {"type": "task.assign"})
    out["records"] = records(store)
    return out
