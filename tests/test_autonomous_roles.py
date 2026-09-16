"""Producer/consumer contract for the four model-facing role schemas (INV-AUTONOMOUS-001).

Every output below is a labelled fixture; no model is called. The live rejected researcher output
is reproduced as a compact fixture carrying only the refused kinds and status, never the transcript.
"""
import json

import pytest
from jsonschema import Draft202012Validator

from codex_harness.adapters.autonomous_roles import CONSUMER_ENUMS, OBJECTIVES, SCHEMAS
from codex_harness.adapters.execution_output import completed_output
from codex_harness.adapters.output_schema import preflight
from codex_harness.adapters.providers import packaged_policy
from codex_harness.domain.autonomous import (
    ROLE_ORDER,
    SSOT_DECISIONS,
    event_from_role,
    packet_from_research,
    validate_autonomous_manifest,
)
from codex_harness.domain.dge import (
    CLAIM_KINDS,
    DECISIONS,
    QUESTION_STATUSES,
    SEVERITIES,
    VERDICTS,
    EventError,
    PacketError,
    validate_event,
    validate_payload,
)
from codex_harness.domain.model import ContractError, canonical

BASE = "a" * 40
SOURCE_SHA = "b" * 64
CRITERION = "focused tests pass"
MANIFEST = validate_autonomous_manifest(
    {"schema": "urn:zeus:autonomous:1", "id": "auto-roles", "base_revision": BASE,
     "goal": {"path": "docs/zeus/operations/GOAL.md", "sha256": SOURCE_SHA, "criterion": "one-start entry point",
              "rationale": "fixture"},
     "plan": {"objective": "align the role schemas", "acceptance_criteria": [CRITERION],
              "allowed_paths": ["src/codex_harness/adapters/autonomous_roles.py"]},
     "budget": {"per_host": 8, "total": 16},
     "claude": {"model": "claude-fixture-model", "timeout_seconds": 300, "max_budget_usd": 2},
     "deadline": "2030-01-01T00:00:00+00:00",
     "research": {"topic": "role contracts", "questions": ["which enums?"], "search_scope": ["src"]}},
    packaged_policy())
SOURCE = {"id": "s1", "path": "docs/contracts.md", "sha256": SOURCE_SHA, "locator": "git", "revision": BASE, "read_scope": "all"}
TRANSITION = {"compatibility": "additive", "rollback": "revert", "retirement": "none"}
RESEARCH = {"sources": [SOURCE],
            "claims": [{"id": "c1", "kind": "fact", "text": "CLAIM_KINDS is finite", "source_ids": ["s1"]},
                       {"id": "c2", "kind": "inference", "text": "an enum keeps outputs inside it", "source_ids": ["s1"]},
                       {"id": "c3", "kind": "unknown", "text": "runtime jsonschema behaviour on the host", "source_ids": []}],
            "questions": [{"id": "q1", "question": "which enums?", "blocking": True, "status": "answered", "claim_ids": ["c1"]},
                          {"id": "q2", "question": "host behaviour?", "blocking": False, "status": "unknown", "claim_ids": ["c3"]}],
            "ssot": {"searched_paths": ["src"], "searched_symbols": ["CLAIM_KINDS"], "authoritative_definition": "domain/dge.py",
                     "callers": ["adapters/autonomous_roles.py"], "evidence": ["ran: python -m pytest tests/test_dge.py (observed pass)"],
                     "unknowns": [], "decision": "improve", "rationale": "reuse the domain constants", "transition": TRANSITION},
            "needs_user": False, "user_question": None}
CRITICAL = {"id": "f1", "criterion": CRITERION, "severity": "critical", "scenario": "schema admits a bad kind", "claim_ids": ["c1"],
            "trigger": "model emits kind=verdict", "impact": "packet refused after a paid start", "mitigation": "enum from CLAIM_KINDS"}
MINOR = {"id": "f2", "criterion": CRITERION, "severity": "minor", "scenario": "prompt wording", "claim_ids": ["c2"],
         "trigger": None, "impact": None, "mitigation": None}
ROLE_OUTPUTS = {"researcher": RESEARCH, "proposer": {"summary": "enum every finite field", "claim_ids": ["c1", "c2"]},
                "attacker": {"findings": [CRITICAL, MINOR]},
                "arbiter": {"verdict": "accept", "rationale": "the critical finding is mitigated by the plan", "research_question": None,
                            "dispositions": [{"finding_id": "f1", "decision": "resolved", "reason": "enum in schema"},
                                             {"finding_id": "f2", "decision": "deferred", "reason": "backlog"}]}}
# Live canary autonomous-ssot-canary-001 (task 7708599f, base e345c2e): the researcher's real output used
# these claim kinds and a prose question status; packet_from_research refused it. Compact fixture, not the transcript.
LIVE_REJECTED_KINDS = ("review_frame", "recommendation", "test_command", "execution_result", "verdict")
LIVE_REJECTED_STATUS = "open - depends on the future CI run"
PACKET_DIGEST = "1" * 64


