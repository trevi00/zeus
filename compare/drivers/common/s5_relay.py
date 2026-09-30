"""Shared S5 scenario steps (`coordination.outbox_relay`): M7 `outbox.relay`, `pin_route` and `bus_route` (RESEARCH-S5
D2, local check (b)).

- **Global batch.** It publishes, advances the cursor and writes the health row.
- **Poison records.** Invalid shape, schema, identity mismatch and an unauthorized route are quarantined once; the
  second pass is `quarantined_existing`.
- **Legacy and delivered records.** A legacy `sent` flag is not certified. An already delivered entry is `skipped`
  and marked sent.
- **Transport failures.** A MessageDeliveryError or TransportChanged is a `retry` with its attempt evidence, and the
  next attempt publishes. An unexpected error is recorded as `error` and re-raised after the commit. Changed content
  under an attempted identity is quarantined.
- **Scoped batches.** They touch only their own correlation and report `unfinished`, `remaining` and `complete`.
- **Route pins.** A pinned record is held, refused or published by the matching route. A malformed pin and a known
  scoped run without a pin are `route_unavailable`, and a second pin to another route is `route_conflict`.
- **Transport bindings.** The binding is committed with the attempt; an unreadable identity hands nothing over.
- **Arguments.** Out-of-range limits and an empty scope refuse.

Layer: harness (never shipped)

`api` supplies MemoryStore, `relay(store, org, bus, limit, audit, correlation_id)`, `pin_route(tx, correlation,
route, at)`, `validate_message`, `MessageDeliveryError`, `TransportChanged`, `envelope(...)`, `advance(seconds)` and
`org`. The fixture bus validates through the side's own message schema. The compared results are the counts, the
refusals, the published sequence, the audit calls (type, outcome, reason) and the final store records by body digest.
"""

from __future__ import annotations

import copy
import hashlib
import json


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Bus:
    """A scripted bus: `plan` maps a message id to a list of failures consumed in order ("delivery", "changed",
    "boom"); an empty list or an absent id publishes and returns a deterministic entry id."""

    def __init__(self, api, published, plan=None, route=None, namespace=None):
        self.api, self.published, self.plan = api, published, plan or {}
        if route is not None:
            self.route, self.namespace = route, namespace

    def validate(self, message):
        return self.api.validate_message(message)

    def publish(self, message):
        failures = self.plan.get(message["message_id"]) or []
        if failures:
            kind = failures.pop(0)
            if kind == "delivery":
                raise self.api.MessageDeliveryError("ConnectionError")
            if kind == "changed":
                raise self.api.TransportChanged("fixture transport changed")
            raise RuntimeError("fixture unexpected failure")
        self.published.append(message["message_id"])
        return "entry-" + str(len(self.published))


class BoundBus(Bus):
    """A binding-capable bus: `transport()` names its identity (or fails), `publish` takes the binding back."""

    def __init__(self, api, published, identity=None, fail_identity=False):
        super().__init__(api, published)
        self.identity, self.fail_identity, self.bindings = identity, fail_identity, []

    def transport(self):
        if self.fail_identity:
            raise self.api.MessageDeliveryError("TimeoutError")
        return dict(self.identity)

    def publish(self, message, transport=None):
        self.bindings.append(transport)
        return super().publish(message)


