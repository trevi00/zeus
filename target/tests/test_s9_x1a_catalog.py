"""S9 X1a: the observability event catalog (SSOT) and the ten REGISTRY additions (DESIGN-s9-X §1, §1.1).

Observation only: no producer emits these events yet (X1b). The catalog and `REGISTRY` agree in both directions, every
enum is closed, no attribute is free text, the M7 entries are unchanged against SOURCE, and a secret planted in an
attribute value is redacted by the existing `build_event` (and refused by the catalog check).
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from codex_harness.kernel.errors import ContractError
from codex_harness.observation.domain import observation as obs
from codex_harness.observation.domain.event_catalog import check_catalog_attributes, load_catalog

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
M7_OBSERVATION = "src/codex_harness/domain/observation.py"
CANARY = "CANARY-9f3b1c7e2a5d4f6b8e0c1d2a3b4c5d6e"
TYPE_KEYS = {"_S": obs._S, "_I": obs._I, "_B": obs._B, "_F": obs._F, "_N": obs._N, "_NI": obs._NI, "_NB": obs._NB}
OPAQUE_NAMES = {"role", "provider", "check", "feature", "collector"}
NEW = {"operations.queue_item_waited", "development.role_dispatch_decided", "operations.capacity_refused",
       "development.tool_call_completed", "development.skill_selected", "operations.ci_observed",
       "operations.cleanup_recorded", "operations.collector_started", "operations.path_declined",
       "development.provider_usage_split"}


def m7_registry():
    src = subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_OBSERVATION}"], check=True,
                         capture_output=True, text=True).stdout
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "REGISTRY":
            return eval(compile(ast.Expression(node.value), "<m7 REGISTRY>", "eval"), {"__builtins__": {}}, TYPE_KEYS)
    raise AssertionError("REGISTRY not found in SOURCE")


def test_the_catalog_loads_and_names_exactly_the_ten_new_events():
    catalog = load_catalog()
    assert catalog["catalog_version"] == 1
    assert set(catalog["events"]) == NEW
    for name, entry in catalog["events"].items():
        assert {"owner_context", "category", "severity", "boundary", "attributes", "producer_sites"} <= set(entry)
        assert entry["category"] == name.split(".")[0] and entry["attributes"]
        assert entry["severity"] in obs.SEVERITIES and entry["producer_sites"] == "measured at X1b"


def test_catalog_and_registry_agree_in_both_directions():
    events = load_catalog()["events"]
    for name, entry in events.items():
        assert name in obs.REGISTRY, name
        assert {k: v["type"] for k, v in entry["attributes"].items()} == obs.REGISTRY[name], name
    m7 = m7_registry()
    assert set(obs.REGISTRY) - set(m7) == set(events)  # every non-M7 REGISTRY key is in the catalog
    assert not set(events) & set(m7)


def test_the_m7_registry_entries_are_unchanged_against_source():
    m7 = m7_registry()
    assert len(m7) == 66
    assert all(obs.REGISTRY[name] == attributes for name, attributes in m7.items())
    assert list(obs.REGISTRY)[:66] == list(m7)  # the additions are appended, not interleaved


def test_every_enum_is_closed_and_no_attribute_is_free_text():
    for name, entry in load_catalog()["events"].items():
        for attr, spec in entry["attributes"].items():
            if "enum" in spec:
                values = spec["enum"]
                assert spec["type"] == "string" and values and len(values) == len(set(values)), (name, attr)
                assert all(isinstance(v, str) and 0 < len(v) <= 40 and v == v.strip() and " " not in v for v in values)
                if "other" in values:
                    assert values[-1] == "other"
            elif spec["type"] in ("string", "nullable_string"):
                assert spec.get("opaque") is True, (name, attr)  # a string with no enum is an opaque identifier
                assert attr.endswith(("_ref", "_id")) or attr in OPAQUE_NAMES, (name, attr)
            else:
                assert spec["type"] in ("integer", "nullable_integer", "number", "boolean"), (name, attr)


def test_check_catalog_attributes_accepts_the_catalog_example():
    given = {"scope": "lane_slots", "refusal_reason": "lane_full", "retry_after_seconds": None}
    assert check_catalog_attributes("operations.capacity_refused", given) == given
    assert check_catalog_attributes("development.tool_call_completed",
                                    {"tool": "Bash", "outcome": "succeeded", "duration_ms": 5, "reservation_id": None})


@pytest.mark.parametrize("event_type,attributes,fragment", [
    ("operations.capacity_refused", {"scope": "anything"}, "scope"),
    ("operations.capacity_refused", {"scope": "lane_slots", "refusal_reason": "because"}, "refusal_reason"),
    ("operations.capacity_refused", {"scope": "lane_slots", "extra": 1}, "extra"),
    ("operations.capacity_refused", {"retry_after_seconds": "5"}, "retry_after_seconds"),
    ("development.tool_call_completed", {"tool": "MyMcpTool"}, "tool"),
    ("operations.queue_item_waited", {"queue": "somewhere"}, "queue"),
    ("operations.path_declined", {"feature": "has spaces and: free text"}, "feature"),
    ("operations.path_declined", {"decline_reason": ["disabled"]}, "decline_reason"),
    ("operations.ci_observed", {"conclusion": "success", "attempt": True}, "attempt"),
])
def test_check_catalog_attributes_refuses_by_name_and_never_echoes_the_value(event_type, attributes, fragment):
    with pytest.raises(ContractError) as refused:
        check_catalog_attributes(event_type, attributes)
    assert fragment in str(refused.value)
    for value in attributes.values():
        assert not isinstance(value, str) or value not in str(refused.value) or value == fragment


def test_an_unknown_event_type_and_a_non_object_are_refused():
    with pytest.raises(ContractError):
        check_catalog_attributes("general.process_started", {})  # an M7 type is not a catalog type
    with pytest.raises(ContractError):
        check_catalog_attributes("operations.capacity_refused", [])


def test_other_is_allowed_only_where_the_catalog_lists_it():
    catalog = load_catalog()["events"]
    assert "other" in catalog["operations.capacity_refused"]["attributes"]["scope"]["enum"]
    assert check_catalog_attributes("operations.capacity_refused", {"scope": "other"})
    for name, entry in catalog.items():
        for attr, spec in entry["attributes"].items():
            if "enum" in spec and "other" not in spec["enum"]:
                with pytest.raises(ContractError):
                    check_catalog_attributes(name, {attr: "other"})


def test_a_secret_canary_in_an_attribute_is_redacted_by_build_event_and_refused_by_the_catalog():
    secret = f"password: {CANARY}"
    for name, attr in (("operations.path_declined", "feature"), ("operations.collector_started", "collector"),
                       ("development.skill_selected", "skill_ref")):
        event = obs.build_event(
            event_type=name, outcome="observed", execution=obs.execution_identity("system", process_run_id="0" * 31 + "1"),
            sequence={"process_run_id": "0" * 31 + "1", "number": 1, "basis": "spool_append"},
            observed_at="2026-01-01T00:00:00+00:00", source={"component": "x1a", "host": None, "pid": None},
            attributes={attr: secret})
        assert CANARY not in str(event) and "[REDACTED" in event["attributes"][attr]
        with pytest.raises(ContractError) as refused:
            check_catalog_attributes(name, {attr: secret})
        assert CANARY not in str(refused.value)
