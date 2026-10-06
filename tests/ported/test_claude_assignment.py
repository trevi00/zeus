# Ported from SOURCE M7 tests/test_claude_assignment.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
"""U002 C01: who may run an assignment, and what is refused before anything spawns.

The packaged policy says what a provider MAY run; the host configuration says what is enabled.
Neither the assignment message nor a model's output appears anywhere in this decision, a pairing
the packaged policy does not permit refuses the whole configuration, and a permitted pairing with
a missing control refuses the execution instead of quietly handing it to the default provider.
"""
import copy
import json

import pytest

from codex_harness.composition.configuration import settings
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest
from codex_harness.routing.adapters.provider_policy import (
    POLICY_FILE,
    ExecutionPolicy,
    host_policy,
    packaged_policy,
)
from codex_harness.routing.domain.model_selection import DESIGN_MODEL, select_model
from codex_harness.routing.domain.providers import parse_configuration, parse_policy, select_execution

ENABLED = {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement",
           "ZEUS_CLAUDE_MODEL": "claude-fable-5-1", "ZEUS_CLAUDE_MAX_BUDGET_USD": "1"}
IMPLEMENT = {"role": "worker:implementation", "action": "implement",
             "workload": "implementation", "read_only": False}
DESIGN_PAIRS = (("lead:research", "dge_role"), ("lead:improvement", "dge_role"), ("conductor", "dge_role"),
                ("lead:researcher", "dge_role"), ("lead:proposer", "dge_role"), ("lead:arbiter", "dge_role"),
                ("lead:frontdesk", "frontdesk"), ("lead:improvement", "plan"))
ALL_ENABLED = {**ENABLED, "ZEUS_CLAUDE_ASSIGNMENTS": ",".join(
    ["worker:implementation/implement", *(f"{role}/{action}" for role, action in DESIGN_PAIRS)])}


def policy():
    return packaged_policy()


def decide(settings, **overrides):
    parsed = policy()
    return select_execution(parsed, parse_configuration(parsed, settings), **{**IMPLEMENT, **overrides})


# ---- the packaged policy keeps Codex the default -------------------------------------------------

def test_the_packaged_policy_defaults_to_codex_and_permits_one_pairing():
    parsed = policy()
    assert parsed.default_provider == "codex"
    assert parsed.provider("codex").identity == "codex-app-server"
    assert parsed.provider("claude").session_resume == "unsupported"
    # The writable worker pair plus exactly the eight read-only design pairs (responsibility routing).
    assert parsed.permitted_pairs("claude") == {("worker:implementation", "implement"), *DESIGN_PAIRS}
    assert not parsed.permits("claude", role="lead:improvement", action="plan",
                              workload="design", read_only=False)
    assert not parsed.permits("claude", role="worker:implementation", action="implement",
                              workload="implementation", read_only=True), "reviews are not assigned"


@pytest.mark.parametrize("settings", [{}, {"ZEUS_CLAUDE_ASSIGNMENTS": ""}])
def test_without_host_enablement_every_assignment_stays_on_codex(settings):
    for role, action, workload in (("worker:implementation", "implement", "implementation"),
                                   ("lead:improvement", "plan", "design"),
                                   ("worker:geeknews", "research", "design")):
        chosen = decide(settings, role=role, action=action, workload=workload)
        assert chosen.provider == "codex" and chosen.selected_by == "packaged_default"
        assert chosen.transport == "app_server" and chosen.configured_model is None


def test_an_enabled_and_permitted_pairing_runs_on_claude_with_its_controls():
    chosen = decide(ENABLED)
    assert chosen.provider == "claude" and chosen.identity == "claude-code-cli"
    assert chosen.transport == "claude_cli" and chosen.selected_by == "host_configuration"
    assert chosen.configured_model == "claude-fable-5-1"
    assert chosen.controls["max_budget_usd"] == 1.0
    assert chosen.session_resume == "unsupported"
    receipt = chosen.receipt()
    assert receipt["policy_version"] == "provider-policy.v1"
    assert receipt["policy_digest"] and receipt["config_digest"]
    assert "claude-fable-5-1" not in str(receipt), "the receipt binds the configuration by digest"


def test_only_the_enabled_pairing_moves_and_the_rest_stay_on_codex():
    assert decide(ENABLED, role="worker:implementation", action="rebase").provider == "codex"
    assert decide(ENABLED, role="lead:improvement", action="plan", workload="design").provider == "codex"
    assert decide(ENABLED, action=None, workload="final_validation").provider == "codex"


