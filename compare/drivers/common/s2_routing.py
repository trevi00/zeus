"""Scenario body `routing.matrix` (REBUILD-DESIGN-v2 §5.3 S2: routing over all packaged agents x
actions x read-only x host enablement; S1 acceptance "S2 entry conditions").

Layer: harness (never shipped); standard library only. `api` provides:
- `organization()`: the packaged organization (validated), `Organization`, `Agent`,
  `conductor_self_arbitration`;
- `providers`: the provider-policy domain module (`parse_policy`, `parse_configuration`,
  `select_execution`, `read_only_profile`, `read_only_runtime_check`, `read_only_settings_check`,
  `read_accounting_mode`, `accounting_mode_setting`);
- `packaged_policy()`, `ExecutionPolicy`, `host_policy(values)` (the packaged policy adapter; the
  host settings mapping is always passed explicitly by this scenario);
- `select_profile(provider, transport, action, read_only, codex_enabled=...)` (role -> container
  profile mapping);
- `select_model(workload, importance)`;
- `ContractError`, `policy_document()` (the packaged providers.json as parsed JSON).

Every selection is recorded as `{"ok": <receipt digest>}` or the refusal type/message; the distinct
receipts are listed once, in full, keyed by their digest. No setting value beyond the fixture model
name and numbers written here is ever read from the host.
"""

from __future__ import annotations

import copy
import hashlib
import json

from s1_common import outcome

ACTIONS = [None, "implement", "dge_role", "frontdesk", "plan", "research", "review", "diagnose"]
WORKLOADS = ["design", "implementation", "final_validation"]
ALL_PAIRS = ("worker:implementation/implement,lead:research/dge_role,lead:improvement/dge_role,"
             "conductor/dge_role,lead:researcher/dge_role,lead:proposer/dge_role,lead:arbiter/dge_role,"
             "lead:frontdesk/frontdesk,lead:improvement/plan")
CONFIGURATIONS = {
    "none": {},
    "claude_all_finite": {"ZEUS_CLAUDE_ASSIGNMENTS": ALL_PAIRS, "ZEUS_CLAUDE_MODEL": "claude-fixture-1",
                          "ZEUS_CLAUDE_MAX_BUDGET_USD": "2.5", "ZEUS_CLAUDE_TIMEOUT_SECONDS": "600"},
    "claude_impl_subscription": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement",
                                 "ZEUS_CLAUDE_MODEL": "sonnet", "ZEUS_CLAUDE_ACCOUNTING_MODE": "subscription"},
    "claude_roles_executable": {"ZEUS_CLAUDE_ASSIGNMENTS": " lead:frontdesk/frontdesk , conductor/dge_role ,",
                                "ZEUS_CLAUDE_MODEL": " opus ", "ZEUS_CLAUDE_MAX_BUDGET_USD": "0.01",
                                "ZEUS_CLAUDE_EXECUTABLE": "/opt/fixture/claude",
                                "ZEUS_CLAUDE_ACCOUNTING_MODE": "finite"},
    "subscription_with_budget": {"ZEUS_CLAUDE_ASSIGNMENTS": "lead:improvement/plan", "ZEUS_CLAUDE_MODEL": "haiku",
                                 "ZEUS_CLAUDE_MAX_BUDGET_USD": "20", "ZEUS_CLAUDE_ACCOUNTING_MODE": "subscription"},
}
INVALID_CONFIGURATIONS = {
    "not_permitted_pair": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:github/research", "ZEUS_CLAUDE_MODEL": "sonnet",
                           "ZEUS_CLAUDE_MAX_BUDGET_USD": "1"},
    "malformed_pair": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker implementation", "ZEUS_CLAUDE_MODEL": "sonnet",
                       "ZEUS_CLAUDE_MAX_BUDGET_USD": "1"},
    "no_pairs": {"ZEUS_CLAUDE_ASSIGNMENTS": " , ,", "ZEUS_CLAUDE_MODEL": "sonnet", "ZEUS_CLAUDE_MAX_BUDGET_USD": "1"},
    "missing_model": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MAX_BUDGET_USD": "1"},
    "bad_model": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MODEL": "gpt-5",
                  "ZEUS_CLAUDE_MAX_BUDGET_USD": "1"},
    "missing_budget": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MODEL": "sonnet"},
    "budget_above_max": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MODEL": "sonnet",
                         "ZEUS_CLAUDE_MAX_BUDGET_USD": "20.5"},
    "budget_not_number": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MODEL": "sonnet",
                          "ZEUS_CLAUDE_MAX_BUDGET_USD": "lots"},
    "budget_infinite": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MODEL": "sonnet",
                        "ZEUS_CLAUDE_MAX_BUDGET_USD": "inf"},
    "timeout_below_min": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MODEL": "sonnet",
                          "ZEUS_CLAUDE_MAX_BUDGET_USD": "1", "ZEUS_CLAUDE_TIMEOUT_SECONDS": "5"},
    "timeout_not_integer": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MODEL": "sonnet",
                            "ZEUS_CLAUDE_MAX_BUDGET_USD": "1", "ZEUS_CLAUDE_TIMEOUT_SECONDS": "60.5"},
    "unknown_accounting": {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MODEL": "sonnet",
                           "ZEUS_CLAUDE_MAX_BUDGET_USD": "1", "ZEUS_CLAUDE_ACCOUNTING_MODE": "unlimited"},
    "settings_not_mapping": None,
}


def sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def policy_negatives(api) -> dict:
    """Packaged-policy parse refusals over single mutations of the SOURCE document."""
    base = api.policy_document()

    def mutate(fn):
        document = copy.deepcopy(base)
        fn(document)
        return outcome(lambda: api.providers.parse_policy(document).policy_digest)

    def drop(path):
        def fn(d):
            node = d
            for key in path[:-1]:
                node = node[key]
            del node[path[-1]]
        return fn

    def put(path, value):
        def fn(d):
            node = d
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
        return fn

    cases = {
        "packaged": lambda d: None,
        "not_object": None,
        "wrong_version": put(["version"], "provider-policy.v0"),
        "no_providers": put(["providers"], {}),
        "bad_provider_name": lambda d: d["providers"].__setitem__("bad name", d["providers"].pop("claude")),
        "unknown_transport": put(["providers", "claude", "transport"], "carrier_pigeon"),
        "unknown_model_source": put(["providers", "claude", "model_source"], "guess"),
        "missing_resume": drop(["providers", "claude", "session_resume"]),
        "bad_enable_setting": put(["providers", "claude", "enable_setting"], "lower_case"),
        "model_setting_mismatch": put(["providers", "codex", "model_setting"], "ZEUS_CODEX_MODEL"),
        "bad_pattern": put(["providers", "claude", "model_pattern"], "(unclosed"),
        "empty_pattern": put(["providers", "claude", "model_pattern"], ""),
        "control_bad_kind": put(["providers", "claude", "controls", "timeout_seconds", "kind"], "float"),
        "control_no_required": drop(["providers", "claude", "controls", "executable", "required"]),
        "runtime_not_object": put(["providers", "claude", "runtime"], []),
        "read_only_null": put(["providers", "claude", "read_only_runtime"], None),
        "read_only_pattern_grant": put(["providers", "claude", "read_only_runtime", "allowed_tools"], ["Read(*)"]),
        "read_only_missing_deny": put(["providers", "claude", "read_only_runtime", "disallowed_tools"], ["Bash"]),
        "read_only_wrong_mode": put(["providers", "claude", "read_only_runtime", "permission_mode"], "default"),
        "read_only_unrestricted": put(["providers", "claude", "read_only_runtime", "restricted"], False),
        "read_only_extra_key": put(["providers", "claude", "read_only_runtime", "hooks"], {}),
        "read_only_rule_without_overlay": drop(["providers", "claude", "read_only_runtime"]),
        "unknown_default": put(["default_provider"], "nobody"),
        "default_enabled_by_host": put(["providers", "codex", "enable_setting"], "ZEUS_CODEX_ASSIGNMENTS"),
        "assignments_not_list": put(["assignments"], {}),
        "assignment_unknown_provider": lambda d: d["assignments"][0].__setitem__("provider", "nobody"),
        "assignment_for_default": lambda d: d["assignments"][0].__setitem__("provider", "codex"),
        "assignment_empty_roles": lambda d: d["assignments"][0].__setitem__("roles", []),
        "assignment_no_read_only": lambda d: d["assignments"][0].pop("read_only"),
    }
    out = {}
    for name, fn in cases.items():
        if fn is None:
            out[name] = outcome(lambda: api.providers.parse_policy([]).policy_digest)
        else:
            out[name] = mutate(fn)
    return out


