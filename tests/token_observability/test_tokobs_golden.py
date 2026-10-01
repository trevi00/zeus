"""Golden files per source (ACCEPTANCE bounded test plan): ledger, data.prom and health.prom per scenario.

The goldens in `golden/<scenario>/` were recorded once from `scenarios.py` and checked by hand against the numbers
asserted below; this test only compares. A mismatch is a regression to explain, never a file to regenerate.
"""

import hashlib
import json
from pathlib import Path

import pytest
from scenarios import SCENARIOS, ledger_snapshot

GOLDEN = Path(__file__).resolve().parent / "golden"


def render_ledger(rig) -> str:
    return json.dumps(ledger_snapshot(rig), indent=1, sort_keys=True) + "\n"


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_matches_its_goldens(tmp_path, name):
    rig = SCENARIOS[name](tmp_path)
    expected = GOLDEN / name
    assert render_ledger(rig) == (expected / "expected_ledger.json").read_text()
    assert (rig.data / "data.prom").read_text() == (expected / "expected_data.prom").read_text()
    assert (rig.data / "health.prom").read_text() == (expected / "expected_health.prom").read_text()


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenarios_are_deterministic(tmp_path, name):
    first = SCENARIOS[name](tmp_path / "one")
    second = SCENARIOS[name](tmp_path / "two")
    digest = lambda rig: hashlib.sha256(  # noqa: E731
        (render_ledger(rig) + (rig.data / "data.prom").read_text() + (rig.data / "health.prom").read_text()).encode()
    ).hexdigest()
    assert digest(first) == digest(second)


def test_routine_scenario_numbers(tmp_path):
    rig = SCENARIOS["routine"](tmp_path)
    prom = rig.series("data")
    out = lambda **labels: prom.sum("zeus_llm_tokens_total", token_type="output", **labels)  # noqa: E731
    assert out(role="implementer") == 100 + 30 and out(role="advisor") == 40  # Σ_m T_m once, per role
    assert out(role="nested_unattributed") == 0
    assert prom.sum("zeus_llm_tokens_total", role="advisor") == 5 + 40 + 200  # Opus T_a, counted once
    assert prom.sum("zeus_llm_invocations_total", outcome="failed") == 1 and prom.sum(
        "zeus_llm_invocations_total", outcome="finished") == 1
    assert prom.sum("zeus_llm_estimated_cost_usd_total", model="claude-opus-5-5") == pytest.approx(0.25)
    assert prom.sum("zeus_llm_estimated_cost_usd_total", model="claude-sonnet-5-5") == pytest.approx(0.75)
    assert prom.sum("zeus_task_outcomes_total", outcome="accepted", first_pass="false") == 1


def test_s2_windows_scenario_numbers(tmp_path):
    rig = SCENARIOS["s2_windows"](tmp_path)
    prom = rig.series("data")
    assert prom.sum("zeus_llm_tokens_total", role="coordinator", token_type="output") == 30  # M only (C-W1-6)
    assert prom.sum("zeus_llm_tokens_total", role="lane_worker", token_type="output") == 8
    assert prom.sum("zeus_llm_tokens_total", role="nested_unattributed", token_type="output") == 7  # 15 - 8
    assert prom.sum("zeus_llm_invocations_total", outcome="terminal_unproven", source="coordinator") == 1
    assert prom.sum("zeus_llm_invocations_total", outcome="finished", source="lane") == 1
    assert prom.sum("zeus_llm_provider_window_state", slot="primary", window="seven_day", state="expired") == 0


def test_codex_scenario_numbers(tmp_path):
    rig = SCENARIOS["codex"](tmp_path)
    prom = rig.series("data")
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 100 + 60 + 90
    assert prom.sum("zeus_llm_tokens_total", token_type="output", task_class="unattributed_interval") == 90
    assert prom.sum("zeus_llm_reasoning_output_tokens_total") == 30 + 10 + 15