# ---- refusals, all of them before anything is started ---------------------------------------------

def test_a_pairing_the_packaged_policy_does_not_permit_refuses_the_configuration():
    for pairing in ("lead:dba/dge_role", "worker:implementation/review_lead", "conductor/deploy"):
        with pytest.raises(ContractError, match="does not permit"):
            decide({**ENABLED, "ZEUS_CLAUDE_ASSIGNMENTS": pairing})
    with pytest.raises(ContractError, match="'<role>/<action>'"):
        decide({**ENABLED, "ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation"})


def test_an_enabled_provider_without_its_required_controls_refuses_rather_than_using_codex():
    for missing in ("ZEUS_CLAUDE_MODEL", "ZEUS_CLAUDE_MAX_BUDGET_USD"):
        settings = {key: value for key, value in ENABLED.items() if key != missing}
        with pytest.raises(ContractError) as refusal:
            decide(settings)
        assert missing in str(refusal.value)
        assert "codex" not in str(refusal.value).lower(), "a refusal never names a substitute provider"


def test_a_model_that_is_not_this_providers_model_is_refused():
    for model in (DESIGN_MODEL, "gpt-5.6-sol", "gpt-4", "", "   "):
        with pytest.raises(ContractError):
            decide({**ENABLED, "ZEUS_CLAUDE_MODEL": model})
    # A real Claude model name and the documented aliases are accepted.
    for model in ("claude-fable-5-1", "claude-opus-5", "sonnet", "haiku", "fable"):
        assert decide({**ENABLED, "ZEUS_CLAUDE_MODEL": model}).configured_model == model


@pytest.mark.parametrize("budget", ["0", "-1", "100", "abc", "nan"])
def test_a_spend_ceiling_outside_the_packaged_range_is_refused(budget):
    with pytest.raises((ContractError, ValueError)):
        decide({**ENABLED, "ZEUS_CLAUDE_MAX_BUDGET_USD": budget})


def test_an_enabled_pairing_used_with_the_wrong_shape_is_refused_not_redirected():
    with pytest.raises(ContractError, match="does not permit it as"):
        decide(ENABLED, read_only=True)
    with pytest.raises(ContractError, match="does not permit it as"):
        decide(ENABLED, workload="design")


def test_the_configuration_cannot_enable_two_providers_for_one_assignment():
    document = {
        "version": "provider-policy.v1", "default_provider": "codex",
        "providers": {
            "codex": {"identity": "codex-app-server", "transport": "app_server",
                      "model_source": "model_routing", "session_resume": "supported"},
            "claude": {"identity": "claude-code-cli", "transport": "claude_cli",
                       "model_source": "explicit_setting", "session_resume": "unsupported",
                       "enable_setting": "ZEUS_CLAUDE_ASSIGNMENTS", "model_setting": "ZEUS_CLAUDE_MODEL"},
            "other": {"identity": "other-cli", "transport": "claude_cli",
                      "model_source": "explicit_setting", "session_resume": "unsupported",
                      "enable_setting": "ZEUS_OTHER_ASSIGNMENTS", "model_setting": "ZEUS_OTHER_MODEL"},
        },
        "assignments": [
            {"provider": "claude", "roles": ["worker:implementation"], "actions": ["implement"],
             "workloads": ["implementation"], "read_only": False},
            {"provider": "other", "roles": ["worker:implementation"], "actions": ["implement"],
             "workloads": ["implementation"], "read_only": False},
        ],
    }
    parsed = parse_policy(document)
    settings = {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement",
                "ZEUS_CLAUDE_MODEL": "claude-fable-5-1",
                "ZEUS_OTHER_ASSIGNMENTS": "worker:implementation/implement",
                "ZEUS_OTHER_MODEL": "other-model"}
    with pytest.raises(ContractError, match="Two providers are enabled"):
        select_execution(parsed, parse_configuration(parsed, settings), **IMPLEMENT)


def test_a_policy_document_that_is_not_the_expected_shape_is_refused():
    for document in ({}, {"version": "other"}, {"version": "provider-policy.v1"},
                     {"version": "provider-policy.v1", "default_provider": "missing", "providers": {}}):
        with pytest.raises(ContractError):
            parse_policy(document)


# ---- INV-CLAUDE-WORKER-001 responsibility routing: read-only design pairs ------------------------

