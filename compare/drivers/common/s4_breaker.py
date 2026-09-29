"""Shared S4 scenario steps (`coordination.breaker`): the Breaker that RunTask admits and reports every provider
invocation through (M7 `application/breaker.py`, moved ahead under Option A).

Layer: harness (never shipped)

`api.breaker(store, policy=None)` is the side's Breaker (a scripted clock for the wall-clock fields it records);
`api.reset()` resets the scripted clock and ids. Values/refusals, the inspections, the result mappings and the
store's final records (by body digest) are compared.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


class DownStore:
    """A store whose transactions cannot be opened."""

    def transaction(self):
        raise RuntimeError("down")


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def at(seconds):
    return BASE + timedelta(seconds=seconds)


def lease(i):
    return {"id": f"t{i}", "generation": 1, "attempt": 1, "lease_owner": f"o{i}"}


def run(api) -> dict:
    api.reset()
    out = {}
    out["keys"] = [call(api.breaker_key, "codex", "improvement"), call(api.breaker_key, "Codex!", "x")]
    k = api.breaker_key("codex", "improvement")
    store = api.MemoryStore()
    b = api.breaker(store)
    out["admit_bad_key"] = call(b.admit, "nope", lease(1))
    out["admit_bad_lease"] = call(b.admit, k, {"id": 1})
    tok1 = b.admit(k, lease(1), at(0))
    out["first_admit"] = tok1
    out["first_failure"] = call(b.report, tok1, "failure", at(10))
    tok2 = b.admit(k, lease(2), at(20))
    out["second_failure"] = call(b.report, tok2, "failure", at(25))
    tok3 = b.admit(k, lease(3), at(30))
    out["third_failure_opens"] = call(b.report, tok3, "failure", at(35))
    out["admit_open"] = call(b.admit, k, lease(4), at(40))
    probe = b.admit(k, lease(5), at(200))
    out["probe"] = probe
    out["admit_probe_in_flight"] = call(b.admit, k, lease(6), at(201))
    out["report_stale_generation"] = call(b.report, tok1, "success", at(202))
    out["probe_success_closes"] = call(b.report, probe, "success", at(210))
    reports = []
    for i, s in ((7, 300), (8, 310), (9, 320)):
        token = b.admit(k, lease(i), at(s))
        reports.append(call(b.report, token, "failure", at(s + 10)))
    out["reopen_failures"] = reports
    q = b.admit(k, lease(10), at(500))
    out["probe_failure_opens"] = call(b.report, q, "failure", at(510))
    r = b.admit(k, lease(11), at(700))
    out["probe_unknown_releases"] = call(b.report, r, "unknown", at(705))
    s_token = b.admit(k, lease(12), at(706))
    out["probe_again"] = s_token
    out["probe_expired"] = call(b.report, s_token, "success", at(1100))
    out["inspect"] = call(b.inspect, k, at(1100))
    out["inspect_missing"] = call(b.inspect, "breaker:codex:missing", at(1100))

    k2 = api.breaker_key("claude", "x")
    with store.transaction() as tx:
        tx.put("breakers", k2, {"bad": True})
    out["corrupt_admit"] = [call(b.admit, k2, lease(13), at(0)), call(b.admit, k2, lease(13), at(0))]
    out["corrupt_inspect"] = call(b.inspect, k2, at(0))

    out["unreadable_inspect"] = call(api.breaker(DownStore()).inspect, k, at(0))

    out["update_policy"] = call(b.update_policy, {**api.DEFAULT_POLICY, "failure_threshold": 2}, revision="r2")
    # M7 refuses the spec's "r2" revision (not a commit hash), so the applied path is also recorded, harness-only.
    out["update_policy_applied"] = call(b.update_policy, {**api.DEFAULT_POLICY, "failure_threshold": 2},
                                        revision="a" * 40)
    out["update_policy_refused"] = call(b.update_policy, {"version": 1}, revision="r3")

    out["result_of"] = [
        call(api.result_of, value) for value in (
            None, {"failure": {"cause": "codex-provider-usage-limit-exceeded"}},
            {"failure": {"cause": "output-invalid"}}, {"inspection_blocked": True, "answer": 1},
            {"interrupted": True, "answer": 1}, {"answer": None}, {"answer": {"x": 1}})]
    out["result_of_exception"] = [
        call(api.result_of_exception, error) for error in (
            api.ContractError("Codex turn execution budget exceeded"), api.ContractError("other"),
            RuntimeError("Codex"))]

    with store.transaction() as tx:
        rows = tx.records()
        events = sum(1 for row in rows if row["bucket"] == "breaker_events")
    out["records"] = sorted([r_["bucket"], r_["id"], canonical_digest(r_["body"])] for r_ in rows)
    out["event_count"] = events
    return out
