"""Producer/consumer contract for the council role schemas (INV-COUNCIL-001). Labelled fixtures only;
no model is called."""
import pytest
from jsonschema import Draft202012Validator
from test_autonomous_roles import CRITICAL, MINOR, ROLE_OUTPUTS

from codex_harness.adapters.autonomous_roles import OBJECTIVES, SCHEMAS, role_objective
from codex_harness.adapters.execution_output import completed_output
from codex_harness.adapters.output_schema import preflight
from codex_harness.domain.autonomous import ROLE_AGENTS, event_from_role
from codex_harness.domain.council import (
    AGENTS,
    COUNCIL_AGENTS,
    COUNCIL_ORDER,
    FIELD_CODE,
    FIELD_LIMITS,
    INTERNAL_SLOT,
    CouncilFieldRefused,
    council_output,
    report_from_dba,
    topology,
)
from codex_harness.domain.dge import SEVERITIES, validate_event, validate_payload
from codex_harness.domain.model import ContractError, canonical

SNAP, REPORT = "1" * 64, "2" * 64
IDS = {"snapshot_digest": SNAP, "report_digest": REPORT}
CLAIMS = {"c1", "c2"}  # the frozen packet's claim ids (fixture)
TRANSITION = {"compatibility": "additive", "rollback": "revert", "retirement": "none"}
OUTPUTS = {"dba": {"snapshot_digest": SNAP, "summary": "records observed", "claim_ids": ["c1"], "unknowns": []},
           "research_lead": {**ROLE_OUTPUTS["proposer"], **IDS},
           "improvement_lead": {"summary": "alternative", "decision": "migrate", "rationale": "r", "transition": TRANSITION,
                                "claim_ids": ["c1"], "findings": [CRITICAL, MINOR], **IDS},
           "conductor": {**ROLE_OUTPUTS["arbiter"], **IDS}}


def schema_check(role, output):
    return completed_output(canonical(output), SCHEMAS[role])


def test_council_agents_are_real_identities_and_map_onto_the_internal_slots():
    assert COUNCIL_AGENTS == {"researcher": "lead:researcher", "dba": "lead:dba", "research_lead": "lead:research",
                              "improvement_lead": "lead:improvement", "conductor": "conductor"}
    assert AGENTS == {**ROLE_AGENTS, **COUNCIL_AGENTS} and ROLE_AGENTS == {r: "lead:" + r for r in ("researcher", "proposer", "attacker", "arbiter")}
    assert INTERNAL_SLOT == {"research_lead": "proposer", "improvement_lead": "attacker", "conductor": "arbiter"}
    view = topology()
    assert [r for r in view["roles"]] == list(COUNCIL_ORDER) and view["roles"]["conductor"]["slot"] == "arbiter"
    assert all(view["roles"][r]["agent"] == COUNCIL_AGENTS[r] for r in COUNCIL_ORDER)


@pytest.mark.parametrize("role", ["dba", "research_lead", "improvement_lead", "conductor"])
def test_council_output_passes_the_schema_preflight_and_the_consumer(role):
    Draft202012Validator.check_schema(SCHEMAS[role])
    receipt = preflight(SCHEMAS[role])
    assert receipt["checks"] and not {"if", "then", "else", "allOf"} & set(receipt["keywords"])
    # The researcher's typed claim/question alternatives do not leak into the council contracts: no anyOf, no
    # questions field, and the objective carries no packet reference rule (packet producer alignment batch).
    assert "anyOf" not in receipt["keywords"] and "questions" not in SCHEMAS[role]["properties"]
    assert "Self-check every answered question" not in OBJECTIVES[role]
    result = schema_check(role, OUTPUTS[role])
    assert result["answer"] == OUTPUTS[role], result.get("failure")
    assert "snapshot_digest" in OBJECTIVES[role] or role == "dba"
    # urn:zeus:council-input:2: the producers' static text names no hard byte cap; the executed objective adds
    # the allowance computed from the earlier payloads in the task details (the conductor produces no payload).
    assert "UTF-8 bytes" not in OBJECTIVES[role]
    earlier = {"packet": {"claims": []}, "dba_report": OUTPUTS["dba"], "research_proposal": OUTPUTS["research_lead"]}
    executed = role_objective(role, earlier)
    assert executed.startswith(OBJECTIVES[role])
    assert ("UTF-8 bytes of canonical JSON" in executed) == (role != "conductor"), role
    if role == "dba":
        assert report_from_dba(OUTPUTS[role], snapshot_digest_value=SNAP, claim_ids={"c1"})["claim_ids"] == ["c1"]
        return
    derived = council_output(role, OUTPUTS[role], IDS, CLAIMS)
    slot = INTERNAL_SLOT[role]
    event = validate_event(event_from_role(slot, derived["event_payload"], "3" * 64, 1, "task-" + role))
    payload = validate_payload(slot, event["payload"], claim_ids={"c1", "c2"}, criteria=[CRITICAL["criterion"]], findings=[CRITICAL, MINOR])
    if role == "improvement_lead":
        assert [f["severity"] for f in payload["findings"]] == sorted(SEVERITIES) and derived["proposal"]["decision"] == "migrate"
        assert derived["proposal"]["transition"] == TRANSITION, "the full proposal survives next to the findings-only event"
    if role == "conductor":
        assert payload["verdict"] == "accept" and set(derived["event_payload"]) == {"verdict", "rationale", "dispositions", "research_question"}


