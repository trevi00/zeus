"""U002 C01: who may run an assignment, and what is refused before anything spawns.

The packaged policy says what a provider MAY run; the host configuration says what is enabled.
Neither the assignment message nor a model's output appears anywhere in this decision, a pairing
the packaged policy does not permit refuses the whole configuration, and a permitted pairing with
a missing control refuses the execution instead of quietly handing it to the default provider.
"""
import pytest

from codex_harness.adapters.providers import ExecutionPolicy, host_policy, packaged_policy
from codex_harness.domain.model import ContractError
from codex_harness.domain.model_routing import DESIGN_MODEL, select_model
from codex_harness.domain.providers import parse_configuration, parse_policy, select_execution

ENABLED = {"ZEUS_CLAUDE_ASSIGNMENTS": "worker:implementation/implement",
           "ZEUS_CLAUDE_MODEL": "claude-fable-5-1", "ZEUS_CLAUDE_MAX_BUDGET_USD": "1"}
IMPLEMENT = {"role": "worker:implementation", "action": "implement",
             "workload": "implementation", "read_only": False}


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
    assert parsed.permitted_pairs("claude") == {("worker:implementation", "implement")}
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
    for pairing in ("lead:improvement/plan", "worker:implementation/review_lead", "conductor/deploy"):
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
    bound = host_policy()
    assert bound.select(**IMPLEMENT).provider == "claude"
    assert bound.select(**{**IMPLEMENT, "action": "plan"}).provider == "codex"
    monkeypatch.delenv("ZEUS_CLAUDE_ASSIGNMENTS")
    assert host_policy().select(**IMPLEMENT).provider == "codex"
