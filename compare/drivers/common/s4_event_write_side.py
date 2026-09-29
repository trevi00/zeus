"""Shared S4 scenario steps (`observation.event_write_side`): the Observer's event write side (M7 `Observer.emit/
audit/audit_system/alert/health/record_termination/pending_terminations/resolve_termination`, `build_event`,
`PostExecutionRecordFailure`, `MemorySpool`), moved ahead under Option A.

Layer: harness (never shipped)

`api.observer(store, spool, directory, monotonic)` is the side's Observer (a fixed clock, pid, host and the given
monotonic callable). Values/refusals, the spool records, the directory maps, the counters and the store's final
records (by body digest) are compared.
"""

from __future__ import annotations

import hashlib
import json

RUN_ID = "0" * 31 + "1"


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


class DownStore:
    """Harness-only: a sink that is down."""

    def transaction(self):
        raise RuntimeError("store down")


def run(api) -> dict:
    ticks = [0.0]
    store = api.MemoryStore()
    directory = api.MemoryDirectory()
    alert_row = {"event_id": "e" * 64, "event_type": "operations.sink_unavailable",
                 "observed_at": "2026-01-01T00:00:00+00:00", "notification": {"status": "pending", "channel": None}}
    directory.write_pending_alerts("f" * 32, [alert_row])
    spool = api.MemorySpool(RUN_ID)
    observer = api.observer(store, spool, directory, lambda: ticks[0])
    out = {}

    out["inheritance"] = {
        "inherited_pending": {run_id: len(rows) for run_id, rows in observer.inherited_pending.items()},
        "refresh": call(observer.refresh_inherited_alerts),
    }

    out["emit"] = {
        "valid": call(observer.emit, "general.process_idle_exit", "observed",
                      attributes={"agent": None, "idle_seconds": 5}),
        "unknown_attribute": call(observer.emit, "general.process_idle_exit", "observed", attributes={"nope": 1}),
        "redaction": call(observer.emit, "general.message_accepted", "observed",
                          attributes={"message_id": "m1", "message_type": "t", "result_kind": "ghp_" + "a" * 30}),
        "bad_category": call(observer.emit, "bogus.x", "observed"),
    }

    audit = {}
    with store.transaction() as tx:
        attrs = {"reservation_id": "r1", "reason": "x"}
        audit["stored"] = call(observer.audit, tx, "development.invocation_abandoned", "observed",
                               identity=["t1", "reserve"], attributes=attrs)
        audit["redelivered"] = call(observer.audit, tx, "development.invocation_abandoned", "observed",
                                    identity=["t1", "reserve"], attributes=attrs)
        audit["quarantined"] = call(observer.audit, tx, "development.invocation_abandoned", "observed",
                                    identity=["t1", "reserve"], attributes={"reservation_id": "r1", "reason": "y"})
        audit["system"] = call(observer.audit_system, tx, "general.process_idle_exit", "observed",
                               identity=["sys", 1], attributes={"agent": None, "idle_seconds": 1})
        audit["no_identity"] = call(observer.audit, tx, "general.process_idle_exit", "observed", identity=[],
                                    attributes={"agent": None, "idle_seconds": 1})
    out["audit"] = audit

    sink_attrs = {"sink": "postgres", "error_type": "X", "pending": 0}
    alerts = {"first": call(observer.alert, "sink_unavailable", "k1", attributes=sink_attrs),
              "suppressed": call(observer.alert, "sink_unavailable", "k1", attributes=sink_attrs)}
    ticks[0] = 301.0
    alerts["after_window"] = call(observer.alert, "sink_unavailable", "k1", attributes=sink_attrs)
    out["alert_dedupe"] = alerts

    failures = {}
    valid = ("general.process_idle_exit", "observed")
    spool.fail_with = api.SpoolFull("memory spool full")
    failures["spool_full"] = call(observer.emit, *valid, attributes={"agent": None, "idle_seconds": 2})
    spool.fail_with = OSError("disk")
    failures["spool_oserror"] = call(observer.emit, *valid, attributes={"agent": None, "idle_seconds": 3})
    spool.fail_with = None
    out["spool_failures"] = failures

    sink = {}
    observer.store = DownStore()
    sink["down_alert"] = call(observer.alert, "spool_append_failed", "k2", attributes={"error_type": "X", "dropped": 1})
    sink["down_pending"] = len(observer.pending_alerts)
    sink["down_state"] = observer.sink_state
    observer.store = store
    ticks[0] = 700.0
    sink["recovered_alert"] = call(observer.alert, "spool_append_failed", "k3",
                                   attributes={"error_type": "Y", "dropped": 2})
    sink["recovered_pending"] = len(observer.pending_alerts)
    sink["recovered_state"] = observer.sink_state
    out["sink"] = sink

    lease = {"id": "t1", "generation": 1, "attempt": 1}

    def terminate():
        return observer.record_termination(
            lease, reservation_id="r1", classification="unknown", stream_hash=None,
            error=RuntimeError("boom sk-ant-oat01-" + "x" * 40), evidence_refs=("sha256:" + "a" * 64, "not a ref"))

    termination = {"first": call(terminate), "redelivered": call(terminate)}
    out["record_termination"] = termination
    record_id = termination["first"].get("value")

    pending = {"all": call(observer.pending_terminations, "t1")}
    observer.store = DownStore()
    pending["store_down"] = call(observer.pending_terminations, "t1")
    pending["store_down_strict"] = call(observer.pending_terminations, "t1", strict=True)
    observer.store = store
    out["pending_terminations"] = pending

    resolve = {
        "rerun": call(observer.resolve_termination, record_id, resolution="rerun", operator="op-1", reason="checked"),
        "redelivered": call(observer.resolve_termination, record_id, resolution="rerun", operator="op-1",
                            reason="checked"),
        "discard": call(observer.resolve_termination, record_id, resolution="discard", operator="op-1",
                        reason="checked"),
        "bad_resolution": call(observer.resolve_termination, record_id, resolution="maybe", operator="op-1",
                               reason="checked"),
        "bad_operator": call(observer.resolve_termination, record_id, resolution="rerun", operator="has spaces",
                             reason="checked"),
        "unknown_id": call(observer.resolve_termination, "f" * 64, resolution="rerun", operator="op-1",
                           reason="checked"),
        "pending_after": call(observer.pending_terminations, "t1"),
    }
    out["resolve_termination"] = resolve

    failure = api.PostExecutionRecordFailure("rid-1", ValueError("secret ghp_" + "b" * 30), "settlement")
    out["post_execution_record_failure"] = {"text": str(failure), "record_id": failure.record_id,
                                           "boundary": failure.boundary}

    out["health"] = call(observer.health)
    out["counters"] = dict(observer.counters)
    out["spool_records"] = spool.records()
    out["directory"] = {"health": directory.health, "pending": directory.pending,
                        "terminations": directory.terminations, "resolved": directory.resolved}
    out["close"] = call(observer.close)
    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out
