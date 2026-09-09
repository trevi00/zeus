"""Strict specification and observation contracts; a report never grants release authority."""
import re
from copy import deepcopy
from datetime import datetime

from codex_harness.domain.model import digest, require

STAGES = (
    ("spec_discussion", "스펙 논의", "spec", ("spec_integrity", "human_scope")),
    ("design_analysis", "디자인 분석", "frontend", ("interaction_design", "human_design")),
    ("implementation", "코드 작성", "frontend/backend", ("candidate_build", "component_stories")),
    ("self_verification", "자체 검증", "qa_qc", ("environment_identity", "real_device_e2e", "reset_verified")),
    ("alpha_deployment", "알파 배포", "devops", ("alpha_receipt",)),
    ("qa_evidence", "QA 및 증적", "qa_qc", ("reviewed_oracles", "human_acceptance")),
    ("live_deployment", "라이브 배포", "devops", ("progressive_rollout", "rollback_receipt")),
    ("cs_response", "CS 대응", "backend/qa_qc/devops", ("monitoring", "incident_feedback")),
)
ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,79}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
ENVIRONMENT_FIELDS = {"device_id", "manufacturer", "model", "form_factor", "platform", "os_version",
    "one_ui_version", "webview_version", "app_build_hash", "locale", "timezone", "orientation",
    "backend_revision", "data_revision", "reset_receipt", "physical_device"}


def _text(value, name, limit=4000):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit, "Invalid " + name)


def _id(value):
    require(isinstance(value, str) and ID.fullmatch(value), "Invalid stable ID")


def _strings(values, name, limit=50):
    require(isinstance(values, list) and 0 < len(values) <= limit, "Missing or excessive " + name)
    for value in values:
        _text(value, name)


