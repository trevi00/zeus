"""ACCEPTANCE A25 (No data, not 0), A27, A28 and the structure of the two provisioned dashboards (W2b, static).

Lints `deploy/observability/grafana/dashboards/*.json` only; it never runs Grafana or Prometheus. Whether every
expression parses on the pinned Prometheus is the owner-run connectivity test (`test_tokobs_conntest.py`, A56).
"""

import ast
import copy
import json
import re
from pathlib import Path

import pytest
import yaml
from tokobs import render

ROOT = Path(__file__).resolve().parents[2]
DASH_DIR = ROOT / "deploy" / "observability" / "grafana" / "dashboards"
RULES = ROOT / "deploy" / "observability" / "prometheus" / "rules" / "tokobs.yml"
WINDOWS = ROOT / "tools" / "token_observability" / "dashboards" / "provider-windows.json"
PROMETHEUS_DS = {"type": "prometheus", "uid": "tokobs-prom"}
NAMES = ("zeus-llm-usage", "zeus-tokobs-health")
NOT_DERIVED = "not derived from token counts"
KEYWORDS = {"by", "without", "on", "ignoring", "group_left", "group_right", "and", "or", "unless", "bool", "offset",
            "inf", "nan"}


def load(name):
    return json.loads((DASH_DIR / f"{name}.json").read_text())


def panels(name):
    return load(name)["panels"]


def queried(panel):
    return [t["expr"] for t in panel.get("targets", [])]


def all_panels():
    return [(name, p) for name in NAMES for p in panels(name)]


def rendered_metrics() -> tuple[set[str], set[str]]:
    """(every metric name tokobs renders, the histogram ones), read from `tokobs.render` itself.

    Data metrics come from a real `build_data` over an empty ledger (its TYPE lines); the health gauges are emitted
    conditionally, so every `zeus_*` string literal of render.py is taken as well."""
    import tempfile

    from tokobs.ledger import open_ledger

    with tempfile.TemporaryDirectory() as tmp:
        ledger = open_ledger(Path(tmp))
        text, _ = render.build_data(ledger)
        ledger.close()
    typed = dict(re.findall(r"^# TYPE (\S+) (\S+)$", text, re.M))
    literals = {n.value for n in ast.walk(ast.parse(Path(render.__file__).read_text()))
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r"zeus_[a-z0-9_]+", n.value)}
    return set(typed) | literals, {n for n, t in typed.items() if t == "histogram"}


def recording_rules() -> set[str]:
    groups = yaml.safe_load(RULES.read_text())["groups"]
    return {r["record"] for g in groups for r in g["rules"] if "record" in r}


