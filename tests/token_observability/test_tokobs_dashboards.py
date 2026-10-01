"""ACCEPTANCE A54 (W1): a deterministic lint of the static provider-window panel mapping.

This lints `dashboards/provider-windows.json`, a file only: it does not install or run Grafana (A25-A30, A55-A57
stay W2). The collector's one-hot state test (`test_tokobs_windows.py`) is collector evidence, not dashboard evidence.
"""

import json
import re
from pathlib import Path

from tokobs.vocab import WINDOW_STATES

PATH = Path(__file__).resolve().parents[2] / "tools" / "token_observability" / "dashboards" / "provider-windows.json"
ALLOWED_METRIC_PREFIX = "zeus_llm_provider_"
METRIC = re.compile(r"\b(zeus_[a-z0-9_]+)")


def panels():
    return json.loads(PATH.read_text())["panels"]


def state_panels():
    return [p for p in panels() if p["title"].startswith("Window state ")]


def exprs(panel):
    return [target["expr"] for target in panel["targets"]]


def test_a54_each_window_has_a_state_panel_and_a_utilization_panel():
    windows = {p["title"].split()[-1] for p in state_panels()}
    assert windows == {"five_hour", "seven_day"}
    assert {p["title"].split()[-1] for p in panels() if p["title"].startswith("Window utilization ")} == windows


def test_a54_the_four_states_map_to_distinct_values_texts_and_colors():
    for panel in state_panels():
        (mapping,) = panel["fieldConfig"]["defaults"]["mappings"]
        options = mapping["options"]
        assert len(options) == len(WINDOW_STATES) == 4
        assert len({o["text"] for o in options.values()}) == 4  # four different labels
        assert len({o["color"] for o in options.values()}) == 4  # four different colors
        assert len({o["index"] for o in options.values()}) == 4
        # each mapped value is produced by exactly one state selector of the collector's one-hot gauge
        expression = " ".join(exprs(panel))
        weights = {state: re.search(rf'state="{state}"\}}\) \* (\d+)', expression) for state in WINDOW_STATES}
        assert all(weights.values()), expression
        assert {int(m.group(1)) for m in weights.values()} == {int(key) for key in options}
        assert panel["fieldConfig"]["defaults"]["noValue"] == "No data"  # never shown as 0
        lowered = {o["text"].lower() for o in options.values()}
        assert any(t.startswith("current") for t in lowered) and any(t.startswith("stale") for t in lowered)
        assert any(t.startswith("expired") for t in lowered) and any(t.startswith("unavailable") for t in lowered)


def test_a54_no_token_consumption_metric_in_the_window_panels():
    for panel in panels():
        for expression in exprs(panel):
            used = set(METRIC.findall(expression))
            assert used and all(name.startswith(ALLOWED_METRIC_PREFIX) for name in used), (panel["title"], used)
            assert "token" not in expression.lower()
        assert "not derived from token counts" in panel["description"]


def test_a54_utilization_is_selected_only_for_current_and_stale_windows():
    for panel in panels():
        if panel["title"].startswith("Window utilization "):
            utilization = [e for e in exprs(panel) if "zeus_llm_provider_utilization_ratio" in e]
            assert utilization and all('freshness=~"current|stale"' in e for e in utilization)


def test_a54_the_mapping_names_exactly_the_collectors_window_states():
    assert set(WINDOW_STATES) == {"current", "stale", "expired", "unavailable"}
    for panel in state_panels():
        expression = " ".join(exprs(panel))
        assert set(re.findall(r'state="([a-z]+)"', expression)) == set(WINDOW_STATES)