def attempt(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def put(store, identity, body):
    with store.transaction() as tx:
        tx.put("outbox", identity, body)


def message(api, correlation, objective, sender="conductor", recipient="lead:improvement"):
    return api.envelope("task.assign", sender, recipient, "plan", {"plan": {"objective": objective}}, correlation)


def queue(api, store, correlation, objective, **kw):
    m = message(api, correlation, objective, **kw)
    put(store, m["message_id"], {"message": m, "sent": False})
    return m


def run(api) -> dict:
    out, audits, published = {}, [], []

    def audit(tx, kind, outcome, **kw):
        audits.append([kind, outcome, kw.get("reason_code"), sorted(kw)])

    store = api.MemoryStore()
    relay = api.relay

    # global batch: good records, poison records, legacy sent
    for i in range(2):
        queue(api, store, "corr-g", "g" + str(i))
    put(store, "poison-shape", {"message": {"x": 1}, "sent": "no"})
    broken = message(api, "corr-p", "p")
    del broken["why"]
    put(store, broken["message_id"], {"message": broken, "sent": False})
    mismatch = message(api, "corr-p", "m")
    put(store, "not-the-message-id", {"message": mismatch, "sent": False})
    unauthorized = message(api, "corr-p", "u", sender="worker:implementation", recipient="conductor")
    put(store, unauthorized["message_id"], {"message": unauthorized, "sent": False})
    legacy = message(api, "corr-l", "l")
    put(store, legacy["message_id"], {"message": legacy, "sent": True})
    api.advance(1)
    out["global_1"] = attempt(relay, store, api.org, Bus(api, published), 100, audit, None)
    api.advance(1)
    out["global_2"] = attempt(relay, store, api.org, Bus(api, published), 100, audit, None)

    # retries: delivery error, transport changed, then success; an unexpected error re-raises after commit
    retry = queue(api, store, "corr-r", "r")
    changed = queue(api, store, "corr-r", "c")
    boom = queue(api, store, "corr-r", "b")
    plan = {retry["message_id"]: ["delivery"], changed["message_id"]: ["changed"], boom["message_id"]: ["boom"]}
    api.advance(1)
    out["failures"] = attempt(relay, store, api.org, Bus(api, published, plan), 100, audit, "corr-r")
    api.advance(1)
    out["after_failures"] = attempt(relay, store, api.org, Bus(api, published, plan), 100, audit, "corr-r")
    api.advance(1)
    out["after_failures_2"] = attempt(relay, store, api.org, Bus(api, published, plan), 100, audit, "corr-r")

    # changed content under an attempted identity; an already delivered entry
    reused = queue(api, store, "corr-i", "i")
    out["reuse_first"] = attempt(relay, store, api.org, Bus(api, published, {reused["message_id"]: ["delivery"]}),
                                 100, audit, "corr-i")
    rewritten = copy.deepcopy(reused)
    rewritten["what"]["details"] = {"plan": {"objective": "rewritten"}}
    put(store, reused["message_id"], {"message": rewritten, "sent": False})
    api.advance(1)
    out["reuse_changed"] = attempt(relay, store, api.org, Bus(api, published), 100, audit, "corr-i")
    delivered = queue(api, store, "corr-d", "d")
    with store.transaction() as tx:
        tx.put("outbox_delivery", delivered["message_id"], {"id": delivered["message_id"], "status": "publishing",
                                                            "delivered_entry_id": "entry-earlier", "attempts": 1})
    out["already_delivered"] = attempt(relay, store, api.org, Bus(api, published), 100, audit, "corr-d")

    # scoped batch: only its own correlation; a failing record leaves it incomplete
    for i in range(2):
        queue(api, store, "corr-s", "s" + str(i))
    queue(api, store, "corr-f", "f")
    out["scoped"] = attempt(relay, store, api.org, Bus(api, published), 100, audit, "corr-s")
    stuck = queue(api, store, "corr-s", "s-stuck")
    out["scoped_incomplete"] = attempt(relay, store, api.org,
                                       Bus(api, published, {stuck["message_id"]: ["delivery"]}), 100, audit, "corr-s")
    out["scoped_limit"] = attempt(relay, store, api.org, Bus(api, published), 1, audit, "corr-f")

    # route pins
    route = {"scope": "run", "run_id": "run-1", "namespace": "ns-1"}
    other = {"scope": "run", "run_id": "run-2", "namespace": "ns-2"}
    with store.transaction() as tx:
        api.pin_route(tx, "corr-pin", route, "2026-01-01T00:00:00+00:00")
    out["pin_same"] = attempt(lambda: _pin(store, api, "corr-pin", route))
    out["pin_conflict"] = attempt(lambda: _pin(store, api, "corr-pin", other))
    out["pin_invalid"] = attempt(lambda: _pin(store, api, "corr-bad", {"scope": "run", "run_id": "", "namespace": "n"}))
    queue(api, store, "corr-pin", "pinned")
    out["pin_global_bus"] = attempt(relay, store, api.org, Bus(api, published), 100, audit, "corr-pin")
    out["pin_other_route"] = attempt(relay, store, api.org, Bus(api, published, route=other, namespace="ns-2"),
                                     100, audit, "corr-pin")
    out["pin_route_namespace_mismatch"] = attempt(relay, store, api.org,
                                                  Bus(api, published, route=route, namespace="ns-x"), 100, audit,
                                                  "corr-pin")
    out["pin_matching_route"] = attempt(relay, store, api.org, Bus(api, published, route=route, namespace="ns-1"),
                                        100, audit, "corr-pin")
    with store.transaction() as tx:
        tx.put("outbox_routes", "corr-malformed", {"id": "corr-malformed", "schema": "urn:other"})
        tx.put("autonomous_runs", "run-x", {"id": "run-x", "correlation_id": "autonomous:run-x",
                                            "bus": {"scope": "run"}})
    queue(api, store, "corr-malformed", "malformed")
    out["pin_malformed"] = attempt(relay, store, api.org, Bus(api, published), 100, audit, "corr-malformed")
    queue(api, store, "autonomous:run-x", "scoped-run", sender="conductor", recipient="lead:improvement")
    out["known_scoped_without_pin"] = attempt(relay, store, api.org, Bus(api, published), 100, audit,
                                              "autonomous:run-x")

    # transport binding
    identity = {"schema": "urn:fixture:transport:1", "endpoint_sha256": "e" * 64, "namespace": "ns"}
    bound_bus = BoundBus(api, published, identity)
    queue(api, store, "corr-b", "bound")
    out["bound"] = attempt(relay, store, api.org, bound_bus, 100, audit, "corr-b")
    out["bound_bindings"] = [canonical_digest(b) if b is not None else None for b in bound_bus.bindings]
    queue(api, store, "corr-u", "unbound")
    out["identity_unavailable"] = attempt(relay, store, api.org, BoundBus(api, published, identity, True), 100,
                                          audit, "corr-u")

    # arguments
    out["limit_zero"] = attempt(relay, store, api.org, Bus(api, published), 0, audit, None)
    out["limit_high"] = attempt(relay, store, api.org, Bus(api, published), 1001, audit, None)
    out["empty_scope"] = attempt(relay, store, api.org, Bus(api, published), 10, audit, " ")

    out["published"] = list(published)
    out["audits"] = audits
    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out


def _pin(store, api, correlation, route):
    with store.transaction() as tx:
        api.pin_route(tx, correlation, route, "2026-01-02T00:00:00+00:00")
    return "pinned"
