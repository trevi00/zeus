"""S9 X4b: the Zeus recording and alert rules over the X2c queue, G3 Redis stream and X5a feature-use facts (DESIGN-s9-X §4).

Static checks (PyYAML) run everywhere, as in `test_s9_x4a_rules.py`: the alert fields and closed enums, every `zeus_`
token in an expression being a family of X2a/X2b/X3a/X2c/G3/X5a or a recording rule of either rules file, the recording
name pattern, every alert tested both firing and resolved, and every runbook anchor existing.

`promtool check rules` and `promtool test rules` are OWNER-RUN outside pytest, with the docker command of the X4a test
docstring on `zeus-s9b.yml` and `zeus-s9b.test.yml`. No docker runs here.
"""

from __future__ import annotations

import re

import yaml
from _layout import TARGET

from codex_harness.observation.adapters.queue_facts import _FAMILIES as QUEUE_FAMILIES
from codex_harness.observation.adapters.redis_stream_facts import _FAMILIES as REDIS_FAMILIES
from codex_harness.observation.adapters.resource_facts import _FAMILIES as RESOURCE_FAMILIES
from codex_harness.observation.domain.feature_registry import INSTRUMENTED
from codex_harness.observation.domain.metric_families import FAMILIES

RULES_DIR = TARGET / "deploy" / "observability" / "prometheus" / "rules"
RULES = RULES_DIR / "zeus-s9b.yml"
OTHER_RULES = RULES_DIR / "zeus-s9.yml"
TESTS = RULES_DIR / "zeus-s9b.test.yml"
RUNBOOK = TARGET / "docs" / "runbooks" / "zeus-s9b.md"
RUNBOOK_PREFIX = "target/docs/runbooks/zeus-s9b.md#"
BASIS = "provisional: no production baseline (S9 fixtures)"
OWNERS = {"observation", "coordination", "storage"}
SEVERITIES = {"info", "warning", "critical"}
RECORDING_NAME = re.compile(r"^zeus:[a-z_]+(:[a-z0-9]+)?$")
TOKEN = re.compile(r"(?<![A-Za-z0-9_:])zeus[A-Za-z0-9_:]*")
DURATION = re.compile(r"^\d+[smh]$")


def _groups(path=RULES):
    return {group["name"]: group["rules"] for group in yaml.safe_load(path.read_text())["groups"]}


def _alerts():
    return _groups()["zeus-s9b-alerts"]


def _metric_names():
    names = set(FAMILIES) | set(RESOURCE_FAMILIES) | set(QUEUE_FAMILIES) | set(REDIS_FAMILIES) | {INSTRUMENTED}
    for family in FAMILIES.values():
        if family.type == "histogram":
            names |= {family.name + suffix for suffix in ("_bucket", "_sum", "_count")}
    return names


def _seconds(text):
    return int(text[:-1]) * {"s": 1, "m": 60, "h": 3600}[text[-1]]


def test_two_groups_and_header():
    assert list(_groups()) == ["zeus-s9b-recording", "zeus-s9b-alerts"]
    header = RULES.read_text().split("groups:")[0]
    assert "No Alertmanager and no notification routing" in header
    assert "Deduplication, grouping and silencing are not delivered" in header


def test_alert_fields_and_closed_enums():
    alerts = _alerts()
    assert len(alerts) == 7 and len({rule["alert"] for rule in alerts}) == 7
    for rule in alerts:
        name = rule["alert"]
        assert DURATION.match(rule["for"]) and DURATION.match(rule["keep_firing_for"]), name
        assert _seconds(rule["for"]) > 0 and _seconds(rule["keep_firing_for"]) > 0, name
        assert set(rule["labels"]) == {"owner", "severity"}, name
        assert rule["labels"]["owner"] in OWNERS and rule["labels"]["severity"] in SEVERITIES, name
        assert set(rule["annotations"]) == {"summary", "runbook", "threshold_basis"}, name
        assert rule["annotations"]["summary"].strip(), name
        assert rule["annotations"]["threshold_basis"] == BASIS, name
        assert rule["annotations"]["runbook"] == RUNBOOK_PREFIX + name.lower(), name