def profile_checks(api) -> dict:
    policy = api.packaged_policy()
    overlay = policy.provider("claude").read_only_runtime
    runtime = {**overlay, "permission_prompts": "none"}
    return {
        "overlay": overlay,
        "runtime_ok": outcome(lambda: api.providers.read_only_runtime_check(runtime)),
        "runtime_prompts": outcome(lambda: api.providers.read_only_runtime_check({**overlay})),
        "runtime_missing": outcome(lambda: api.providers.read_only_runtime_check({"tools": ["Read"]})),
        "runtime_not_dict": outcome(lambda: api.providers.read_only_runtime_check(None)),
        "settings_ok": outcome(lambda: api.providers.read_only_settings_check(
            {"permissions": {"allow": ["Read"], "deny": list(overlay["disallowed_tools"]),
                             "defaultMode": "dontAsk"}}, overlay)),
        "settings_hooks": outcome(lambda: api.providers.read_only_settings_check(
            {"permissions": {}, "hooks": {}}, overlay)),
        "settings_extra_grant": outcome(lambda: api.providers.read_only_settings_check(
            {"permissions": {"allow": ["Bash"], "deny": list(overlay["disallowed_tools"]),
                             "defaultMode": "dontAsk"}}, overlay)),
        "settings_dropped_deny": outcome(lambda: api.providers.read_only_settings_check(
            {"permissions": {"allow": ["Read"], "deny": ["Bash"], "defaultMode": "dontAsk"}}, overlay)),
        "settings_mode": outcome(lambda: api.providers.read_only_settings_check(
            {"permissions": {"allow": [], "deny": list(overlay["disallowed_tools"]),
                             "defaultMode": "acceptEdits"}}, overlay)),
    }


def selection_matrix(api, agents) -> dict:
    receipts, rows, summaries, profiles, full = {}, {}, {}, {}, {}
    for config_name, settings in CONFIGURATIONS.items():
        policy = api.host_policy(dict(settings))
        summaries[config_name] = policy.summary()
        grid = {}
        for agent in agents:
            for action in ACTIONS:
                for workload in WORKLOADS:
                    for read_only in (False, True):
                        key = f"{agent}|{action}|{workload}|{'ro' if read_only else 'rw'}"

                        def select():
                            receipt = policy.select(role=agent, action=action, workload=workload,
                                                    read_only=read_only).receipt()
                            # The full receipt is bound by its digest; the echoed request fields are
                            # dropped from the listed shape only (the row digest still covers them).
                            shape = {k: v for k, v in receipt.items()
                                     if k not in {"role", "action", "workload", "read_only"}}
                            shape_digest = sha(shape)
                            receipts[shape_digest] = shape
                            full[key] = receipt
                            return [sha(receipt), shape_digest]

                        result = outcome(select)
                        grid[key] = result
                        if "ok" in result:
                            receipt = full[key]
                            for codex_enabled in (True, False):
                                pkey = (f"{receipt['provider']}|{receipt['transport']}|{action}|"
                                        f"{'ro' if read_only else 'rw'}|codex_enabled={codex_enabled}")
                                if pkey not in profiles:
                                    profiles[pkey] = outcome(lambda: api.select_profile(
                                        receipt["provider"], receipt["transport"], action, read_only,
                                        codex_enabled=codex_enabled))
        rows[config_name] = grid
    invalid = {}
    for name, settings in INVALID_CONFIGURATIONS.items():
        invalid[name] = outcome(lambda: api.host_policy(settings if settings is not None else []).summary())
    return {"receipt_shapes": dict(sorted(receipts.items())), "grid": rows, "summaries": summaries,
            "invalid_configurations": invalid, "profiles": dict(sorted(profiles.items()))}