def test_swapped_identities_missing_transition_and_unsupported_critical_are_refused():
    for role in ("research_lead", "improvement_lead", "conductor"):
        with pytest.raises(ContractError, match="council_identity_mismatch"):
            council_output(role, {**OUTPUTS[role], "report_digest": "9" * 64}, IDS, CLAIMS)
        with pytest.raises(ContractError, match="council_identity_mismatch"):
            council_output(role, OUTPUTS[role], {**IDS, "snapshot_digest": "9" * 64}, CLAIMS)
        with pytest.raises(ContractError, match="required fields"):
            council_output(role, {k: v for k, v in OUTPUTS[role].items() if k != "snapshot_digest"}, IDS, CLAIMS)
    with pytest.raises(ContractError, match="compatibility, rollback and retirement"):
        council_output("improvement_lead", {**OUTPUTS["improvement_lead"], "transition": None}, IDS, CLAIMS)
    with pytest.raises(ContractError, match="must be null"):
        council_output("improvement_lead", {**OUTPUTS["improvement_lead"], "decision": "reuse"}, IDS, CLAIMS)
    assert council_output("improvement_lead", {**OUTPUTS["improvement_lead"], "decision": "new", "transition": None, "findings": []}, IDS, CLAIMS)["event_payload"] == {"findings": []}, "no compulsory objection"
    with pytest.raises(ContractError, match="concrete trigger"):
        council_output("improvement_lead", {**OUTPUTS["improvement_lead"], "findings": [{**CRITICAL, "trigger": None}]}, IDS, CLAIMS)
    # Unknown packet claim ids cannot ride in on the alternative (it never reaches the DGE payload validator).
    for role in ("research_lead", "improvement_lead"):
        with pytest.raises(ContractError, match="claim_ids must be distinct known packet claim ids"):
            council_output(role, {**OUTPUTS[role], "claim_ids": ["c1", "c404"]}, IDS, CLAIMS)
    # One authoritative conversion: the derived payload still carries the materiality fields for event_from_role.
    raw = council_output("improvement_lead", OUTPUTS["improvement_lead"], IDS, CLAIMS)["event_payload"]["findings"][0]
    assert raw == CRITICAL and event_from_role("attacker", {"findings": [raw]}, "3" * 64, 1, "t")["payload"]["findings"][0]["scenario"] \
        .count("trigger: ") == 1
    with pytest.raises(ContractError, match="Unknown council role"):
        council_output("dba", OUTPUTS["dba"], IDS, CLAIMS)
    bad = schema_check("improvement_lead", {**OUTPUTS["improvement_lead"], "decision": "keep"})
    assert bad["answer"] is None and bad["failure"]["output_reason"] == "schema_mismatch" and "keep" not in str(bad["failure"])


# ----- council field bounds (SPEC "Settled council contract failure recovery") ---------------------------
# ACTUAL-SHAPED fixture: release-checklist-research-001.c001's improvement lead returned a 6046-character
# summary; the domain replay refused it against the 4000 bound. The text below is a LABELLED stand-in of that
# length (the original bytes are not in this repository); no model is called.
ORIGINAL6046 = ("SECRET-summary-body " * 400)[:6046]
BOUNDED = {("dba", "summary"): lambda o, v: {**o, "summary": v},
           ("dba", "unknowns"): lambda o, v: {**o, "unknowns": ["known gap", v]},
           ("improvement_lead", "summary"): lambda o, v: {**o, "summary": v},
           ("improvement_lead", "rationale"): lambda o, v: {**o, "rationale": v},
           **{("improvement_lead", "transition." + k): (lambda key: lambda o, v: {**o, "transition": {**o["transition"], key: v}})(k)
              for k in ("compatibility", "rollback", "retirement")}}