def packaged_document() -> dict:
    return json.loads(POLICY_FILE.read_text(encoding="utf-8"))


def _overlay_variants():
    good = packaged_document()["providers"]["claude"]["read_only_runtime"]
    without = lambda key: {k: v for k, v in good.items() if k != key}  # noqa: E731
    return [
        ("null", None), ("empty", {}), ("list", ["Read"]),
        ("missing_restricted", without("restricted")), ("missing_denies", without("disallowed_tools")),
        ("extra_key", {**good, "hooks": {}}),
        ("tools_not_list", {**good, "tools": "Read"}), ("empty_tools", {**good, "tools": []}),
        ("empty_allowed", {**good, "allowed_tools": []}), ("non_string_tool", {**good, "tools": ["Read", 1]}),
        *[(f"exposes_{tool}", {**good, "tools": [*good["tools"], tool]})
          for tool in ("Bash", "Edit", "Write", "NotebookEdit")],
        *[(f"allows_{tool}", {**good, "allowed_tools": [*good["allowed_tools"], tool]})
          for tool in ("Bash", "Edit", "Write", "NotebookEdit")],
        ("wildcard_grant", {**good, "allowed_tools": ["Read(*)"]}), ("star_grant", {**good, "tools": ["*"]}),
        ("allowed_not_exposed", {**good, "tools": ["Read"], "allowed_tools": ["Read", "Grep"]}),
        *[(f"undenied_{tool}", {**good, "disallowed_tools": [t for t in good["disallowed_tools"] if t != tool]})
          for tool in ("Bash", "Edit", "Write", "NotebookEdit")],
        *[(f"mode_{mode}", {**good, "permission_mode": mode})
          for mode in ("auto", "acceptEdits", "bypassPermissions", "plan", "unknown", None)],
        ("restricted_false", {**good, "restricted": False}), ("restricted_truthy", {**good, "restricted": 1}),
    ]


@pytest.mark.parametrize("name,overlay", _overlay_variants(), ids=[name for name, _ in _overlay_variants()])
def test_read_only_overlay_is_strict_and_required_for_read_only_rules(name, overlay):
    document = packaged_document()
    document["providers"]["claude"]["read_only_runtime"] = overlay
    with pytest.raises(ContractError):
        parse_policy(document)
    # Present-but-invalid never counts as absent: the same overlay refuses even where no read-only rule
    # would have required one.
    without_rules = packaged_document()
    without_rules["providers"]["claude"]["read_only_runtime"] = overlay
    without_rules["assignments"] = [rule for rule in without_rules["assignments"] if not rule["read_only"]]
    with pytest.raises(ContractError):
        parse_policy(without_rules)
    # Absent overlay: the writable rule alone still parses, the read-only design rules do not.
    absent = packaged_document()
    del absent["providers"]["claude"]["read_only_runtime"]
    with pytest.raises(ContractError, match="read_only_runtime"):
        parse_policy(absent)
    absent["assignments"] = [rule for rule in absent["assignments"] if not rule["read_only"]]
    assert parse_policy(absent).provider("claude").read_only_runtime is None


def test_read_only_overlay_is_copy_only_and_receipted():
    parsed = policy()
    claude = parsed.provider("claude")
    base = copy.deepcopy(claude.runtime)
    configuration = parse_configuration(parsed, ALL_ENABLED)
    chosen = select_execution(parsed, configuration, role="lead:improvement", action="plan",
                              workload="design", read_only=True)
    assert chosen.provider == "claude"
    assert chosen.runtime["restricted"] is True and chosen.runtime["permission_mode"] == "dontAsk"
    assert chosen.runtime["tools"] == ["Read", "Glob", "Grep"] == chosen.runtime["allowed_tools"]
    assert {"Bash", "Edit", "Write", "NotebookEdit"} <= set(chosen.runtime["disallowed_tools"])
    assert chosen.runtime["permission_prompts"] == "none", "base keys outside the overlay are kept"
    receipt = chosen.receipt()
    assert receipt["read_only_profile_applied"] is True
    assert receipt["read_only_profile_digest"] == digest(claude.read_only_runtime)
    chosen.runtime["tools"].append("Bash")
    assert claude.runtime == base and claude.runtime["restricted"] is False, "Provider.runtime is never mutated"
    assert claude.read_only_runtime["tools"] == ["Read", "Glob", "Grep"]
    # The writable run keeps the base runtime and its exact receipt shape.
    writable = select_execution(parsed, configuration, **IMPLEMENT)
    assert writable.runtime == base
    assert "read_only_profile_applied" not in writable.receipt()
    assert "read_only_profile_digest" not in writable.receipt()
    assert set(writable.receipt()) == set(decide(ENABLED).receipt())


