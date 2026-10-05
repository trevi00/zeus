"""S9 X4a: the Zeus recording and alert rules over the X2a/X3a metrics (DESIGN-s9-X §4).

Static checks (PyYAML) run everywhere: the alert fields and closed enums, every `zeus_` metric token in an expression
being an X2a or X3a family or a recording rule of the file, the recording name pattern, every alert tested both firing
and resolved, and every runbook anchor existing.

`promtool check rules` and `promtool test rules` are OWNER-RUN outside pytest, as in the tokobs precedent. The test
process's provider guard (`compare/guard/provider_guard.py`) admits docker only in its owned-fixture forms, and it stays
as it is. The owner command, with the local image never pulled:
`docker run --rm --network none --read-only --tmpfs /tmp:rw,size=64m --cap-drop ALL --security-opt no-new-privileges
--user 65534 --mount type=bind,src=<rules dir>,dst=/rules,readonly --entrypoint promtool prom/prometheus:latest
{check rules /rules/zeus-s9.yml | test rules /rules/zeus-s9.test.yml}`. The result is recorded in
A/evidence/rebuild/s9/integration/x4a-promtool.txt.
"""

from __future__ import annotations

import re

import yaml
from _layout import TARGET

from codex_harness.observation.adapters.resource_facts import _FAMILIES as RESOURCE_FAMILIES
from codex_harness.observation.domain.metric_families import FAMILIES

RULES_DIR = TARGET / "deploy" / "observability" / "prometheus" / "rules"
RULES = RULES_DIR / "zeus-s9.yml"
TESTS = RULES_DIR / "zeus-s9.test.yml"
RUNBOOK = TARGET / "docs" / "runbooks" / "zeus-s9.md"
RUNBOOK_PREFIX = "target/docs/runbooks/zeus-s9.md#"
BASIS = "provisional: no production baseline (S9 fixtures)"
OWNERS = {"observation", "execution", "host_os"}
SEVERITIES = {"info", "warning", "critical"}
RECORDING_NAME = re.compile(r"^zeus:[a-z_]+(:[a-z0-9]+)?$")
TOKEN = re.compile(r"(?<![A-Za-z0-9_:])zeus[A-Za-z0-9_:]*")
DURATION = re.compile(r"^\d+[smh]$")


def _groups():
    return {group["name"]: group["rules"] for group in yaml.safe_load(RULES.read_text())["groups"]}


def _alerts():
    return _groups()["zeus-s9-alerts"]


def _metric_names():
    names = set(FAMILIES) | set(RESOURCE_FAMILIES)
    for family in FAMILIES.values():
        if family.type == "histogram":
            names |= {family.name + suffix for suffix in ("_bucket", "_sum", "_count")}
    return names


def _seconds(text):
    return int(text[:-1]) * {"s": 1, "m": 60, "h": 3600}[text[-1]]


def test_two_groups_and_header():
    assert list(_groups()) == ["zeus-s9-recording", "zeus-s9-alerts"]
    header = RULES.read_text().split("groups:")[0]
    assert "No Alertmanager and no notification routing" in header
    assert "Deduplication, grouping and silencing are not delivered" in header


def test_alert_fields_and_closed_enums():
    alerts = _alerts()
    assert len(alerts) == 9 and len({rule["alert"] for rule in alerts}) == 9
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
    recordings = _groups()["zeus-s9-recording"]
    assert len(recordings) == 5
    for rule in recordings:
        assert RECORDING_NAME.match(rule["record"]), rule["record"]


def test_expression_metric_tokens_are_known_families():
    groups = _groups()
    recorded = {rule["record"] for rule in groups["zeus-s9-recording"]}
    known = _metric_names()
    for rule in groups["zeus-s9-recording"] + groups["zeus-s9-alerts"]:
        for token in TOKEN.findall(rule["expr"]):
            assert token in recorded or (":" not in token and token in known), (rule.get("alert") or rule["record"], token)
    # A recording rule is only used after its own definition, so the group order is the evaluation order.
    for rule in groups["zeus-s9-recording"]:
        assert all(token in known for token in TOKEN.findall(rule["expr"])), rule["record"]


def test_every_alert_is_tested_firing_and_resolved():
    document = yaml.safe_load(TESTS.read_text())
    assert document["rule_files"] == ["zeus-s9.yml"]
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
    below_volume = [group for group in document["tests"] if all(
        not case["exp_alerts"] for case in group.get("alert_rule_test", [{"exp_alerts": [1]}]))
        and any(case["alertname"] == "ZeusModelInvocationFailureRatioHigh" for case in group.get("alert_rule_test", []))]
    assert below_volume, "the failure ratio alert needs a below-volume case that does not fire"
    expr_tests = [case["expr"] for group in document["tests"] for case in group.get("promql_expr_test", [])]
    for rule in _groups()["zeus-s9-recording"]:
        assert any(expr == rule["record"] for expr in expr_tests), rule["record"]


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