def test_recording_names():
    recordings = _groups()["zeus-s9b-recording"]
    assert [rule["record"] for rule in recordings] == [
        "zeus:redis_memory_usage_ratio", "zeus:feature_used:7d", "zeus:feature_unused_instrumented_candidate:7d"]
    for rule in recordings:
        assert RECORDING_NAME.match(rule["record"]), rule["record"]
    assert not {rule["record"] for rule in recordings} & {rule["record"] for rule in _groups(OTHER_RULES)["zeus-s9-recording"]}


def test_candidate_rule_says_it_is_only_a_candidate():
    text = RULES.read_text()
    assert "CANDIDATE only" in text and "never a removal authority" in text


def test_expression_metric_tokens_are_known_families():
    groups = _groups()
    recorded = {rule["record"] for rule in groups["zeus-s9b-recording"]}
    recorded |= {rule["record"] for rule in _groups(OTHER_RULES)["zeus-s9-recording"]}
    known = _metric_names()
    for rule in groups["zeus-s9b-recording"] + groups["zeus-s9b-alerts"]:
        for token in TOKEN.findall(rule["expr"]):
            assert token in recorded or (":" not in token and token in known), (rule.get("alert") or rule["record"], token)
    # A recording rule is only used after its own definition, so the group order is the evaluation order.
    for rule in groups["zeus-s9b-recording"]:
        assert all(token in known for token in TOKEN.findall(rule["expr"])), rule["record"]


def test_every_alert_is_tested_firing_and_resolved():
    document = yaml.safe_load(TESTS.read_text())
    assert document["rule_files"] == ["zeus-s9b.yml"]
    expected = {rule["alert"]: rule for rule in _alerts()}
    firing, resolved = set(), set()
    for group in document["tests"]:
        by_alert = {}
        for case in group.get("alert_rule_test", []):
            by_alert.setdefault(case["alertname"], []).append(case)
        for name, cases in by_alert.items():
            assert name in expected, name
            cases.sort(key=lambda case: _seconds(case["eval_time"]))
            for case in cases:
                for alert in case["exp_alerts"]:
                    rule = expected[name]
                    assert alert["exp_labels"]["owner"] == rule["labels"]["owner"], name
                    assert alert["exp_labels"]["severity"] == rule["labels"]["severity"], name
                    assert alert["exp_annotations"] == rule["annotations"], name
            first_firing = next((i for i, case in enumerate(cases) if case["exp_alerts"]), None)
            if first_firing is not None:
                firing.add(name)
                if any(not case["exp_alerts"] for case in cases[first_firing + 1:]):
                    resolved.add(name)
    assert firing == set(expected) and resolved == set(expected)
    expr_tests = [case["expr"] for group in document["tests"] for case in group.get("promql_expr_test", [])]
    for rule in _groups()["zeus-s9b-recording"]:
        assert any(expr == rule["record"] for expr in expr_tests), rule["record"]


def test_feature_recordings_cover_unused_and_used_features():
    document = yaml.safe_load(TESTS.read_text())
    cases = {case["expr"]: case for group in document["tests"] for case in group.get("promql_expr_test", [])
             if case["expr"].startswith("zeus:feature_")}
    candidate = {sample["labels"] for sample in cases["zeus:feature_unused_instrumented_candidate:7d"]["exp_samples"]}
    name = "zeus:feature_unused_instrumented_candidate:7d"
    assert name + '{feature="fleet_backlog"}' in candidate
    assert name + '{feature="model_invocation"}' not in candidate


def test_runbook_anchors_exist():
    text = RUNBOOK.read_text()
    anchors = {re.sub(r"[^a-z0-9_-]", "", heading.strip().lower().replace(" ", "-"))
               for heading in re.findall(r"^#{1,6} (.+)$", text, re.MULTILINE)}
    for rule in _alerts():
        anchor = rule["annotations"]["runbook"].removeprefix(RUNBOOK_PREFIX)
        assert anchor in anchors, rule["alert"]
    sections = [name for name in re.findall(r"^## (.+)$", text, re.MULTILINE)]
    assert sections == [rule["alert"] for rule in _alerts()]
    for part in ("**What fired:**", "**First three read-only checks:**", "**Do not conclude:**", "**Owner:**"):
        assert text.count(part) == len(sections), part
    owners = re.findall(r"^\*\*Owner:\*\* (.+)$", text, re.MULTILINE)
    assert owners == [rule["labels"]["owner"] for rule in _alerts()]
