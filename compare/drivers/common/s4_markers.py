"""Shared S4 scenario steps (`observation.termination_markers`): the Observer's durable unconfirmed-effect
markers (M7 `Observer.termination_id/mark_unconfirmed/close_unconfirmed`), moved ahead under Option A.

Layer: harness (never shipped)

`api.observer(store)` is the side's Observer (a fixed clock, pid, host and process run id). Values/refusals,
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
    observer = api.observer(store)
    lease = {"id": "t1", "generation": 2, "attempt": 1}
    decision = {"id": "d1", "_bucket": "decisions_pending", "generation": 1, "attempt": 1}
    out = {"termination_id": [observer.termination_id(lease), observer.termination_id(decision)]}
    with store.transaction() as tx:
        out["close_without_marker"] = call(observer.close_unconfirmed, tx, lease, "accepted")
        out["mark"] = call(observer.mark_unconfirmed, tx, lease, reservation_id="r1")
        out["mark_again"] = call(observer.mark_unconfirmed, tx, lease, reservation_id="r2")
        out["close_unknown"] = call(observer.close_unconfirmed, tx, lease, "whatever")
        out["close"] = call(observer.close_unconfirmed, tx, lease, "accepted")
        out["close_again"] = call(observer.close_unconfirmed, tx, lease, "observed_failure")
        out["mark_after_close"] = call(observer.mark_unconfirmed, tx, lease, reservation_id="r3")
        out["mark_decision"] = call(observer.mark_unconfirmed, tx, decision, reservation_id="r4")
        out["close_decision_not_entered"] = call(observer.close_unconfirmed, tx, decision, "not_entered")
    out["counters"] = {k: observer.counters[k] for k in ("unconfirmed_marked", "unconfirmed_closed")}
    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out