def validate_spec(value, previous=None):
    """INV-SDD-001: unknown fields, absent scenarios and retired-ID resurrection fail closed."""
    required = {"schema", "id", "title", "intent", "personas", "requirements", "scenarios",
                "devices", "design", "target", "reset_contract"}
    require(isinstance(value, dict) and set(value) == required, "Invalid SDD spec fields")
    require(value["schema"] == "zeus.sdd.v1", "Unsupported SDD schema")
    _id(value["id"])
    for key in ("title", "intent", "reset_contract"):
        _text(value[key], key)
    _strings(value["personas"], "personas")
    require(isinstance(value["target"], dict) and set(value["target"]) == {"kind", "app_id", "build_hash", "alpha_url"},
            "Invalid target identity")
    require(value["target"]["kind"] in {"unconfigured", "web", "android"}, "Unsupported target kind")
    for key in ("app_id", "build_hash", "alpha_url"):
        require(value["target"][key] is None or isinstance(value["target"][key], str), "Invalid target " + key)
    require(value["target"]["build_hash"] is None or HASH.fullmatch(value["target"]["build_hash"]), "Invalid app build hash")
    design = value["design"]
    require(isinstance(design, dict) and set(design) == {"components", "icons", "tokens", "required_stories"}, "Invalid design contract")
    for key in ("components", "icons", "tokens"):
        _text(design[key], "design " + key)
    _strings(design["required_stories"], "required stories")
    require(isinstance(value["devices"], list) and 0 < len(value["devices"]) <= 20, "Device matrix required")
    devices = {}
    for row in value["devices"]:
        require(isinstance(row, dict) and set(row) == {"id", "manufacturer", "platform", "form_factor", "physical_required", "conditions"},
                "Invalid device profile")
        _id(row["id"])
        require(row["id"] not in devices, "Duplicate device profile")
        require(row["manufacturer"] == "samsung" and row["platform"] == "android"
                and row["form_factor"] in {"phone", "tablet"} and row["physical_required"] is True,
                "Initial SDD scope requires physical Samsung Android phone/tablet")
        _strings(row["conditions"], "device conditions")
        devices[row["id"]] = row
    require(isinstance(value["requirements"], list) and 0 < len(value["requirements"]) <= 200, "Requirements missing")
    requirements = {}
    for row in value["requirements"]:
        require(isinstance(row, dict) and set(row) == {"id", "statement", "risk", "status"}, "Invalid requirement")
        _id(row["id"])
        require(row["id"] not in requirements, "Duplicate requirement ID")
        _text(row["statement"], "requirement statement")
        require(row["risk"] in {"normal", "critical", "financial"}, "Invalid requirement risk")
        require(row["status"] in {"active", "retired"}, "Invalid requirement status")
        requirements[row["id"]] = row
    require(isinstance(value["scenarios"], list) and 0 < len(value["scenarios"]) <= 200, "Scenarios missing; not a pass")
    scenarios, covered = {}, set()
    for row in value["scenarios"]:
        require(isinstance(row, dict) and set(row) == {"id", "title", "status", "requirement_ids", "given", "when", "then", "device_profiles", "bindings"},
                "Invalid scenario fields")
        _id(row["id"])
        require(row["id"] not in scenarios, "Duplicate scenario ID")
        _text(row["title"], "scenario title")
        require(row["status"] in {"active", "retired"}, "Invalid scenario status")
        for key in ("requirement_ids", "given", "when", "then", "device_profiles"):
            _strings(row[key], key)
        require(set(row["requirement_ids"]) <= requirements.keys(), "Unknown scenario requirement")
        require(set(row["device_profiles"]) <= devices.keys(), "Unknown scenario device")
        require(isinstance(row["bindings"], list) and len(row["bindings"]) <= 100, "Invalid executable bindings")
        for binding in row["bindings"]:
            require(isinstance(binding, dict) and set(binding) == {"operation", "selector", "value", "oracle_index", "source_ref"}, "Invalid replay binding")
            require(binding["operation"] in {"tap", "input", "assert_visible", "assert_text"}, "Unsupported replay operation")
            selector = binding["selector"]
            require(isinstance(selector, dict) and set(selector) == {"strategy", "value"}
                    and selector["strategy"] in {"id", "accessibility id"}, "Stable selector required")
            _text(selector["value"], "selector", 500)
            require(binding["value"] is None or isinstance(binding["value"], str), "Invalid replay value")
            _text(binding["source_ref"], "binding source", 300)
            if binding["operation"].startswith("assert_"):
                require(type(binding["oracle_index"]) is int and 0 <= binding["oracle_index"] < len(row["then"]), "Assertion must map to an explicit oracle")
            else:
                require(binding["oracle_index"] is None, "Actions cannot claim oracle coverage")
            if binding["operation"] in {"input", "assert_text"}:
                _text(binding["value"], "binding value", 1000)
        scenarios[row["id"]] = row
        if row["status"] == "active":
            require(all(requirements[k]["status"] == "active" for k in row["requirement_ids"]), "Active scenario references retired requirement")
            covered.update(row["requirement_ids"])
    require(any(row["status"] == "active" for row in scenarios.values()), "No active scenarios")
    require(covered == {k for k, r in requirements.items() if r["status"] == "active"}, "Requirement without an active scenario")
    if previous is not None:
        require(previous["id"] == value["id"], "Spec identity changed")
        for old in previous["requirements"]:
            require(old["id"] in requirements, "Retire requirement IDs instead of deleting them")
            current = requirements[old["id"]]
            require(all(current[k] == old[k] for k in ("statement", "risk")), "Changed requirement meaning requires a new ID")
            require(old["status"] != "retired" or current["status"] == "retired", "Retired requirement ID cannot be reused")
        for old in previous["scenarios"]:
            require(old["id"] in scenarios, "Retire scenario IDs instead of deleting them")
            require(old["status"] != "retired" or scenarios[old["id"]]["status"] == "retired", "Retired scenario ID cannot be reused")
    return deepcopy(value)


def coverage(spec, observed_ids):
    active = {s["id"] for s in spec["scenarios"] if s["status"] == "active"}
    observed = set(observed_ids)
    return {"matched": sorted(active & observed), "missing": sorted(active - observed),
            "orphan": sorted(observed - active), "authority": "structural_only_not_acceptance"}