def schema_check(role, output):
    """What the runner does with the provider's text: preflight plus Draft 2020-12 validation."""
    return completed_output(canonical(output), SCHEMAS[role])


def consume(role, output, findings=None):
    """The existing consumers, untouched: packet validator for research, per-role payload validator for debate."""
    if role == "researcher":
        return packet_from_research(MANIFEST, output)
    event = validate_event(event_from_role(role, output, PACKET_DIGEST, 1, "task-" + role))
    return validate_payload(role, event["payload"], claim_ids={"c1", "c2", "c3"}, criteria=[CRITERION],
                            findings=findings if findings is not None else ROLE_OUTPUTS["attacker"]["findings"])


def test_every_role_schema_enum_is_the_consumer_constant_and_passes_preflight():
    schemas = SCHEMAS
    located = {"claim.kind": schemas["researcher"]["properties"]["claims"]["items"]["properties"]["kind"],
               "question.status": schemas["researcher"]["properties"]["questions"]["items"]["properties"]["status"],
               "ssot.decision": schemas["researcher"]["properties"]["ssot"]["properties"]["decision"],
               "finding.severity": schemas["attacker"]["properties"]["findings"]["items"]["properties"]["severity"],
               "arbiter.verdict": schemas["arbiter"]["properties"]["verdict"],
               "disposition.decision": schemas["arbiter"]["properties"]["dispositions"]["items"]["properties"]["decision"]}
    expected = {"claim.kind": CLAIM_KINDS, "question.status": QUESTION_STATUSES, "ssot.decision": SSOT_DECISIONS,
                "finding.severity": SEVERITIES, "arbiter.verdict": VERDICTS, "disposition.decision": DECISIONS}
    assert CONSUMER_ENUMS == expected
    for field, node in located.items():
        assert node["type"] == "string" and set(node["enum"]) == expected[field] and len(node["enum"]) == len(expected[field]), field
    for role in ROLE_ORDER:
        receipt = preflight(SCHEMAS[role])
        assert receipt["checks"] and ("enum" in receipt["keywords"]) == (role != "proposer"), role


def test_prompts_name_the_finite_values_and_separate_design_unknowns_from_future_tests():
    researcher = OBJECTIVES["researcher"]
    for value in CLAIM_KINDS | QUESTION_STATUSES | SSOT_DECISIONS:
        assert value in researcher
    assert "ssot.evidence" in researcher and "not claim kinds" in researcher
    assert "have not run yet are not unknown design questions" in researcher
    assert "not asked to certify" in researcher, "a read-only researcher never certifies the future fix"
    assert all(v in OBJECTIVES["attacker"] for v in SEVERITIES) and "Everything else is minor" in OBJECTIVES["attacker"]
    assert all(v in OBJECTIVES["arbiter"] for v in VERDICTS | DECISIONS) and "never defer a critical" in OBJECTIVES["arbiter"]


@pytest.mark.parametrize("role", ROLE_ORDER)
def test_valid_full_role_output_passes_the_schema_and_the_consumer(role):
    result = schema_check(role, ROLE_OUTPUTS[role])
    assert result["answer"] == ROLE_OUTPUTS[role] and result["structural"]["checks"]["schema"] == "checked", result.get("failure")
    consumed = consume(role, ROLE_OUTPUTS[role])
    if role == "researcher":
        assert consumed["ssot"]["decision"] == "improve" and [c["kind"] for c in consumed["packet"]["claims"]] == ["fact", "inference", "unknown"]
        assert [q["status"] for q in consumed["packet"]["questions"]] == ["answered", "unknown"]
    elif role == "attacker":
        assert [f["severity"] for f in consumed["findings"]] == ["critical", "minor"]
        assert consumed["findings"][0]["scenario"].endswith("mitigation: enum from CLAIM_KINDS"), "materiality is carried into the event"
    elif role == "arbiter":
        assert [d["decision"] for d in consumed["dispositions"]] == ["resolved", "deferred"]


@pytest.mark.parametrize("role, pointer, bad", [
    ("researcher", ("claims", 0, "kind"), "review_frame"),
    ("researcher", ("questions", 0, "status"), "open"),
    ("researcher", ("ssot", "decision"), "keep"),
    ("attacker", ("findings", 0, "severity"), "high"),
    ("arbiter", ("verdict",), "approve"),
    ("arbiter", ("dispositions", 0, "decision"), "accepted"),
])
def test_invalid_finite_values_are_refused_at_the_model_boundary_and_by_the_consumer(role, pointer, bad):
    document = json.loads(canonical(ROLE_OUTPUTS[role]))
    node = document
    for step in pointer[:-1]:
        node = node[step]
    node[pointer[-1]] = bad
    result = schema_check(role, document)
    assert result["answer"] is None and result["failure"]["output_reason"] == "schema_mismatch"
    assert result["failure"]["owner"] == "agent_output" and result["failure"]["instance_path"] == list(pointer)
    assert bad not in str(result["failure"]), "no value is echoed"
    with pytest.raises((PacketError, EventError, ContractError)):
        consume(role, document)