@pytest.mark.parametrize("role,action", DESIGN_PAIRS)
def test_design_read_only_assignment_matrix(role, action):
    shape = {"role": role, "action": action, "workload": "design", "read_only": True}
    assert decide({}, **shape).provider == "codex", "listed but not enabled stays on Codex"
    chosen = decide(ALL_ENABLED, **shape)
    assert chosen.provider == "claude" and chosen.selected_by == "host_configuration"
    assert chosen.runtime["restricted"] is True and chosen.receipt()["read_only_profile_applied"] is True
    for wrong in ({"read_only": False}, {"workload": "implementation"}, {"workload": "final_validation"}):
        with pytest.raises(ContractError, match="does not permit it as"):
            decide(ALL_ENABLED, **{**shape, **wrong})


@pytest.mark.parametrize("role,action,workload", [
    ("lead:dba", "dge_role", "design"), ("lead:attacker", "dge_role", "design"),
    ("lead:frontdesk", "dge_role", "design"), ("lead:improvement", None, "final_validation"),
    ("conductor", None, "final_validation"), ("lead:improvement", None, "design"),
    ("worker:github", "research", "design"), ("worker:geeknews", "research", "design"),
])
def test_state_correctness_review_and_research_roles_stay_on_codex(role, action, workload):
    chosen = decide(ALL_ENABLED, role=role, action=action, workload=workload, read_only=True)
    assert chosen.provider == "codex" and chosen.selected_by == "packaged_default"
    assert "read_only_profile_applied" not in chosen.receipt()


@pytest.mark.parametrize("pairing", ["lead:dba/dge_role", "lead:attacker/dge_role", "worker:geeknews/research",
                                     "worker:github/research", "conductor/review_conductor",
                                     "lead:frontdesk/plan", "lead:improvement/review_lead"])
def test_enabling_an_unlisted_design_pair_is_refused(pairing):
    with pytest.raises(ContractError, match="does not permit"):
        decide({**ALL_ENABLED, "ZEUS_CLAUDE_ASSIGNMENTS": ALL_ENABLED["ZEUS_CLAUDE_ASSIGNMENTS"] + "," + pairing})


# ---- C04: the model axes stay separate ------------------------------------------------------------

def test_codex_routing_is_unchanged_and_never_names_the_other_providers_model():
    for importance in (None, "simple", "important", "unknown"):
        assert select_model("implementation", importance).requested_model == DESIGN_MODEL
    assert select_model("design").requested_model == DESIGN_MODEL
    chosen = decide(ENABLED)
    assert chosen.model_source == "explicit_setting"
    assert chosen.configured_model != DESIGN_MODEL
    # Nothing derives the configured model: removing the setting refuses instead of guessing one.
    with pytest.raises(ContractError, match="never derived"):
        decide({key: value for key, value in ENABLED.items() if key != "ZEUS_CLAUDE_MODEL"})


def test_the_host_policy_summary_reports_enablement_without_reprinting_configuration():
    bound = ExecutionPolicy(policy(), parse_configuration(policy(), ENABLED))
    summary = bound.summary()
    assert summary["default_provider"] == "codex"
    assert summary["enabled"]["claude"]["pairs"] == ["worker:implementation/implement"]
    assert summary["enabled"]["claude"]["controls"] == ["max_budget_usd"]
    assert summary["policy_digest"] and summary["config_digest"]


def test_the_host_policy_reads_the_packaged_file_and_the_process_settings(monkeypatch):
    for key, value in ENABLED.items():
        monkeypatch.setenv(key, value)
    # S11 M B3: M7 host_policy() read settings() itself; the target host_policy(values) takes the settings read once by
    # composition (routing.adapters.provider_policy), so the test passes the same process settings explicitly.
    bound = host_policy(settings())
    assert bound.select(**IMPLEMENT).provider == "claude"
    assert bound.select(**{**IMPLEMENT, "action": "plan"}).provider == "codex"
    monkeypatch.delenv("ZEUS_CLAUDE_ASSIGNMENTS")
    assert host_policy(settings()).select(**IMPLEMENT).provider == "codex"  # S11 M B3: as above
