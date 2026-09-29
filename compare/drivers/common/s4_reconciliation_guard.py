"""Shared S4 scenario steps (`observation.reconciliation_guard`): the Observer's reconciliation guard (M7
`Observer._other_attempt/guard_reservation`, `ReconciliationRequired`, `MemoryDirectory`), moved ahead under Option A.

Layer: harness (never shipped)

`api.observer(store, directory)` is the side's Observer (a fixed clock, pid, host and process run id). Values/refusals,
the counters and the store's final records (by body digest) are compared.
"""

from __future__ import annotations

import hashlib
import json


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def run(api) -> dict:
    store = api.MemoryStore()
    directory = api.MemoryDirectory()
    observer = api.observer(store, directory)
    attempt1 = {"id": "t1", "generation": 2, "attempt": 1}
    attempt2 = {"id": "t1", "generation": 2, "attempt": 2}

    def detail(tx, lease):
        result = call(observer.guard_reservation, tx, lease)
        try:
            observer.guard_reservation(tx, lease)
        except api.ReconciliationRequired as exc:
            result["detail"] = [type(exc).__name__, exc.task_id, sorted(r["record_id"] for r in exc.records)]
        except Exception:
            pass
        return result

    out = {}
    with store.transaction() as tx:
        out["no_rows"] = call(observer.guard_reservation, tx, attempt2)
        observer.mark_unconfirmed(tx, attempt2, reservation_id="r2")
        out["own_attempt_marker"] = call(observer.guard_reservation, tx, attempt2)
        marker = observer.mark_unconfirmed(tx, attempt1, reservation_id="r1")
        out["earlier_unconfirmed"] = detail(tx, attempt2)
        observer.close_unconfirmed(tx, attempt1, "observed_failure")
        out["earlier_closed"] = call(observer.guard_reservation, tx, attempt2)
        tx.put("observation_terminations", marker["record_id"], {**marker, "status": "pending_reconciliation"})
        out["earlier_pending_reconciliation"] = detail(tx, attempt2)
        other = {"id": "t9", "_bucket": "decisions_pending", "generation": 1, "attempt": 1}
        observer.mark_unconfirmed(tx, other, reservation_id="r9")
        out["other_bucket"] = call(observer.guard_reservation, tx, {"id": "t9", "generation": 1, "attempt": 2})
        directory.record_termination("rid-x", {"record_id": "rid-x", "task_id": "t5", "generation": 1, "attempt": 1})
        out["directory_other_attempt"] = call(observer.guard_reservation, tx, {"id": "t5", "generation": 1, "attempt": 2})
        directory.record_termination("rid-u", {"record_id": "rid-u", "task_id": "t6", "generation": 1, "attempt": 1,
                                                 "unreadable": True})
        out["directory_unreadable_same_attempt"] = call(observer.guard_reservation, tx,
                                                        {"id": "t6", "generation": 1, "attempt": 1})
    fresh = api.MemoryDirectory()
    row = {"record_id": "rid-x", "task_id": "t5", "generation": 1, "attempt": 1}
    out["directory_ops"] = {
        "record": call(fresh.record_termination, "rid-x", row),
        "record_again": call(fresh.record_termination, "rid-x", row),
        "pending_all": call(fresh.pending_terminations),
        "pending_t5": call(fresh.pending_terminations, "t5"),
        "resolve_unknown": call(fresh.resolve_termination, "nope", "rerun"),
        "resolve": call(fresh.resolve_termination, "rid-x", {"resolution": "rerun"}),
        "resolve_again": call(fresh.resolve_termination, "rid-x", {"resolution": "rerun"}),
        "pending_after": call(fresh.pending_terminations),
    }
    out["counters"] = dict(observer.counters)
    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out