def test_live_rejected_claim_kinds_and_question_status_fixture_is_refused_before_the_packet():
    # Labelled reproduction of the live refusal: the same shape the researcher returned, reduced to the
    # refused values. Before this fix the schema admitted it and only packet_from_research refused.
    live = {**RESEARCH,
            "claims": [{"id": "c" + str(i), "kind": kind, "text": "process commentary", "source_ids": ["s1"]}
                       for i, kind in enumerate(LIVE_REJECTED_KINDS, 1)],
            "questions": [{"id": "q1", "question": "does the future CI pass?", "blocking": True, "status": LIVE_REJECTED_STATUS,
                           "claim_ids": ["c1"]}]}
    result = schema_check("researcher", live)
    assert result["answer"] is None and result["failure"]["output_reason"] == "schema_mismatch"
    assert result["failure"]["instance_path"] == ["claims", 0, "kind"]
    with pytest.raises(PacketError, match="known kind"):
        packet_from_research(MANIFEST, live)
    only_status = {**RESEARCH, "questions": [{**RESEARCH["questions"][0], "status": LIVE_REJECTED_STATUS}]}
    assert schema_check("researcher", only_status)["failure"]["instance_path"] == ["questions", 0, "status"]
    with pytest.raises(PacketError, match="answered or unknown"):
        packet_from_research(MANIFEST, only_status)
    # The consumer is unchanged: a blocking design unknown is still refused (research first), while a
    # non-blocking unknown about a future test is carried as an unknown claim.
    blocking_unknown = {**RESEARCH, "questions": [{**RESEARCH["questions"][1], "blocking": True}]}
    assert schema_check("researcher", blocking_unknown)["answer"] == blocking_unknown
    with pytest.raises(PacketError, match="blocking unresolved"):
        packet_from_research(MANIFEST, blocking_unknown)


@pytest.mark.parametrize("decision", sorted(SSOT_DECISIONS))
def test_every_ssot_decision_the_schema_admits_is_consumed(decision):
    ssot = {**RESEARCH["ssot"], "decision": decision,
            "authoritative_definition": None if decision == "new" else "domain/dge.py",
            "transition": TRANSITION if decision in {"improve", "migrate"} else None}
    output = {**RESEARCH, "ssot": ssot}
    assert schema_check("researcher", output)["answer"] == output
    assert packet_from_research(MANIFEST, output)["ssot"]["decision"] == decision


def test_every_severity_verdict_and_disposition_the_schema_admits_is_consumed_under_the_debate_rules():
    for severity in sorted(SEVERITIES):
        finding = CRITICAL if severity == "critical" else MINOR
        assert consume("attacker", {"findings": [finding]})["findings"][0]["severity"] == severity
    unsupported = {**CRITICAL, "trigger": None}
    assert schema_check("attacker", {"findings": [unsupported]})["answer"], "the schema admits it; the host rule refuses it"
    with pytest.raises(ContractError, match="concrete trigger"):
        consume("attacker", {"findings": [unsupported]})
    for verdict in sorted(VERDICTS):
        dispositions = [{"finding_id": "f1", "decision": "blocking" if verdict != "accept" else "resolved", "reason": "r"},
                        {"finding_id": "f2", "decision": "deferred", "reason": "backlog"}]
        output = {"verdict": verdict, "rationale": "r", "dispositions": dispositions,
                  "research_question": "what else?" if verdict == "needs_research" else None}
        assert schema_check("arbiter", output)["answer"] == output
        assert consume("arbiter", output)["verdict"] == verdict
    for decision in sorted(DECISIONS):
        output = {"verdict": "reject", "rationale": "r", "research_question": None,
                  "dispositions": [{"finding_id": "f1", "decision": decision if decision != "deferred" else "resolved", "reason": "r"},
                                   {"finding_id": "f2", "decision": decision, "reason": "r"}]}
        assert consume("arbiter", output)["dispositions"][1]["decision"] == decision
    deferred_critical = {**ROLE_OUTPUTS["arbiter"], "dispositions": [{"finding_id": "f1", "decision": "deferred", "reason": "later"},
                                                                     {"finding_id": "f2", "decision": "resolved", "reason": "r"}]}
    assert schema_check("arbiter", deferred_critical)["answer"], "the enum admits deferred; the debate rule refuses it for a critical"
    with pytest.raises(EventError, match="cannot defer a critical"):
        consume("arbiter", deferred_critical)


def test_schema_validation_is_the_same_dialect_the_runner_reports():
    for role in ROLE_ORDER:
        Draft202012Validator.check_schema(SCHEMAS[role])
        assert not list(Draft202012Validator(SCHEMAS[role]).iter_errors(ROLE_OUTPUTS[role])), role