def consume(role, output):
    if role == "dba":
        return report_from_dba(output, snapshot_digest_value=SNAP, claim_ids={"c1"})
    return council_output(role, output, IDS, CLAIMS)


def test_the_bounded_fields_are_one_table_for_the_consumer_the_schema_and_the_guidance():
    assert set(BOUNDED) == {(role, field) for role, fields in FIELD_LIMITS.items() for field in fields}
    assert FIELD_LIMITS["improvement_lead"]["summary"] == 4000, "the consumer bound is kept, never raised"
    for (role, field), limit in ((k, FIELD_LIMITS[k[0]][k[1]]) for k in BOUNDED):
        node = SCHEMAS[role]["properties"]
        for part in field.split("."):
            node = node[part]["properties"] if "properties" in node.get(part, {}) else node[part]
        node = node["items"] if field == "unknowns" else node
        assert node["type"] == "string" and node["description"].startswith("At most " + str(limit) + " characters")
        assert "maxLength" not in node, "the bound is stated as an annotation; the consumer stays the authority"
        assert field + " at most " + str(limit) + " characters" in OBJECTIVES[role]
    # Text the DGE validator owns keeps plain TEXT: nothing unrelated is shrunk.
    assert SCHEMAS["research_lead"]["properties"]["summary"] == {"type": "string"}
    assert SCHEMAS["conductor"]["properties"]["rationale"] == {"type": "string"}
    assert SCHEMAS["improvement_lead"]["properties"]["findings"]["items"]["properties"]["scenario"] == {"type": "string"}
    for role in ("dba", "improvement_lead"):
        assert preflight(SCHEMAS[role])["checks"]


@pytest.mark.parametrize("role, field", sorted(BOUNDED))
def test_each_bounded_field_admits_its_limit_and_refuses_one_more_with_a_fixed_code(role, field):
    limit, build = FIELD_LIMITS[role][field], BOUNDED[(role, field)]
    assert consume(role, build(OUTPUTS[role], "y" * limit)), "the boundary value is admitted"
    assert consume(role, build(OUTPUTS[role], " " + "y" * limit + "\n")), "the existing trimmed-length rule is kept"
    for value, problem in (("y" * (limit + 1), "too_long"), ("  ", "empty"), (7, "type")):
        with pytest.raises(CouncilFieldRefused) as info:
            consume(role, build(OUTPUTS[role], value))
        code = role + "." + field + ":" + problem
        assert info.value.reason_code == "council_field_invalid:" + code and FIELD_CODE.fullmatch(info.value.reason_code)
        assert "yyyy" not in str(info.value), "the refused value is never echoed"
        # A schema-valid value the consumer refuses: the provider boundary states the bound, it does not coerce.
        if role == "improvement_lead" and problem == "too_long":
            assert schema_check(role, build(OUTPUTS[role], value))["answer"] is not None


def test_the_original6046_summary_is_a_deterministic_safe_refusal_not_a_truncation():
    output = {**OUTPUTS["improvement_lead"], "summary": ORIGINAL6046}
    codes = set()
    for _ in range(3):
        with pytest.raises(CouncilFieldRefused) as info:
            council_output("improvement_lead", output, IDS, CLAIMS)
        codes.add(info.value.reason_code)
        assert "SECRET-summary-body" not in str(info.value)
        # The legacy message is kept for existing readers; the code is appended.
        assert str(info.value).startswith("Improvement lead proposal needs a summary, a rationale and a decision")
    assert codes == {"council_field_invalid:improvement_lead.summary:too_long"}
    assert output["summary"] == ORIGINAL6046 and len(output["summary"]) == 6046, "the output is not rewritten"
    # A wrong decision is still the generic refusal (it is not a bounded text field).
    with pytest.raises(ContractError) as info:
        council_output("improvement_lead", {**output, "decision": "keep"}, IDS, CLAIMS)
    assert not isinstance(info.value, CouncilFieldRefused)