def selection_inputs(api) -> dict:
    policy = api.host_policy({})
    shapes = {
        "empty_role": dict(role="", action=None, workload="design", read_only=False),
        "role_not_str": dict(role=None, action=None, workload="design", read_only=False),
        "empty_action": dict(role="conductor", action="", workload="design", read_only=False),
        "action_not_str": dict(role="conductor", action=7, workload="design", read_only=False),
        "empty_workload": dict(role="conductor", action=None, workload="", read_only=False),
        "read_only_not_bool": dict(role="conductor", action=None, workload="design", read_only=1),
        "unknown_workload_default": dict(role="conductor", action=None, workload="anything", read_only=True),
    }
    out = {name: outcome(lambda: sha(policy.select(**kw).receipt())) for name, kw in shapes.items()}
    enabled = api.host_policy(dict(CONFIGURATIONS["claude_all_finite"]))
    mismatch = {
        "enabled_pair_wrong_workload": dict(role="worker:implementation", action="implement", workload="design",
                                            read_only=False),
        "enabled_pair_wrong_read_only": dict(role="worker:implementation", action="implement",
                                             workload="implementation", read_only=True),
        "enabled_dge_role_rw": dict(role="conductor", action="dge_role", workload="design", read_only=False),
    }
    out.update({name: outcome(lambda: sha(enabled.select(**kw).receipt())) for name, kw in mismatch.items()})
    out["provider_unknown"] = outcome(lambda: enabled.provider("nobody").receipt())
    out["provider_claude"] = outcome(lambda: enabled.provider("claude").receipt())
    # Two providers enabled for the same pairing (a second enabled provider only exists in a mutated policy).
    document = api.policy_document()
    twin = copy.deepcopy(document["providers"]["claude"])
    twin["enable_setting"] = "ZEUS_TWIN_ASSIGNMENTS"
    document["providers"]["twin"] = twin
    document["assignments"].append({**document["assignments"][0], "provider": "twin"})
    parsed = api.providers.parse_policy(document)
    both = {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement", "ZEUS_CLAUDE_MODEL": "sonnet",
            "ZEUS_CLAUDE_MAX_BUDGET_USD": "1", "ZEUS_TWIN_ASSIGNMENTS": "worker:implementation/implement"}
    out["two_providers_enabled"] = outcome(lambda: sha(api.providers.select_execution(
        parsed, api.providers.parse_configuration(parsed, both), role="worker:implementation",
        action="implement", workload="implementation", read_only=False).receipt()))
    out["accounting_setting"] = {name: api.providers.accounting_mode_setting(parsed.provider(name))
                                 for name in sorted(parsed.providers)}
    out["accounting_mode_values"] = {
        value: outcome(lambda: api.providers.read_accounting_mode(
            parsed.provider("claude"), {"ZEUS_CLAUDE_ACCOUNTING_MODE": value}))
        for value in ("", " ", "finite", "subscription", " subscription ", "Finite")}
    return out


