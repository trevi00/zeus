"""Scenario body `kernel.values` (REBUILD-DESIGN-v2 §5.3 S1: message digest/identity).

Layer: harness (never shipped). `api` provides: canonical, digest, envelope, validate_message,
ContractError, ExecutionFailure, require, usage (the usage-policy module), POLICY.
`envelope` is bound by the driver to the scripted clock/id source (reference: patched stdlib in
the driver process; target: injected Clock/IdSource ports).
"""

from __future__ import annotations

import copy

from s1_common import outcome

VECTORS = [
    {"b": 1, "a": [1, 2, {"z": None, "y": "é"}]},
    [],
    "text",
    1.5,
    {"한": "글", "n": -0.0, "t": True},
    {"nested": {"k": [{"x": 1}, {"x": 2}]}, "empty": {}},
]


def run(api, clock, ids) -> dict:
    out: dict = {}
    out["canonical"] = [api.canonical(v) for v in VECTORS]
    out["digest"] = [api.digest(v) for v in VECTORS]

    clock.reset()
    ids.reset()
    first = api.envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                         {"evidence_refs": ["sha256:" + "0" * 64], "n": 1}, "correlation-1")
    clock.advance(1.5)
    second = api.envelope("task.result", "worker:implementation", "lead:improvement", "report", {},
                          "correlation-1", cause=first["message_id"])
    out["envelopes"] = [first, second]
    out["envelope_digests"] = [api.digest(first), api.digest(second)]
    out["message_ids_distinct"] = first["message_id"] != second["message_id"]

    valid = copy.deepcopy(first)
    cases = {"valid": valid}
    missing = copy.deepcopy(first)
    del missing["why"]
    cases["missing_why"] = missing
    bad_type = copy.deepcopy(first)
    bad_type["type"] = "task.unknown"
    cases["unknown_type"] = bad_type
    bad_id = copy.deepcopy(first)
    bad_id["message_id"] = "not-a-uuid"
    cases["malformed_message_id"] = bad_id
    extra = copy.deepcopy(first)
    extra["unexpected"] = 1
    cases["additional_property"] = extra
    wrong_version = copy.deepcopy(first)
    wrong_version["schema_version"] = "2.0"
    cases["schema_version"] = wrong_version
    not_object = copy.deepcopy(first)
    not_object["what"] = "text"
    cases["what_not_object"] = not_object
    out["validate_message"] = {}
    for name, message in cases.items():
        result = outcome(lambda m=message: api.validate_message(m))
        if "ok" in result:
            result = {"ok": result["ok"] == message}
        out["validate_message"][name] = result

    out["require"] = [outcome(lambda: api.require(True, "never")),
                      outcome(lambda: api.require(False, "Declared contract reason"))]
    out["contract_error_is_value_error"] = issubclass(api.ContractError, ValueError)
    failure = api.ExecutionFailure("runner_timeout", {"seconds": 5})
    out["execution_failure"] = {"cause": failure.cause, "evidence": failure.evidence, "text": str(failure),
                                "is_runtime_error": isinstance(failure, RuntimeError)}

    usage = api.usage
    budgets = [
        {"per_host": 2, "total": 5}, {"per_host": 2, "total": 5, "mode": "finite"},
        {"per_host": 2, "total": 5, "mode": "subscription"}, {"per_host": 0, "total": 5},
        {"per_host": 3, "total": 2}, {"per_host": True, "total": 5}, {"per_host": 2},
        {"per_host": 2, "total": 5, "extra": 1}, {"per_host": 2, "total": 5, "mode": "other"}, "text",
    ]
    out["usage.validate_budget"] = [outcome(lambda b=b: usage.validate_budget(b)) for b in budgets]
    counts = [{"this_host": 1, "all_hosts": 4}, {"this_host": 2, "all_hosts": 3},
              {"this_host": 1, "all_hosts": 1, "unreadable": 0}, {"this_host": 1, "all_hosts": 1, "unreadable": 2},
              {"this_host": "1", "all_hosts": 1}, None]
    out["usage.headroom"] = [
        [outcome(lambda b=b, c=c: usage.headroom(b, c, 1)) for c in counts]
        for b in ({"per_host": 2, "total": 5}, {"per_host": 2, "total": 5, "mode": "subscription"})]
    out["usage.exhausted"] = [outcome(lambda c=c: usage.exhausted({"per_host": 2, "total": 5}, c)) for c in counts]
    out["usage.validate_grant"] = [
        outcome(lambda p=p, r=r: usage.validate_grant(p, r)) for p, r in (
            ({"per_host": 2, "total": 5}, {"per_host": 3, "total": 5}),
            ({"per_host": 2, "total": 5}, {"per_host": 2, "total": 5}),
            ({"per_host": 2, "total": 5}, {"per_host": 1, "total": 5}),
            ({"per_host": 2, "total": 5}, {"per_host": 2, "total": 5, "mode": "subscription"}))]
    out["usage.accounting_mode"] = [outcome(lambda b=b: usage.accounting_mode(b)) for b in budgets]
    out["usage.constants"] = {"FINITE": usage.FINITE, "SUBSCRIPTION": usage.SUBSCRIPTION,
                              "MODES": list(usage.MODES), "FIELDS": sorted(usage.FIELDS)}
    out["usage.error_is_contract_error"] = issubclass(usage.UsagePolicyError, api.ContractError)
    out["policy.snapshot"] = api.POLICY.snapshot()
    return out
