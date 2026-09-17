"""Producer/consumer contract for the council role schemas (INV-COUNCIL-001). Labelled fixtures only;
no model is called."""
import pytest
from jsonschema import Draft202012Validator
from test_autonomous_roles import CRITICAL, MINOR, ROLE_OUTPUTS

from codex_harness.adapters.autonomous_roles import OBJECTIVES, SCHEMAS
from codex_harness.adapters.execution_output import completed_output
from codex_harness.adapters.output_schema import preflight
from codex_harness.domain.autonomous import ROLE_AGENTS, event_from_role
from codex_harness.domain.council import (
    AGENTS,
    COUNCIL_AGENTS,
    COUNCIL_ORDER,
    INTERNAL_SLOT,
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
    result = schema_check(role, OUTPUTS[role])
    assert result["answer"] == OUTPUTS[role], result.get("failure")
    assert "snapshot_digest" in OBJECTIVES[role] or role == "dba"
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