def organization_matrix(api) -> dict:
    org = api.organization()
    agents = sorted(org.agents)
    kinds = ["task.assign", "execution.notice", "review.result", "incident.report", "task.result",
             "hook.required", "other.kind"]
    grid = {}
    for sender in agents + ["worker:ghost"]:
        for recipient in agents:
            for kind in kinds:
                action = "observe_execution" if kind == "execution.notice" else "work"
                message = {"type": kind, "who": {"sender": sender, "recipient": recipient, "owner": recipient},
                           "what": {"action": action, "details": {}}}
                result = outcome(lambda: org.authorize(message))
                grid[f"{sender}>{recipient}|{kind}"] = "ok" if "ok" in result else result["message"]
    special = {}
    base = {"who": {"sender": "conductor", "recipient": "conductor", "owner": "conductor"}}
    special["self_dge_assign"] = {"type": "task.assign", **base,
                                  "what": {"action": "dge_role", "details": {"role": "conductor"}}}
    special["self_dge_assign_other_role"] = {"type": "task.assign", **base,
                                             "what": {"action": "dge_role", "details": {"role": "lead"}}}
    special["self_dge_assign_details_not_dict"] = {"type": "task.assign", **base,
                                                   "what": {"action": "dge_role", "details": "conductor"}}
    special["self_dge_result"] = {"type": "task.result", **base, "what": {"action": "dge_role", "details": {}}}
    special["self_other_action"] = {"type": "task.assign", **base, "what": {"action": "plan", "details": {}}}
    special["notice_wrong_action"] = {"type": "execution.notice",
                                      "who": {"sender": "worker:github", "recipient": "lead:research",
                                              "owner": "lead:research"},
                                      "what": {"action": "work", "details": {}}}
    special["notice_conductor_self"] = {"type": "execution.notice", **base,
                                        "what": {"action": "observe_execution", "details": {}}}
    special["unknown_owner"] = {"type": "task.assign",
                                "who": {"sender": "conductor", "recipient": "lead:research", "owner": "ghost"},
                                "what": {"action": "work", "details": {}}}
    out = {"authorize": grid,
           "special": {name: outcome(lambda: org.authorize(m)) for name, m in special.items()},
           "self_arbitration": {name: api.conductor_self_arbitration(m) for name, m in special.items()},
           "self_arbitration_empty": api.conductor_self_arbitration({}),
           "agents": {a: [org.agents[a].role, org.agents[a].parent, org.agents[a].team] for a in agents},
           "actor": {
               "known": outcome(lambda: org.actor("lead:dba", "lead").id),
               "wrong_role": outcome(lambda: org.actor("lead:dba", "worker").id),
               "unknown": outcome(lambda: org.actor("nobody").id)}}
    Agent, Organization = api.Agent, api.Organization

    def build(rows):
        return Organization({a[0]: Agent(*a) for a in rows})

    negatives = {
        "two_conductors": [("c1", "conductor", None, "t"), ("c2", "conductor", None, "t")],
        "no_conductor": [("l", "lead", None, "t")],
        "unknown_role": [("c", "conductor", None, "t"), ("x", "admin", "c", "t")],
        "conductor_parent": [("c", "conductor", "c", "t")],
        "lead_under_lead": [("c", "conductor", None, "t"), ("l", "lead", "c", "t"), ("m", "lead", "l", "t")],
        "worker_other_team": [("c", "conductor", None, "t"), ("l", "lead", "c", "a"), ("w", "worker", "l", "b")],
        "worker_under_conductor": [("c", "conductor", None, "t"), ("w", "worker", "c", "t")],
        "valid": [("c", "conductor", None, "t"), ("l", "lead", "c", "a"), ("w", "worker", "l", "a")],
    }
    out["validate"] = {name: outcome(lambda: build(rows).validate()) for name, rows in negatives.items()}
    key_mismatch = Organization({"x": Agent("c", "conductor", None, "t")})
    out["validate"]["key_mismatch"] = outcome(key_mismatch.validate)
    return out


def model_matrix(api) -> dict:
    out = {}
    for workload in ["design", "implementation", "final_validation", "research", None]:
        for importance in [None, "not_applicable", "simple", "important", "unknown", "critical", 3]:
            out[f"{workload}|{importance}"] = outcome(lambda: api.select_model(workload, importance).receipt())
    return out


def run(api) -> dict:
    agents = sorted(api.organization().agents) + ["worker:unknown"]
    policy = api.packaged_policy()
    return {
        "packaged_policy": {"version": policy.version, "default": policy.default_provider,
                            "digest": policy.policy_digest, "providers": sorted(policy.providers),
                            "assignments": [dict(rule) for rule in policy.assignments],
                            "provider_receipts": {n: p.receipt() for n, p in sorted(policy.providers.items())},
                            "permitted_pairs": sorted(f"{r}/{a}" for r, a in policy.permitted_pairs("claude"))},
        "policy_negatives": policy_negatives(api),
        "read_only_profile": profile_checks(api),
        "selection": selection_matrix(api, agents),
        "selection_inputs": selection_inputs(api),
        "profile_inputs": {
            name: outcome(lambda: api.select_profile(*args, codex_enabled=enabled))
            for name, (args, enabled) in {
                "read_only_int": (("claude", "claude_cli", "implement", 1), True),
                "claude_wrong_transport": (("claude", "app_server", "implement", False), True),
                "codex_rw_review": (("codex", "app_server", "review", False), True),
                "codex_disabled_ro": (("codex", "app_server", None, True), False),
                "unknown_provider": (("other", "claude_cli", "implement", False), True),
            }.items()},
        "organization": organization_matrix(api),
        "model_selection": model_matrix(api),
    }
