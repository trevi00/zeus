"""Shared S4 scenario steps (`coordination.execution_time`): execution deadlines, clock pins, liveness,
time containment, the running set and the rejection of fenced-out executors (lead decision Option A).

Layer: harness (never shipped)

`api` supplies MemoryStore, `dt` (the side's datetime class), `advance(seconds)` (the scripted clock),
`time` (deadline, check_clock, pin_clock, active, observe_domain, contain_with_notice, running,
ExecutionTimeError, DOMAIN) with the side's clock bound, `reconcile(store, lease, error, rejection_error=None)`
and `org`. Values and refusals (ExecutionTimeError reason and observation keys) are reported; the store's
final records are compared by digest.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timezone


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        row = {"refused": type(exc).__name__, "message": str(exc)[:200]}
        if hasattr(exc, "reason"):
            row["reason"] = exc.reason
            obs = getattr(exc, "observation", None)
            row["observation_keys"] = sorted(obs) if isinstance(obs, dict) else None
        return row
    if isinstance(value, tuple):
        value = list(value)
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    return {"value": value}


def task(tid, status="running", deadline=None, **extra):
    return {"id": tid, "agent": "worker:implementation", "status": status, "attempt": 1, "generation": 1,
            "lease_owner": "o1", "message": {"correlation_id": "c-" + tid, "when": {"deadline": deadline}}, **extra}


def run(api) -> dict:
    t, dt = api.time, api.dt
    out = {"domain_is_injected": t.DOMAIN == "00000000-0000-4000-8000-00000000e4e4"}
    now = dt(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    out["deadline"] = [call(t.deadline, row, bucket) for row, bucket in (
        (task("a"), "tasks"), (task("b", deadline="2026-01-01T01:00:00+00:00"), "tasks"),
        (task("c", deadline="soon"), "tasks"), ({"id": "d", "execution_deadline": "2026-01-02T00:00:00+00:00"},
                                                 "decisions_pending"),
        ({"id": "e"}, "tasks"), ({"id": "f"}, "decisions_pending"))]
    pin = {"version": 1, "domain": t.DOMAIN, "wall": "2026-01-01T00:00:00+00:00", "monotonic": 1000.0,
           "lease_seconds": 600, "deadline_remaining": None}
    out["check_clock"] = [call(t.check_clock, row, now, mono, domain) for row, mono, domain in (
        ({}, 1000.0, t.DOMAIN), ({"execution_clock": pin}, 1010.0, t.DOMAIN),
        ({"execution_clock": pin}, 1010.0, "other"), ({"execution_clock": pin}, 2000.0, t.DOMAIN),
        ({"execution_clock": {**pin, "version": 2}}, 1000.0, t.DOMAIN), ({"execution_clock": pin}, float("nan"), t.DOMAIN),
        ({"execution_clock": {**pin, "lease_seconds": -1}}, 1000.0, t.DOMAIN))]
    live = task("g", deadline="2026-01-01T02:00:00+00:00", lease_until="2026-01-01T00:10:00+00:00")
    out["pin"] = call(t.pin_clock, live, "tasks", now, dt(2026, 1, 1, 0, 10, 0, tzinfo=timezone.utc))
    out["pinned"] = live.get("execution_clock")
    out["active_fresh"] = call(t.active, live, "tasks", now)
    api.advance(30)
    now = dt(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc)
    out["active_later"] = call(t.active, live, "tasks", now)
    renewed = dict(live)
    out["pin_renew"] = call(t.pin_clock, renewed, "tasks", now, dt(2026, 1, 1, 0, 20, 0, tzinfo=timezone.utc), renew=True)
    out["renewed"] = renewed.get("execution_clock")
    out["active_past_deadline"] = call(t.active, task("h", deadline="2026-01-01T00:00:10+00:00",
                                                       lease_until="2026-01-01T00:10:00+00:00"), "tasks", now)
    out["active_no_lease"] = call(t.active, task("i"), "tasks", now)
    out["active_expired_lease"] = call(t.active, task("j", lease_until="2026-01-01T00:00:10+00:00"), "tasks", now)
    store = api.MemoryStore()
    with store.transaction() as tx:
        legacy = task("k", lease_until="2026-01-01T00:10:00+00:00")
        out["observe_legacy"] = call(t.observe_domain, tx, legacy, "tasks", now)
        out["observe_same_domain"] = call(t.observe_domain, tx, live, "tasks", now)
        out["observe_foreign"] = call(t.observe_domain, tx, {**legacy, "id": "l",
                                                              "execution_clock": {**pin, "domain": "other"}}, "tasks", now)
        blocked = task("m")
        out["contain_block"] = call(lambda: t.contain_with_notice(tx, api.org, blocked, "tasks", "InvalidExecutionLease",
                                                                   now, {"x": 1})["status"])
        out["contain_block_again"] = call(lambda: t.contain_with_notice(tx, api.org, dict(blocked), "tasks",
                                                                         "InvalidExecutionLease", now, {"x": 1})["status"])
        expired = task("n", deadline="2026-01-01T00:00:10+00:00")
        out["contain_deadline"] = call(lambda: {k: t.contain_with_notice(tx, api.org, expired, "tasks",
                                                                          "deadline_exceeded", now)[k]
                                                for k in ("status", "error", "attempt_outcomes")})
        for row in (task("p", lease_until="2026-01-01T00:10:00+00:00", execution_clock=renewed["execution_clock"]),
                    task("q", lease_until="2026-01-01T00:00:05+00:00"), task("r", status=""),
                    task("s", status="queued"), task("u", lease_until="bad")):
            tx.put("tasks", row["id"], row)
        out["running"] = call(lambda: sorted(r["id"] for r in t.running(tx, api.org, now)))
    with store.transaction() as tx:
        tx.put("tasks", "v", task("v", lease_until="2026-01-01T00:10:00+00:00", execution_clock=renewed["execution_clock"]))
        tx.put("tasks", "w", task("w", status="succeeded"))
        tx.put("tasks", "x", task("x", status="failed"))
        tx.put("tasks", "y", task("y", lease_until="2026-01-01T00:00:01+00:00"))
    err = RuntimeError("stale write")
    lease = task("v", lease_until="2026-01-01T00:10:00+00:00")
    out["reconcile"] = {
        "missing": call(api.reconcile, store, task("zz"), err),
        "identity_changed": call(api.reconcile, store, {**task("x"), "generation": 9}, err),
        "not_running": call(api.reconcile, store, task("x"), err),
        "succeeded_same": call(lambda: api.reconcile(store, task("w"), err)["status"]),
        "expired_lease": call(api.reconcile, store, task("y"), err),
        "expired_again": call(api.reconcile, store, task("y"), err),
        "valid_owner_reraises": call(api.reconcile, store, lease, err, ValueError("cause")),
        "invalid_identity": call(api.reconcile, store, {"id": "v", "_bucket": "tasks"}, err),
    }
    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out