def validate_environment(value):
    require(isinstance(value, dict) and set(value) == ENVIRONMENT_FIELDS, "Incomplete environment identity")
    for key in ENVIRONMENT_FIELDS - {"physical_device"}:
        _text(value[key], "environment " + key, 500)
    require(type(value["physical_device"]) is bool, "Physical device fact required")
    require(value["form_factor"] in {"phone", "tablet", "desktop", "unknown"}, "Unknown form factor")
    require(value["orientation"] in {"portrait", "landscape", "unknown"}, "Invalid orientation")
    return deepcopy(value)


def validate_events(rows):
    require(isinstance(rows, list) and 0 < len(rows) <= 1000, "Observation event budget exceeded or empty")
    for row in rows:
        require(isinstance(row, dict) and set(row) == {"sequence", "scenario_id", "kind", "name", "observed", "source_ref", "timestamp", "observed_timestamp"}, "Invalid observation fields")
        require(type(row["sequence"]) is int and row["sequence"] > 0, "Invalid event sequence")
        _id(row["scenario_id"])
        require(row["kind"] in {"action", "observation", "assertion", "gap"}, "Unknown event kind")
        for key in ("name", "observed", "source_ref"):
            _text(row[key], "event " + key, 2000)
        for key in ("timestamp", "observed_timestamp"):
            require(key == "timestamp" and row[key] is None or isinstance(row[key], str), "Invalid event timestamp")
            if row[key] is not None:
                try:
                    instant = datetime.fromisoformat(row[key])
                except ValueError:
                    require(False, "Invalid event timestamp")
                require(instant.tzinfo is not None, "Event timestamp requires a timezone")
    numbers = [row["sequence"] for row in rows]
    require(len(numbers) == len(set(numbers)) and numbers == sorted(numbers), "Duplicate or unordered events")
    return deepcopy(rows)


def propose_scenarios(spec, environment, events):
    """INV-ORACLE-001: log-derived proposals contain observations, never expected outcomes."""
    validate_environment(environment)
    validate_events(events)
    by_id = {}
    for row in events:
        by_id.setdefault(row["scenario_id"], []).append(row)
    numbers = [row["sequence"] for row in events]
    contiguous = numbers == list(range(1, len(numbers) + 1)) and not any(r["kind"] == "gap" for r in events)
    return {"schema": "zeus.scenario-proposal.v1", "spec_hash": digest(spec),
            "environment_hash": digest(environment), "events_hash": digest(events),
            "observations": by_id, "coverage": coverage(spec, by_id), "sequence_complete": contiguous,
            "status": "requires_human_oracle_review", "authority": "proposal_only",
            "acceptance_passed": False}


def gate_report(spec, observations=()):
    validate_spec(spec)
    # No imported claim or local --reviewer string can authenticate human QA or a device run.
    rows = []
    for key, title, owner, checks in STAGES:
        facts = [{"check": name, "status": "validated_structure" if name == "spec_integrity" else "not_run",
                  "reason": "Native schema validation" if name == "spec_integrity" else
                  "Authenticated human decision provider required" if name.startswith("human_") or name == "reviewed_oracles"
                  else "Actual version-bound runner evidence required"} for name in checks]
        rows.append({"id": key, "title": title, "responsible_team": owner, "status": "blocked",
                     "checks": facts, "authority": "advisory_gate_report"})
    return {"schema": "zeus.sdd-report.v1", "spec_hash": digest(spec), "stages": rows,
            "observation_count": len(observations), "acceptance_passed": False,
            "release_authorized": False, "human_authority_configured": False,
            "next_action": "Review the intended user scenarios and configure authenticated human approval",
            "model_transfer": {"design": "gpt-6-astra", "final_validation": "gpt-6-astra",
                "important_target": "gpt-5.6-sol", "simple_target": "gpt-5.6-terra",
                "status": "unqualified", "automatic_downshift": False}}