def metric_names(expr: str) -> set[str]:
    """Metric names in one PromQL expression: strip strings, label matchers, ranges, grouping clauses, Grafana
    variables and function calls; what is left that is an identifier is a series name."""
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', expr)
    text = re.sub(r"\$\{?\w+\}?", "0", text)
    text = re.sub(r"\{[^}]*\}", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", " ", text, flags=re.I)
    found = set()
    for name, nxt in re.findall(r"([A-Za-z_:][A-Za-z0-9_:]*)(\s*\()?", text):
        if not nxt and name.lower() not in KEYWORDS:
            found.add(name)
    return found


def all_exprs():
    return [(name, p, e) for name, p in all_panels() for e in queried(p)]


# -- structure -----------------------------------------------------------------

def test_dashboards_directory_holds_exactly_the_two_provisioned_files():
    assert sorted(p.name for p in DASH_DIR.glob("*.json")) == ["zeus-llm-usage.json", "zeus-tokobs-health.json"]
    # provider-windows.json stays where W1c's A54 test lints it and is NOT provisioned
    assert WINDOWS.exists() and WINDOWS.parent != DASH_DIR


@pytest.mark.parametrize("name", NAMES)
def test_dashboard_identity_and_datasource(name):
    d = load(name)
    assert d["uid"] == name and d["schemaVersion"] == 39 and d["editable"] is False
    for panel in d["panels"]:
        assert panel["datasource"] == PROMETHEUS_DS, panel["title"]
        for target in panel.get("targets", []):
            assert target["datasource"] == PROMETHEUS_DS, panel["title"]
    for variable in d["templating"]["list"]:
        assert variable["datasource"] == PROMETHEUS_DS
    ids = [p["id"] for p in d["panels"]]
    assert len(ids) == len(set(ids))


def test_usage_variables_are_multi_select_with_all():
    variables = {v["name"]: v for v in load("zeus-llm-usage")["templating"]["list"]}
    assert set(variables) == {"provider", "role", "model", "task_class"}
    for name, v in variables.items():
        assert v["type"] == "query" and v["multi"] is True and v["includeAll"] is True and v["allValue"] == ".*"
        assert re.fullmatch(rf"label_values\(zeus_llm_tokens_total, {name}\)", v["definition"])
        assert v["query"]["query"] == v["definition"]


def test_usage_rows_follow_design_section_6_order():
    rows = [p["title"] for p in panels("zeus-llm-usage") if p["type"] == "row"]
    assert rows == ["Data quality", "Tokens by role and type", "By model", "Provider windows", "Estimated cost",
                    "Task efficiency"]


def test_every_expression_uses_a_rendered_metric_a_recording_rule_or_up():
    rendered, histograms = rendered_metrics()
    allowed = rendered | recording_rules() | {"up"}
    allowed |= {f"{h}{suffix}" for h in histograms for suffix in ("_bucket", "_sum", "_count")}
    assert "zeus_tokobs_last_scan_success_timestamp_seconds" in rendered and histograms == {"zeus_task_elapsed_seconds"}
    seen = set()
    for name, panel, expr in all_exprs():
        used = metric_names(expr)
        assert used, (name, panel["title"], expr)
        assert used <= allowed, (name, panel["title"], sorted(used - allowed))
        seen |= used
    for variable in load("zeus-llm-usage")["templating"]["list"]:
        (metric,) = re.findall(r"label_values\((\w+),", variable["definition"])
        assert metric in allowed
    assert "zeus:llm_unknown_ratio:1d" in seen  # DESIGN 5.1's name, not EFFICIENCY 2's slip
    assert "zeus:llm_usage_unknown_ratio:1d" not in seen


def test_metric_name_extraction_ignores_labels_functions_and_grouping():
    expr = 'sum by (le, model) (increase(zeus_x_total{a=~"$b",c!="zeus_y"}[$__range])) / ignoring(token_type) up'
    assert metric_names(expr) == {"zeus_x_total", "up"}


# -- A25 -------------------------------------------------------------------------

def test_a25_no_vector_zero_and_no_numeric_novalue():
    for name, panel, expr in all_exprs():
        assert "vector(" not in expr.replace(" ", ""), (name, panel["title"])
    for name, panel in all_panels():
        if panel["type"] == "row":
            continue
        defaults = panel["fieldConfig"]["defaults"]
        assert defaults.get("noValue") == "No data", (name, panel["title"])
        assert not isinstance(defaults["noValue"], (int, float))


def test_a25_every_data_quality_panel_says_no_data():
    in_row, checked = False, []
    for panel in panels("zeus-llm-usage"):
        if panel["type"] == "row":
            in_row = panel["title"] == "Data quality"
            continue
        if in_row:
            assert panel["fieldConfig"]["defaults"]["noValue"] == "No data", panel["title"]
            checked.append(panel["title"])
    assert len(checked) == 8
    ratio = next(p for p in panels("zeus-llm-usage") if p["title"].startswith("Unknown ratio"))
    assert queried(ratio) == ["zeus:llm_unknown_ratio:1d"]


# -- A27 -------------------------------------------------------------------------

def is_token_metric(name):
    return "token" in name


def test_a27_no_expression_combines_a_provider_metric_with_a_token_metric():
    for name, panel in all_panels():
        used_by_panel = set()
        for expr in queried(panel):
            used = metric_names(expr)
            used_by_panel |= used
            assert not (any(u.startswith("zeus_llm_provider_") for u in used) and any(map(is_token_metric, used))), expr
        if any(u.startswith("zeus_llm_provider_") for u in used_by_panel):
            assert all(u.startswith("zeus_llm_provider_") for u in used_by_panel), (name, panel["title"])
            assert NOT_DERIVED in panel["description"], (name, panel["title"])


def provider_window_panels():
    rows = panels("zeus-llm-usage")
    start = next(i for i, p in enumerate(rows) if p["type"] == "row" and p["title"] == "Provider windows")
    end = next(i for i, p in enumerate(rows) if i > start and p["type"] == "row")
    return rows[start + 1:end]


def window_of(panel):
    return "five_hour" if panel["title"].endswith("five_hour") else "seven_day"


def effective_unit(panel, ref_id):
    """Unit Grafana applies to the frame of `ref_id`: defaults, then matching overrides (byFrameRefID only)."""
    config = panel["fieldConfig"]
    unit = config["defaults"].get("unit")
    for override in config.get("overrides", []):
        assert override["matcher"]["id"] == "byFrameRefID", override
        if override["matcher"]["options"] == ref_id:
            for prop in override["properties"]:
                if prop["id"] == "unit":
                    unit = prop["value"]
    return unit


def test_a27_provider_window_panels_derive_from_provider_windows_json_with_the_f1_presentation():
    def normalized(panel):
        panel = copy.deepcopy(panel)
        for key in ("id", "gridPos", "datasource"):
            panel.pop(key, None)
        for target in panel["targets"]:
            target.pop("datasource", None)
        return panel

    def with_f1_presentation(panel):
        # the only differences from the W1 (A54) artifact: DESIGN 6 / review F1, observation time as a date
        panel = normalized(panel)
        if panel["type"] == "stat":
            w = window_of(panel)
            panel["fieldConfig"]["defaults"]["mappings"][0]["options"]["2"]["text"] = "Stale"
            panel["targets"].append({
                "refId": "B",
                "expr": "max by (slot) (zeus_llm_provider_window_observed_timestamp_seconds"
                        f'{{provider="anthropic",window="{w}"}}) * 1000',
                "legendFormat": "{{slot}} last observed"})
            panel["fieldConfig"]["overrides"] = [{"matcher": {"id": "byFrameRefID", "options": "B"},
                                                  "properties": [{"id": "unit", "value": "dateTimeAsIso"}]}]
        else:
            panel["targets"] = [t for t in panel["targets"] if t["refId"] == "A"]
        return panel

    source = json.loads(WINDOWS.read_text())["panels"]
    actual = provider_window_panels()
    assert len(source) == len(actual) == 4
    for src, got in zip(source, actual):
        assert (got["title"], got["type"], got["description"]) == (src["title"], src["type"], src["description"])
        src_a = [t["expr"] for t in src["targets"] if t["refId"] == "A"]
        assert [t["expr"] for t in got["targets"] if t["refId"] == "A"] == src_a
        assert "Reported by the provider; not derived from token counts" in got["description"]
    assert [normalized(p) for p in actual] == [with_f1_presentation(p) for p in source]


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def test_f1_observation_time_is_a_date_and_utilization_a_ratio():
    assert not [t for t in strings(load("zeus-llm-usage")) if "{{time}}" in t]
    by_title = {p["title"]: p for p in provider_window_panels()}
    for window in ("five_hour", "seven_day"):
        state, gauge = by_title[f"Window state {window}"], by_title[f"Window utilization {window}"]
        b = [t for t in state["targets"] if t["refId"] == "B"]
        assert len(b) == 1
        assert "zeus_llm_provider_window_observed_timestamp_seconds" in b[0]["expr"]
        assert f'window="{window}"' in b[0]["expr"] and "by (slot)" in b[0]["expr"]
        assert "{{slot}}" in b[0]["legendFormat"]
        assert effective_unit(state, "B").startswith("dateTime")
        assert effective_unit(state, "A") is None
        assert not [m for m in state["fieldConfig"]["defaults"]["mappings"]
                    if m["type"] == "value" and "B" in json.dumps(m)]
        (target,) = gauge["targets"]
        assert target["refId"] == "A" and "zeus_llm_provider_utilization_ratio" in target["expr"]
        assert f'window="{window}"' in target["expr"] and "{{slot}}" in target["legendFormat"]
        assert effective_unit(gauge, "A") == "percentunit"
        assert gauge["fieldConfig"]["defaults"]["noValue"] == "No data"


def test_f1_synthetic_readings_resolve_to_the_right_units_and_texts():
    by_title = {p["title"]: p for p in provider_window_panels()}
    for window in ("five_hour", "seven_day"):
        state, gauge = by_title[f"Window state {window}"], by_title[f"Window utilization {window}"]
        # current 0.79 is a ratio shown as a percentage; the epoch (ms) is a date, never a percentage
        assert effective_unit(gauge, "A") == "percentunit"
        assert effective_unit(state, "B").startswith("dateTime")
        assert 1700000000 * 1000 > 0 and effective_unit(state, "B") != "percentunit"
        texts = {k: v["text"] for k, v in state["fieldConfig"]["defaults"]["mappings"][0]["options"].items()}
        assert texts["2"] == "Stale"
        assert texts["3"] == "Expired"
        assert texts["4"] == "Unavailable: newest observation has no valid reading for this window"
        # expired (3) and unavailable (4) carry no utilization: the gauge query filters them out
        assert 'freshness=~"current|stale"' in gauge["targets"][0]["expr"]


# -- A28 -------------------------------------------------------------------------

def test_a28_cost_panels_are_titled_as_estimates_and_nothing_says_charge_or_bill():
    cost_panels = [p for _, p in all_panels() if any("estimated_cost_usd" in e for e in queried(p))]
    assert cost_panels
    for panel in cost_panels:
        assert "estimate" in panel["title"].lower()
        assert "client estimate, not a charge" in panel["description"].lower()
    for name, panel in all_panels():
        title = panel["title"].lower()
        assert not re.search(r"charge|bill", title), (name, title)
        assert "cost" not in title or "estimate" in title, (name, title)
        for expr in queried(panel):
            assert not re.search(r"charge|bill", expr.lower()), (name, expr)


# -- Always visible --------------------------------------------------------------

def test_the_unattributed_and_ambiguous_shares_are_always_visible():
    (panel,) = [p for p in panels("zeus-llm-usage") if p["title"] == "Unattributed and ambiguous shares"]
    text = json.dumps(panel)
    assert "$role" not in text and "$task_class" not in text and "${role}" not in text
    exprs = " ".join(queried(panel))
    for value in ("nested_unattributed", "advisor_or_nested", "unattributed_interval", "identity_unavailable"):
        assert value in exprs, value
    # the named-role panels keep their variable filter and never select these four values as a role
    named = [p for p in panels("zeus-llm-usage") if p["title"].startswith("Tokens by role and type")]
    assert named and all("$role" in e for p in named for e in queried(p))
