"""urn:zeus:council-input:2 boundaries (research-program-001, Implementation013: shared pool with ordered future
reservations, replacing the v1 isolated section ceilings).

Every fixture here is SYNTHETIC and labelled. No model runs: the executor tests use the prompt-recording fake
runtime of test_council_delivery, the council-run tests use the FakeExecutor of test_council with INJECTED
oversized role outputs. Sizes are UTF-8 bytes of canonical JSON, the policy's own unit; they prove deterministic
admission and refusal, never model comprehension. The live005 case below is a SIZE-EQUIVALENT synthetic
reconstruction (11965/1677/4260 bytes); the owner replays the actual raw data separately.
"""
import copy
import hashlib
import json

import pytest
import test_council
from test_autonomous import RESEARCH, ROLE_OUTPUTS
from test_council import DBA_REPORT, IMPROVEMENT, CouncilExecutor, build, valid
from test_council_delivery import (  # noqa: F401  `representative` is a pytest fixture: importing it registers it here
    BASE,
    CONDUCTOR_ANSWER,
    KOREAN,
    deliver,
    details_for,
    harness,
    representative,
    task_for,
)
from test_operation import BOUND_GOAL, IDENTITY

from codex_harness.adapters.autonomous_roles import (
    COUNCIL_DEBATE_ROLES,
    OBJECTIVES,
    council_delivery,
    execute_role,
    role_objective,
    role_schema,
)
from codex_harness.adapters.executor import VERDICT
from codex_harness.domain.autonomous import packet_from_research
from codex_harness.domain.council import AGENTS
from codex_harness.domain.council_input import (
    LIMITS,
    ORDER,
    PAYLOAD_POOL,
    PRODUCERS,
    RESERVATIONS,
    ROLE_PREFIX,
    SCHEMA,
    UNIT,
    CouncilInputOverflow,
    admit,
    admit_delivery,
    admit_prefix,
    admit_required,
    allowance,
    canonical_bytes,
    council_budget,
    output_limit,
    policy_manifest,
    preceding,
)
from codex_harness.domain.model import ContractError, canonical
from codex_harness.domain.observation import REGISTRY, check_attributes

ESCAPED = 'quote " backslash \\ newline \n tab \t '  # JSON escaping adds bytes the policy must count
PAYLOAD = ORDER
PACKET, DBA, RESEARCH_PROPOSAL, IMPROVEMENT_PROPOSAL = ORDER
LATER = {s: sum(RESERVATIONS[t] for t in ORDER[i + 1:]) for i, s in enumerate(ORDER)}   # reservations after each stage
# SYNTHETIC size match to the owner's live005 measurement (RESULT-005): the actual producer refused 4260 against
# the v1 4096 ceiling although 11965 + 1677 + 4260 + 8192 (future) is far below the pool.
LIVE005 = {PACKET: 11965, DBA: 1677, RESEARCH_PROPOSAL: 4260}
FILL_PATH = {PACKET: ["claims", 3, "text"], DBA: ["summary"], RESEARCH_PROPOSAL: ["summary"],
             IMPROVEMENT_PROPOSAL: ["findings", 0, "scenario"]}


def fill(obj, path, cap, prefix="", multibyte=False):
    """Deep copy of `obj` whose canonical UTF-8 size is EXACTLY `cap`: the string at `path` becomes `prefix`
    plus a filler of Korean (3 bytes each) and/or ASCII characters. Filler characters are never escaped."""
    out = copy.deepcopy(obj)
    target = out
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = prefix
    room = cap - canonical_bytes(out)
    assert room >= 0, room
    target[path[-1]] = prefix + (("한" * (room // 3) + "y" * (room % 3)) if multibyte else "y" * room)
    assert canonical_bytes(out) == cap, (canonical_bytes(out), cap)
    return out


def sized(section, size, prefix="", multibyte=False):
    """SYNTHETIC minimal component of exactly `size` bytes."""
    return fill({"id": section, "text": ""}, ["text"], size, prefix, multibyte)


# Earlier-stage size distributions: every earlier component exactly at its reservation, or the packet small so
# that its unused bytes flow downstream to the component under test.
DISTRIBUTIONS = {"reserved": lambda s: RESERVATIONS[s], "shifted": lambda s: 2048 if s == PACKET else RESERVATIONS[s]}
VARIANTS = {"ascii": ("", False), "multibyte": ("", True), "escaped": (ESCAPED, False), "escaped_multibyte": (ESCAPED, True)}


def earlier_of(section, distribution, prefix="", multibyte=False):
    return {s: sized(s, DISTRIBUTIONS[distribution](s), prefix, multibyte) for s in preceding(section)}


def grown(obj, path, extra="!"):
    out = copy.deepcopy(obj)
    target = out
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] += extra
    return out


# ----- policy -------------------------------------------------------------------------------------
def test_policy_manifest_names_reservations_in_one_pool_the_fixed_overheads_the_council_window_and_the_legacy_pair():
    manifest = policy_manifest()
    assert manifest["schema"] == SCHEMA == "urn:zeus:council-input:2" and manifest["previous"] == "urn:zeus:council-input:1"
    assert manifest["unit"] == UNIT and manifest["order"] == list(ORDER) == ["packet", "dba_report", "research_proposal", "improvement_proposal"]
    assert manifest["reservations"] == RESERVATIONS == {"packet": 16384, "dba_report": 4096, "research_proposal": 4096, "improvement_proposal": 8192}
    assert sum(RESERVATIONS.values()) == PAYLOAD_POOL == manifest["payload_pool"] == 32768, "reservations exactly fill the pool"
    assert manifest["limits"] == LIMITS == {"delivery_overhead": 4096, "host_overhead": 4096, "required": 40960}
    assert not set(LIMITS) & set(ORDER), "payload numbers are reservations, not limits"
    assert PAYLOAD_POOL + LIMITS["delivery_overhead"] + LIMITS["host_overhead"] == LIMITS["required"] == manifest["usable"]
    assert council_budget() == (manifest["window"], manifest["reserved"]) == (49152, 8192)
    assert manifest["legacy"] == {"window": 28000, "reserved": 6000}
    assert "not model tokens" in manifest["note"] and "reservations" in manifest["note"]
    assert ROLE_PREFIX == {"research_lead": ORDER[:2], "improvement_lead": ORDER[:3], "conductor": ORDER}
    for bad in (lambda: admit("bogus", {}, {}), lambda: output_limit("bogus", {}), lambda: CouncilInputOverflow("bogus", 1, 0),
                lambda: preceding("bogus"), lambda: allowance("bogus", {})):
        with pytest.raises(ContractError, match="Unknown council input section"):
            bad()
    # Initial allowances equal the reservations; the researcher's objective states its (fixed) initial allowance.
    assert [allowance(s, earlier_of(s, "reserved")) for s in ORDER] == [16384, 4096, 4096, 8192]
    assert output_limit(PACKET, {}) in OBJECTIVES["researcher"] and "16384 UTF-8 bytes" in OBJECTIVES["researcher"]
    assert "urn:zeus:autonomous:2" in OBJECTIVES["researcher"] and "never drop or relabel" in OBJECTIVES["researcher"]


def test_producer_objectives_carry_the_allowance_computed_by_the_same_rule_from_the_exact_earlier_payloads():
    details = details_for("conductor")   # carries packet, dba_report and research_proposal
    for section, role in PRODUCERS.items():
        if role == "researcher":
            continue
        assert "UTF-8 bytes" not in OBJECTIVES[role] and "4096" not in OBJECTIVES[role], "no static hard cap in the role text"
        earlier = {k: details[k] for k in preceding(section)}
        objective = role_objective(role, details)
        assert objective == OBJECTIVES[role] + " " + output_limit(section, earlier)
        room = allowance(section, earlier)
        assert room > RESERVATIONS[section] and str(room) + " UTF-8 bytes" in objective, (role, room)
        assert str(sum(canonical_bytes(v) for v in earlier.values())) + " bytes committed by earlier stages" in objective
        assert "never drop or relabel" in objective and str(LATER[section]) + " bytes reserved for later stages" in objective
    assert "normalizes" in role_objective("dba", details) and "derives" in role_objective("research_lead", details)
    assert "every finding included" in role_objective("improvement_lead", details)
    # A small packet leaves the research lead far more than the retired 4096 ceiling; the number is the domain's.
    assert allowance(RESEARCH_PROPOSAL, {PACKET: details[PACKET], DBA: details[DBA]}) == \
        32768 - canonical_bytes(details[PACKET]) - canonical_bytes(details[DBA]) - 8192
    # Non-producers keep their static objective; a missing earlier payload is a contract error, never "empty".
    assert role_objective("conductor", details) == OBJECTIVES["conductor"] and role_objective("proposer", {}) == OBJECTIVES["proposer"]
    with pytest.raises(ContractError, match="needs exactly the earlier components: packet, dba_report") as info:
        role_objective("research_lead", {k: v for k, v in details.items() if k != "dba_report"})
    assert not isinstance(info.value, CouncilInputOverflow)


# ----- producer prefix matrix: every stage, exact allowance / allowance+1, ASCII, multi-byte and escaped ----
@pytest.mark.parametrize("section", PAYLOAD)
@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("distribution", sorted(DISTRIBUTIONS))
def test_exact_allowance_is_admitted_and_one_more_byte_is_the_typed_overflow_with_safe_diagnostics(section, variant, distribution):
    prefix, multibyte = VARIANTS[variant]
    earlier = earlier_of(section, distribution, prefix, multibyte)
    spent = sum(canonical_bytes(v) for v in earlier.values())
    room = allowance(section, earlier)
    assert room == PAYLOAD_POOL - spent - LATER[section], "pool minus actual earlier bytes minus later reservations"
    assert room == RESERVATIONS[section] if distribution == "reserved" or section == PACKET else room > RESERVATIONS[section]
    exact = sized(section, room, prefix, multibyte)
    assert admit(section, exact, earlier) == room
    measured = admit_prefix({**earlier, section: exact})
    assert measured["sections"][section] == room and measured["payload_bytes"] == spent + room
    assert measured["reserved_bytes"] == LATER[section] and measured["payload_bytes"] + measured["reserved_bytes"] <= PAYLOAD_POOL
    assert measured["schema"] == SCHEMA and measured["payload_pool"] == 32768
    if multibyte:
        assert len(canonical(exact)) < room, "characters are not bytes: the policy counts encoded bytes"
    if prefix:
        assert '\\"' in canonical(exact) and "\\n" in canonical(exact) and "\\\\" in canonical(exact), "escaped forms are measured"
    over = {**exact, "text": exact["text"] + "!"}
    assert canonical_bytes(over) == room + 1
    with pytest.raises(CouncilInputOverflow) as info:
        admit(section, over, earlier)
    exc = info.value
    assert isinstance(exc, ContractError) and (exc.section, exc.observed, exc.limit) == (section, room + 1, room)
    assert str(exc) == exc.reason_code == "needs_scope_split:" + section + ":" + str(room + 1) + "/" + str(room)
    assert exc.diagnostics() == {"schema": SCHEMA, "reason": "needs_scope_split", "section": section,
                                 "observed_bytes": room + 1, "limit_bytes": room, "unit": UNIT}
    assert "yyyy" not in str(exc) and "한" not in json.dumps(exc.diagnostics(), ensure_ascii=False), "no content leaks"
    assert over["text"].endswith("!"), "the value is never modified"
    # Pure calculation: an independent repeat neither borrows nor loses credit.
    assert admit(section, exact, earlier) == room and allowance(section, earlier) == room


def test_prefix_rule_rejects_holes_unknown_keys_out_of_order_stages_and_future_values_as_contract_errors():
    values = {s: sized(s, 100) for s in ORDER}
    cases = [(lambda: admit_prefix({}), "prefix is empty"),
             (lambda: admit_prefix("text"), "must be an object"),
             (lambda: admit_prefix({PACKET: values[PACKET], "bogus": {}}), "Unknown council input section: bogus"),
             (lambda: admit_prefix({DBA: values[DBA]}), "Council input missing: packet"),
             (lambda: admit_prefix({PACKET: values[PACKET], RESEARCH_PROPOSAL: values[RESEARCH_PROPOSAL]}), "Council input missing: dba_report"),
             (lambda: admit_prefix({PACKET: values[PACKET], IMPROVEMENT_PROPOSAL: values[IMPROVEMENT_PROPOSAL]}),
              "Council input missing: dba_report, research_proposal"),
             # A producer must hand in exactly its earlier components: none missing, none pretended empty, none later.
             (lambda: admit(DBA, values[DBA], {}), "for dba_report needs exactly the earlier components: packet"),
             (lambda: admit(PACKET, values[PACKET], {DBA: values[DBA]}), "for packet needs exactly the earlier components: none"),
             (lambda: admit(RESEARCH_PROPOSAL, values[RESEARCH_PROPOSAL], {PACKET: values[PACKET], DBA: values[DBA],
                                                                            IMPROVEMENT_PROPOSAL: values[IMPROVEMENT_PROPOSAL]}),
              "for research_proposal needs exactly the earlier components: packet, dba_report"),
             (lambda: admit(RESEARCH_PROPOSAL, values[RESEARCH_PROPOSAL], {PACKET: values[PACKET], RESEARCH_PROPOSAL: values[RESEARCH_PROPOSAL]}),
              "needs exactly the earlier components"),
             (lambda: allowance(IMPROVEMENT_PROPOSAL, {PACKET: values[PACKET]}), "for improvement_proposal needs exactly"),
             (lambda: allowance(PACKET, [values[PACKET]]), "must be an object"),
             (lambda: admit(DBA, values[DBA], {PACKET: values[PACKET], "bogus": 1}), "needs exactly the earlier components")]
    for bad, message in cases:
        with pytest.raises(ContractError, match=message) as info:
            bad()
        assert not isinstance(info.value, CouncilInputOverflow), message
    # Future values never affect a producer's allowance: only the earlier prefix is an input.
    assert allowance(DBA, {PACKET: values[PACKET]}) == 32768 - 100 - 12288 == allowance(DBA, {PACKET: values[PACKET]})


def test_earlier_unused_bytes_flow_downstream_but_future_reservations_are_never_spent_twice():
    small = sized(PACKET, 2000)
    assert allowance(DBA, {PACKET: small}) == 18480 == 32768 - 2000 - 4096 - 8192
    big_report = sized(DBA, 18480)
    assert admit(DBA, big_report, {PACKET: small}) == 18480
    # After the report spent the packet's unused bytes, both later components keep exactly their reservations.
    assert allowance(RESEARCH_PROPOSAL, {PACKET: small, DBA: big_report}) == 4096
    proposal = sized(RESEARCH_PROPOSAL, 4096)
    assert allowance(IMPROVEMENT_PROPOSAL, {PACKET: small, DBA: big_report, RESEARCH_PROPOSAL: proposal}) == 8192
    with pytest.raises(CouncilInputOverflow) as info:
        admit(RESEARCH_PROPOSAL, sized(RESEARCH_PROPOSAL, 4097), {PACKET: small, DBA: big_report})
    assert (info.value.section, info.value.observed, info.value.limit) == (RESEARCH_PROPOSAL, 4097, 4096)
    # A packet over its own allowance is refused by every later prefix too: no later stage rescues an earlier one.
    over = sized(PACKET, 16385)
    for stage in (1, 2, 4):
        with pytest.raises(CouncilInputOverflow) as info:
            admit_prefix({PACKET: over, **{s: sized(s, 100) for s in ORDER[1:stage]}})
        assert (info.value.section, info.value.observed, info.value.limit) == (PACKET, 16385, 16384)
    with pytest.raises(CouncilInputOverflow) as info:
        allowance(DBA, {PACKET: over})   # the earlier prefix is re-admitted, never trusted
    assert info.value.section == PACKET
    # Exact pool: the complete prefix spends the whole pool without per-component ceilings.
    full = {PACKET: sized(PACKET, 1000), DBA: sized(DBA, 1000), RESEARCH_PROPOSAL: sized(RESEARCH_PROPOSAL, 1000),
            IMPROVEMENT_PROPOSAL: sized(IMPROVEMENT_PROPOSAL, 29768)}
    assert admit_prefix(full)["payload_bytes"] == 32768 and admit_prefix(full)["reserved_bytes"] == 0
    with pytest.raises(CouncilInputOverflow) as info:
        admit_prefix({**full, IMPROVEMENT_PROPOSAL: sized(IMPROVEMENT_PROPOSAL, 29769)})
    assert (info.value.section, info.value.observed, info.value.limit) == (IMPROVEMENT_PROPOSAL, 29769, 29768)


def test_live005_size_equivalent_case_is_admitted_at_every_stage_with_the_future_improvement_reservation_kept():
    # SYNTHETIC size-equivalent reconstruction, not the retained raw data: the owner replays that separately.
    committed = {}
    for section, size in LIVE005.items():
        value = sized(section, size, ESCAPED, True)
        assert admit(section, value, committed) == size
        committed[section] = value
    measured = admit_prefix(committed)
    assert measured["sections"] == LIVE005 and measured["payload_bytes"] == 17902 and measured["reserved_bytes"] == 8192
    assert measured["payload_bytes"] + measured["reserved_bytes"] == 26094 <= PAYLOAD_POOL
    assert allowance(RESEARCH_PROPOSAL, {k: committed[k] for k in ORDER[:2]}) == 32768 - 11965 - 1677 - 8192 == 10934 >= 4260
    assert allowance(IMPROVEMENT_PROPOSAL, committed) == 32768 - 17902 == 14866 >= 8192, "later 8192 stays admissible"
    assert admit(IMPROVEMENT_PROPOSAL, sized(IMPROVEMENT_PROPOSAL, 8192), committed) == 8192
    assert admit(IMPROVEMENT_PROPOSAL, sized(IMPROVEMENT_PROPOSAL, 14866), committed) == 14866
    with pytest.raises(CouncilInputOverflow) as info:
        admit(IMPROVEMENT_PROPOSAL, sized(IMPROVEMENT_PROPOSAL, 14867), committed)
    assert (info.value.observed, info.value.limit) == (14867, 14866)


# ----- delivery (wrapper) and required (host) admission ---------------------------------------------
def test_delivery_admission_binds_the_role_prefix_measures_wrapper_exactly_and_keeps_shape_errors_distinct():
    details = details_for("conductor")
    delivery = council_delivery("conductor", details)
    measure = admit_delivery(delivery, "conductor")
    inline = delivery["inline"]
    assert measure["sections"] == {k: canonical_bytes(inline[k]) for k in PAYLOAD} and measure["role"] == "conductor"
    assert measure["sections"]["packet"] == canonical_bytes(details["packet"]), "the exact task value is measured"
    assert measure["delivery_bytes"] == canonical_bytes(delivery) == len(canonical(delivery).encode("utf-8"))
    assert measure["delivery_overhead_bytes"] == measure["delivery_bytes"] - sum(measure["sections"].values())
    assert measure["payload_bytes"] == sum(measure["sections"].values()) and measure["reserved_bytes"] == 0
    # Exactness of the subtraction: the wrapper with every component emptied to "" is the overhead plus the quotes.
    emptied = copy.deepcopy(delivery)
    for key in PAYLOAD:
        emptied["inline"][key] = ""
    assert canonical_bytes(emptied) == measure["delivery_overhead_bytes"] + 2 * len(PAYLOAD)
    assert delivery["input_policy"] == SCHEMA and measure["schema"] == SCHEMA
    lead = admit_delivery(council_delivery("research_lead", details_for("research_lead")), "research_lead")
    assert set(lead["sections"]) == {"packet", "dba_report"} and lead["reserved_bytes"] == 12288, "early roles keep future reservations"
    improve = admit_delivery(council_delivery("improvement_lead", details_for("improvement_lead")), "improvement_lead")
    assert set(improve["sections"]) == {"packet", "dba_report", "research_proposal"} and improve["reserved_bytes"] == 8192
    # Missing component, shape, role binding or an injected future component: a ContractError that is NOT an overflow.
    injected = copy.deepcopy(council_delivery("research_lead", details_for("research_lead")))
    injected["inline"]["improvement_proposal"] = details["improvement_proposal"]
    for document, role, message in (({"inline": {"role": "conductor", "packet": {}}}, "conductor",
                                     "Council input missing: dba_report, research_proposal, improvement_proposal"),
                                    ({"schema": "x"}, "conductor", "inline object"), ("text", "conductor", "inline object"),
                                    (delivery, "research_lead", "delivery role mismatch"), (delivery, "dba", "names no debate role"),
                                    (injected, "research_lead", "beyond the research_lead prefix: improvement_proposal")):
        with pytest.raises(ContractError, match=message) as info:
            admit_delivery(document, role)
        assert not isinstance(info.value, CouncilInputOverflow)
    # Wrapper boundary: exactly 4096 bytes of overhead is admitted, one more byte is the typed overflow.
    room = LIMITS["delivery_overhead"] - measure["delivery_overhead_bytes"]
    exact = {**delivery, "guidance": delivery["guidance"] + "g" * room}
    assert admit_delivery(exact, "conductor")["delivery_overhead_bytes"] == 4096
    with pytest.raises(CouncilInputOverflow) as info:
        admit_delivery({**exact, "guidance": exact["guidance"] + "g"}, "conductor")
    assert (info.value.section, info.value.observed, info.value.limit) == ("delivery_overhead", 4097, 4096)


@pytest.mark.parametrize("role", COUNCIL_DEBATE_ROLES)
def test_consumer_projection_at_its_exact_prefix_bound_is_admitted_and_one_byte_over_is_refused(role):
    prefix = ROLE_PREFIX[role]
    details = details_for(role, claims=4, text_bytes=40)
    for section in prefix[:-1]:
        details[section] = fill(details[section], FILL_PATH[section], RESERVATIONS[section], ESCAPED, True)
    last = prefix[-1]
    room = allowance(last, {k: details[k] for k in prefix[:-1]})
    assert room == PAYLOAD_POOL - sum(RESERVATIONS[s] for s in prefix[:-1]) - LATER[last]
    details[last] = fill(details[last], FILL_PATH[last], room, ESCAPED, True)
    measured = admit_delivery(council_delivery(role, details), role)
    assert measured["payload_bytes"] + measured["reserved_bytes"] == PAYLOAD_POOL and measured["reserved_bytes"] == LATER[last]
    over = {**details, last: grown(details[last], FILL_PATH[last])}
    with pytest.raises(CouncilInputOverflow) as info:
        council_delivery(role, over)
    assert (info.value.section, info.value.observed, info.value.limit) == (last, room + 1, room)


def test_required_admission_bounds_the_host_overhead_and_the_whole_prompt():
    assert admit_required(40960, 36864) == {"schema": SCHEMA, "unit": UNIT, "required_bytes": 40960, "delivery_bytes": 36864,
                                            "host_overhead_bytes": 4096, "limit_bytes": 40960}
    with pytest.raises(CouncilInputOverflow) as info:
        admit_required(40961, 36865)  # host exactly 4096, whole prompt one byte over the usable window
    assert (info.value.section, info.value.observed, info.value.limit) == ("required", 40961, 40960)
    with pytest.raises(CouncilInputOverflow) as info:
        admit_required(5000, 903)
    assert (info.value.section, info.value.observed, info.value.limit) == ("host_overhead", 4097, 4096)
    for rendered, delivery in ((-1, 0), (10, 20), (10.0, 5), (True, 0), (10, -1)):
        with pytest.raises(ContractError, match="non-negative integers") as info:
            admit_required(rendered, delivery)
        assert not isinstance(info.value, CouncilInputOverflow)


# ----- producer gates through the real CouncilRun (FakeExecutor, INJECTED oversized outputs) ------------
def big_research():
    """INJECTED: valid claims (each under the DGE text limit) whose packet exceeds the 16384 initial allowance."""
    claims = [RESEARCH["claims"][0]] + [{"id": "c" + str(i), "kind": "fact", "text": "claim " + str(i) + " " + "x" * 3000,
                                          "source_ids": ["s1"]} for i in range(2, 9)]
    return {**RESEARCH, "claims": claims}


def research_sized(target: int) -> dict:
    """INJECTED: valid researcher output whose FROZEN packet (`packet_from_research` at the council manifest, the
    value the run admits) is EXACTLY `target` canonical bytes; the filler is split over two ASCII claims."""
    def frozen(first, second):
        research = {**RESEARCH, "claims": RESEARCH["claims"] + [
            {"id": "c2", "kind": "fact", "text": first, "source_ids": ["s1"]}, {"id": "c3", "kind": "fact", "text": second, "source_ids": ["s1"]}]}
        return research, canonical_bytes(packet_from_research(valid(), research)["packet"])
    _, base = frozen("f", "f")
    room = target - base
    assert room >= 0, room
    research, size = frozen("f" + "x" * min(room, 10000), "f" + "x" * max(room - 10000, 0))
    assert size == target, (size, target)
    return research


def rows(svc, bucket):
    with svc.store.transaction() as tx:
        return list(tx.scan(bucket))


def task_details(svc, agent):
    [task] = [t for t in rows(svc, "tasks") if t["agent"] == agent]
    return task, task["message"]["what"]["details"]


def reason_parts(receipt):
    section, fraction = receipt["reason_code"].split(":")[1:]
    observed, limit = (int(v) for v in fraction.split("/"))
    return section, observed, limit


def test_oversized_packet_ends_the_run_before_the_snapshot_or_the_dba_and_keeps_the_researcher_evidence():
    svc, run, executor, budget, port = build(outputs={"researcher": big_research()})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"].startswith("needs_scope_split:packet:"), receipt["reason_code"]
    section, observed, limit = reason_parts(receipt)
    assert section == "packet" and limit == 16384 and observed > 16384, "the first component's allowance is its reservation"
    assert executor.calls == ["lead:researcher"] and port.calls == 0, "no snapshot, no DBA, no lead after the refusal"
    assert receipt["stage"] == "packet" and receipt["packet_digest"] is not None and receipt["snapshot"] is None
    # Raw role evidence retained and untouched: the researcher task row, its answer and its execution artifact.
    task, _ = task_details(svc, "lead:researcher")
    assert task["status"] == "succeeded" and task["result"]["claims"] == big_research()["claims"]
    assert executor.artifacts.document(task["result"]["execution_ref"])["answer"]["claims"] == big_research()["claims"]
    assert "researcher" in receipt["roles"] and receipt["roles"]["researcher"]["execution_ref"] == task["result"]["execution_ref"]
    assert "xxxx" not in json.dumps(receipt), "the receipt carries digits and a section, never content"


def test_oversized_unicode_dba_report_after_a_large_packet_stops_before_the_relay_and_either_lead(monkeypatch):
    # INJECTED: a 16000-byte frozen packet (admitted: under 16384) leaves the normalized report 32768 - 16000 - 4096
    # - 8192 = 4480 bytes; 4000 Korean characters are inside the 4000-character report text rule but 12000 bytes.
    # The byte policy over the committed prefix, not the character rule, decides, and before any relay or lead.
    # (CouncilExecutor builds the DBA answer from the module constant, so the constant is patched.)
    monkeypatch.setattr(test_council, "DBA_REPORT", {**DBA_REPORT, "summary": "한" * 4000})
    svc, run, executor, budget, port = build(outputs={"researcher": research_sized(16000)})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"].startswith("needs_scope_split:dba_report:"), receipt["reason_code"]
    section, observed, limit = reason_parts(receipt)
    dba, details = task_details(svc, "lead:dba")
    assert canonical_bytes(details["packet"]) == 16000, "the DBA received the exact admitted packet"
    assert limit == 4480 == 32768 - 16000 - 4096 - 8192 and observed > 12000 > limit
    assert executor.calls == ["lead:researcher", "lead:dba"] and port.calls == 1
    assert receipt["report"] is None, "the oversized report is never frozen into the run row"
    assert not [t for t in rows(svc, "tasks") if t["agent"] in {"lead:research", "lead:improvement", "conductor"}]
    assert dba["status"] == "succeeded" and dba["result"]["summary"] == "한" * 4000, "raw DBA evidence retained"
    assert "한" not in json.dumps(receipt, ensure_ascii=False)


def test_oversized_research_lead_proposal_after_a_large_packet_stops_before_submit_and_the_improvement_lead():
    # INJECTED: 16000-byte packet, the fixture report, then a 9000-byte proposal summary (3000 Korean characters):
    # the allowance 32768 - 16000 - report - 8192 is below 9000 while the retired 4096 ceiling plays no part.
    svc, run, executor, budget, port = build(outputs={"researcher": research_sized(16000),
                                                      "research_lead": {**ROLE_OUTPUTS["proposer"], "summary": "한" * 3000}})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"].startswith("needs_scope_split:research_proposal:") and receipt["status"] == "failed"
    section, observed, limit = reason_parts(receipt)
    _, details = task_details(svc, "lead:research")
    assert limit == 32768 - canonical_bytes(details["packet"]) - canonical_bytes(details["dba_report"]) - 8192
    assert canonical_bytes(details["packet"]) == 16000 and 4096 < limit < 9000 <= observed
    assert executor.calls == ["lead:researcher", "lead:dba", "lead:research"]
    assert rows(svc, "dge_events") == [], "sessions.submit never ran for the refused proposal"


def test_oversized_improvement_proposal_including_findings_stops_before_the_conductor_with_findings_retained():
    # INJECTED: eight minor findings under the text rule each; the COMPLETE proposal (findings included) exceeds the
    # allowance left after a 16000-byte packet, the fixture report and the fixture proposal (about 16300 bytes).
    findings = [{"id": "f" + str(i), "criterion": "focused tests pass", "severity": "minor", "scenario": "s" + str(i) + " " + "z" * 2500,
                 "claim_ids": ["c1"], "trigger": None, "impact": None, "mitigation": None} for i in range(1, 9)]
    proposal = {**IMPROVEMENT, "findings": findings}
    svc, run, executor, budget, port = build(outputs={"researcher": research_sized(16000), "improvement_lead": proposal})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"].startswith("needs_scope_split:improvement_proposal:") and receipt["status"] == "failed"
    section, observed, limit = reason_parts(receipt)
    task, details = task_details(svc, "lead:improvement")
    assert limit == 32768 - sum(canonical_bytes(details[k]) for k in ("packet", "dba_report", "research_proposal"))
    assert 8192 < limit < observed, "the final component spends the rest of the pool, not a fixed 8192"
    assert executor.calls == ["lead:researcher", "lead:dba", "lead:research", "lead:improvement"], "no conductor start"
    assert [e["role"] for e in rows(svc, "dge_events")] == ["proposer"], "the attacker event was never submitted"
    assert task["result"]["findings"] == findings, "every finding stays in the raw evidence; none is dropped"
    assert not [t for t in rows(svc, "tasks") if t["agent"] == "conductor"]


def test_earlier_unused_capacity_lets_a_report_and_findings_over_the_retired_ceilings_reach_promotion(monkeypatch):
    # CONTROL (INJECTED): with the small fixture packet the same 12000-byte report and a 10000+ byte improvement
    # proposal, both refused under v1's 4096/8192 ceilings, are admitted and the council promotes; every role sees
    # the complete values and the future reservation was never spent twice.
    findings = [{"id": "f" + str(i), "criterion": "focused tests pass", "severity": "minor", "scenario": "s" + str(i) + " " + "z" * 2500,
                 "claim_ids": ["c1"], "trigger": None, "impact": None, "mitigation": None} for i in range(1, 5)]
    monkeypatch.setattr(test_council, "DBA_REPORT", {**DBA_REPORT, "summary": "한" * 4000})
    # The conductor fixture must name every finding exactly once (existing arbiter rule, unchanged).
    conductor = {**ROLE_OUTPUTS["arbiter"], "dispositions": [{"finding_id": f["id"], "decision": "deferred", "reason": "backlog"} for f in findings]}
    svc, run, executor, budget, port = build(outputs={"improvement_lead": {**IMPROVEMENT, "findings": findings}, "conductor": conductor})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and receipt["reason_code"] == "promoted", receipt["reason_code"]
    assert executor.calls == test_council.ORDER
    _, details = task_details(svc, "conductor")
    sizes = {k: canonical_bytes(details[k]) for k in PAYLOAD}
    assert sizes["dba_report"] > 12000 > 4096 and sizes["improvement_proposal"] > 10000 > 8192 and sizes["packet"] < 16384
    assert sum(sizes.values()) <= PAYLOAD_POOL and details["improvement_proposal"]["findings"] == findings
    assert admit_prefix({k: details[k] for k in PAYLOAD})["sections"] == sizes, "the conductor's prefix is the admitted one"


def test_normal_council_cycle_still_promotes_under_the_policy_control():
    svc, run, executor, budget, port = build()
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and receipt["reason_code"] == "promoted" and executor.calls == test_council.ORDER


class ConsumerOverflowExecutor(CouncilExecutor):
    """FIXTURE: the conductor task ends the way the real executor records its own consumer-gate refusal
    (task error = exception type + ': ' + the typed reason). The real executor's pre-entry refusal goes through
    `Workflow.fail(..., retryable=True)`, so the row is `retry`; a settled non-retryable failure is `failed`.
    Every other role runs as the council fixture does."""

    def __init__(self, svc, artifacts, error="CouncilInputOverflow: needs_scope_split:host_overhead:4721/4096",
                 status="retry", **kwargs):
        super().__init__(svc, artifacts, **kwargs)
        self.error, self.status = error, status

    def execute_one(self, agent, expected=None):
        with self.svc.store.transaction() as tx:
            task = tx.get("tasks", expected["id"])
        if task["message"]["what"]["details"].get("role") != "conductor":
            return super().execute_one(agent, expected)
        self.calls.append(agent)
        with self.svc.store.transaction() as tx:
            task.update(attempt=1, generation=1, lease_owner="fixture", status=self.status, error=self.error)
            tx.put("tasks", task["id"], task)
        return task


@pytest.mark.parametrize("status", ["retry", "failed"])
@pytest.mark.parametrize("error, lifted", [
    ("CouncilInputOverflow: needs_scope_split:host_overhead:4721/4096", True),
    ("CouncilInputOverflow: needs_scope_split:required:40961/40960", True),
    ("CouncilInputOverflow: needs_scope_split:improvement_proposal:14867/14866", True),  # a v2 computed allowance
    ("CouncilInputOverflow: needs_scope_split:packet:<script>/16384", False),  # not the safe shape: not lifted
    ("RuntimeError: needs_scope_split:packet:1/1", False),  # another failure type: unchanged code
    ("ContractError: Council delivery input missing: packet", False),  # missing field stays distinct
    ("ContractError: Council input beyond the research_lead prefix: improvement_proposal", False),  # injected future component
])
def test_consumer_gate_refusal_reaches_the_run_as_the_precise_reason_only_in_its_safe_shape(monkeypatch, error, lifted, status):
    # Both legitimate role outcomes of an executor refusal (`retry`: the real pre-entry path; `failed`) surface the
    # typed reason; an unrelated failure keeps the plain role_<status> code. The run never re-dispatches the role.
    reason = error.split(": ", 1)[1] if lifted else "role_" + status
    monkeypatch.setattr(test_council, "CouncilExecutor",
                        lambda svc, artifacts, **kw: ConsumerOverflowExecutor(svc, artifacts, error, status, **kw))
    svc, run, executor, budget, port = build()
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == reason
    assert executor.calls[-1] == "conductor" and len(executor.calls) == 5 and receipt["promotion"] is None
    assert executor.calls.count("conductor") == 1, "no automatic retry of the refused role"
    [task] = [t for t in rows(svc, "tasks") if t["agent"] == "conductor"]
    assert (task["status"], task["error"]) == (status, error), "the role's own failure record stays as recorded"


# ----- consumer gates under the actual Executor and compiler (fake runtime records the prompt) ---------
def largest_details(role, distribution="reserved"):
    """SYNTHETIC: the role's payload prefix at its largest admitted sizes, each value ending in escaped and Korean
    text. `reserved`: every component at its reservation. `shifted`: a 4096-byte packet and the last component
    of the prefix spending the unused bytes, the later reservations still held."""
    details = details_for(role, claims=4, text_bytes=40)
    prefix = ROLE_PREFIX[role]
    sizes = {s: RESERVATIONS[s] for s in prefix}
    if distribution == "shifted":
        sizes[PACKET] = 4096
        sizes[prefix[-1]] = PAYLOAD_POOL - sum(sizes[s] for s in prefix[:-1]) - LATER[prefix[-1]]
    for section in prefix:
        details[section] = fill(details[section], FILL_PATH[section], sizes[section], ESCAPED, True)
    if role != "research_lead":
        details["prior_outputs"]["research_lead"]["proposal"] = details["research_proposal"]
    if role == "conductor":
        details["prior_outputs"]["improvement_lead"]["proposal"] = details["improvement_proposal"]
    return details, sizes


@pytest.mark.parametrize("role", COUNCIL_DEBATE_ROLES)
@pytest.mark.parametrize("distribution", sorted(DISTRIBUTIONS))
def test_largest_admitted_prefix_with_representative_metadata_reaches_the_prompt_whole_and_one_more_byte_never_reaches_a_provider(
        representative, role, distribution):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    executor, artifacts, prompts, config = representative
    details, sizes = largest_details(role, distribution)
    prefix = ROLE_PREFIX[role]
    assert sum(sizes.values()) + LATER[prefix[-1]] == PAYLOAD_POOL, "the prefix plus its future reservations fills the pool exactly"
    frozen = copy.deepcopy(details)
    result = deliver(executor, role, details)
    [prompt] = prompts
    rendered = len(canonical(prompt).encode("utf-8"))
    assert rendered <= 40960, rendered
    inline = prompt["required"]["council_delivery"]["inline"]
    assert [k for k in PAYLOAD if k in inline] == list(prefix), "exactly the role's prefix, no future component"
    for key in prefix:
        assert inline[key] == details[key] and canonical_bytes(inline[key]) == sizes[key], key
    assert "한" * 10 in inline["packet"]["claims"][3]["text"] and "한" * 10 in inline["dba_report"]["summary"], "Korean whole"
    assert ESCAPED in inline["packet"]["claims"][3]["text"] and ESCAPED in inline["dba_report"]["summary"], "escaped text whole"
    assert details == frozen and artifacts._body(prompt["required"]["external_context"]["ref"]) == canonical(details)
    assert prompt["required"]["objective"] == role_objective(role, details)
    # Truthful byte telemetry in the execution receipt: v2 policy, named sections, pool spend, held reservations,
    # host overhead and the limit.
    receipt = json.loads(artifacts._body(result["execution_ref"]))["context_measurement"]
    assert receipt["policy"] == SCHEMA == "urn:zeus:council-input:2"
    assert (receipt["window"], receipt["reserved"], receipt["usable"]) == (49152, 8192, 40960)
    assert receipt["rendered_bytes"] == receipt["required_bytes"] == rendered and receipt["limit_bytes"] == 40960
    assert receipt["sections"] == sizes and receipt["unit"] == UNIT
    assert receipt["payload_bytes"] == sum(sizes.values()) and receipt["reserved_bytes"] == LATER[prefix[-1]]
    assert receipt["host_overhead_bytes"] == rendered - receipt["delivery_bytes"] <= 4096
    assert receipt["delivery_overhead_bytes"] <= 4096 and "estimated_tokens" not in receipt
    print("\n", role, distribution, "rendered", rendered, "host", receipt["host_overhead_bytes"], "wrapper", receipt["delivery_overhead_bytes"])
    # One byte more on the last component of the prefix: refused by the typed overflow before any provider entry,
    # naming the computed allowance (not a fixed ceiling).
    last = prefix[-1]
    over = copy.deepcopy(details)
    over[last] = grown(details[last], FILL_PATH[last])
    assert canonical_bytes(over[last]) == sizes[last] + 1
    with pytest.raises(CouncilInputOverflow) as info:
        execute_role(executor, task_for(role, over), heartbeat=None)
    assert (info.value.section, info.value.observed, info.value.limit) == (last, sizes[last] + 1, sizes[last])
    assert len(prompts) == 1, "no second provider entry"


@pytest.mark.parametrize("role", ["improvement_lead", "conductor"])
def test_live005_size_equivalent_projection_fits_under_the_actual_executor_with_the_future_reservation_held(representative, role):  # noqa: F811
    # SYNTHETIC size-equivalent case (11965/1677/4260; the conductor adds the full 8192 the improvement lead may
    # still spend). The owner replays the retained raw inputs separately.
    executor, artifacts, prompts, config = representative
    details = details_for(role, claims=4, text_bytes=40)
    sizes = dict(LIVE005, **({IMPROVEMENT_PROPOSAL: 8192} if role == "conductor" else {}))
    for section, size in sizes.items():
        details[section] = fill(details[section], FILL_PATH[section], size, ESCAPED, True)
    details["prior_outputs"]["research_lead"]["proposal"] = details["research_proposal"]
    if role == "conductor":
        details["prior_outputs"]["improvement_lead"]["proposal"] = details["improvement_proposal"]
    result = deliver(executor, role, details)
    [prompt] = prompts
    receipt = json.loads(artifacts._body(result["execution_ref"]))["context_measurement"]
    assert receipt["sections"] == sizes and receipt["policy"] == SCHEMA
    assert receipt["reserved_bytes"] == (0 if role == "conductor" else 8192) and receipt["payload_bytes"] == sum(sizes.values())
    assert receipt["required_bytes"] == len(canonical(prompt).encode("utf-8")) <= 40960


def test_caller_cannot_obtain_the_council_budget_with_a_foreign_trimmed_misrouted_or_future_injected_delivery(tmp_path, monkeypatch):
    details = details_for("conductor")
    delivery = council_delivery("conductor", details)
    executor, _, _ = harness(tmp_path, monkeypatch, entered=False)
    cwd, schema = str(executor.git.root), role_schema("conductor", details)

    def run(agent="conductor", evidence=details, **overrides):
        kwargs = dict(read_only=True, stage="dge:conductor", workload="design", action="dge_role", max_handoffs=1, delivery=delivery)
        kwargs.update(overrides)
        return executor._run(agent, "task-conductor", OBJECTIVES["conductor"], evidence, cwd, schema, **kwargs)

    trimmed = copy.deepcopy(delivery)
    trimmed["inline"]["packet"]["claims"].clear()
    inflated = {**delivery, "guidance": delivery["guidance"] + " (edited)"}
    # A research lead handed the improvement proposal ahead of time: not the projection of its task.
    lead_details = details_for("research_lead")
    lead_delivery = council_delivery("research_lead", lead_details)
    injected = copy.deepcopy(lead_delivery)
    injected["inline"]["improvement_proposal"] = details["improvement_proposal"]
    cases = [(dict(action="implement"), "read-only dge_role"), (dict(action=None), "read-only dge_role"),
             (dict(read_only=False), "read-only dge_role"), (dict(stage="dge:dba"), "role, stage and agent"),
             (dict(stage=None), "role, stage and agent"), (dict(agent="lead:dba"), "role, stage and agent"),
             (dict(delivery=trimmed), "not the projection"), (dict(delivery=inflated), "not the projection"),
             (dict(delivery={"schema": "urn:zeus:council-delivery:1"}), "names no debate role"),
             (dict(delivery={"inline": {"role": "dba"}}), "names no debate role"),
             (dict(delivery={**delivery, "inline": {**delivery["inline"], "role": "research_lead"}}, stage="dge:research_lead",
                   agent="lead:research"), "role mismatch"),
             (dict(delivery=injected, evidence=lead_details, stage="dge:research_lead", agent="lead:research"), "not the projection")]
    for overrides, message in cases:
        with pytest.raises(ContractError, match=message):
            run(**overrides)
    with pytest.raises(ContractError, match="beyond the research_lead prefix"):
        admit_delivery(injected, "research_lead")


def test_legacy_budget_and_receipt_are_unchanged_for_non_council_executions(tmp_path, monkeypatch):
    answer = {"accepted": True, "reason": "fixture", "blocked": False, "risks": [], "sre_assessment": "n/a", "arc42_assessment": "n/a"}
    executor, artifacts, prompts = harness(tmp_path, monkeypatch, answer=answer)
    result = executor._run("lead:improvement", "review", "Evaluate review_lead", {"candidate": {"revision": "c" * 40}},
                           str(tmp_path), VERDICT, read_only=True)
    [prompt] = prompts
    receipt = json.loads(artifacts._body(result["execution_ref"]))
    assert receipt["context_measurement"] == {"policy": "legacy", "unit": "utf8_bytes", "window": 28000, "reserved": 6000,
                                              "usable": 22000, "rendered_bytes": len(canonical(prompt).encode("utf-8"))}
    assert "council_delivery" not in prompt["required"] and "input_policy" not in json.dumps(prompt)
    assert set(result) == {*answer, "execution_ref", "basis_revision"}, "the returned answer shape is unchanged"
    # A required block over the legacy budget stays refused by the legacy compiler rule; no council window is granted.
    second = tmp_path / "second"
    second.mkdir()
    other, _, _ = harness(second, monkeypatch, entered=False)
    big = {"plan": {"objective": "o" * 23000, "acceptance_criteria": ["a"], "allowed_paths": ["docs"]}}
    with pytest.raises(ContractError, match="Required contract exceeds budget"):
        other._run("lead:improvement", "plan-1", "Plan", big, str(second), VERDICT, read_only=True)


def test_provider_start_event_keeps_its_registered_log_schema_and_the_receipt_carries_the_byte_telemetry(tmp_path, monkeypatch):
    # The executor's default observer is the real Observer over an in-memory spool: an attribute the registry does
    # not declare makes build_event refuse and Observer.emit return None, losing the whole normal start event.
    # The start event must therefore carry exactly the registered attributes; the byte telemetry is additive in the
    # execution receipt's context_measurement only.
    details = details_for("conductor")
    executor, artifacts, prompts = harness(tmp_path, monkeypatch, answer=CONDUCTOR_ANSWER)
    result = deliver(executor, "conductor", details)
    records = executor.observer.spool.records()
    [started] = [r for r in records if r["event_type"] == "development.provider_started"]
    assert not [r for r in records if r["event_type"] == "operations.observation_refused"], "no refused emission"
    assert check_attributes("development.provider_started", started["attributes"]) == started["attributes"]
    assert set(started["attributes"]) == set(REGISTRY["development.provider_started"])
    assert started["attributes"]["read_only"] is True and started["attributes"]["context_ref"].startswith("sha256:")
    assert "context_bytes" not in started["attributes"] and "context_policy" not in started["attributes"]
    assert [r["event_type"] for r in records if r["event_type"].startswith("development.provider_")] == \
        ["development.provider_started", "development.provider_finished"]
    [prompt] = prompts
    receipt = json.loads(artifacts._body(result["execution_ref"]))["context_measurement"]
    assert receipt["policy"] == SCHEMA and receipt["rendered_bytes"] == receipt["required_bytes"] == canonical_bytes(prompt)
    assert receipt["limit_bytes"] == 40960 and set(receipt["sections"]) == set(PAYLOAD)
    assert receipt["payload_bytes"] == sum(receipt["sections"].values()) and receipt["reserved_bytes"] == 0


def test_complete_required_envelope_over_the_whole_window_is_the_typed_refusal_before_the_generic_compiler_rule(tmp_path, monkeypatch):
    # INJECTED: the largest admitted conductor prefix (the whole 32768-byte pool spent; measured in implementation011
    # the serialized delivery was 34044 bytes, the wrapper well under its cap) and a host objective grown by 8000
    # bytes: a REQUIRED host input outside the delivery, the only one a `_run` caller supplies. The COMPLETE
    # required envelope is then over the whole 40960 window, the case the generic compiler rule ("Required
    # contract exceeds budget") used to catch first. The executor preflights the actual required envelope through
    # ContextPacket before compile_context, so the refusal is the typed needs_scope_split with safe named
    # diagnostics, before any provider entry, and the raw task artifact is stored untouched.
    details, _ = largest_details("conductor")
    frozen = copy.deepcopy(details)
    delivery = council_delivery("conductor", details)
    delivery_bytes = canonical_bytes(delivery)
    executor, artifacts, prompts = harness(tmp_path, monkeypatch, entered=False)
    objective = OBJECTIVES["conductor"] + " " + "o" * 8000
    with pytest.raises(CouncilInputOverflow) as info:
        executor._run(AGENTS["conductor"], "task-conductor", objective, details, str(executor.git.root),
                      role_schema("conductor", details), True, None, None, stage="dge:conductor", workload="design",
                      action="dge_role", max_handoffs=1, delivery=delivery)
    exc = info.value
    assert "exceeds budget" not in str(exc) and str(exc) == exc.reason_code
    # Arithmetic of the policy: 32768 + 4096 + 4096 = 40960, so a whole envelope over the window with an admitted
    # delivery is always a host overflow; that is the section named, with observed and limit bytes only.
    assert exc.section == "host_overhead" and exc.limit == 4096 < exc.observed
    assert exc.observed + delivery_bytes > LIMITS["required"] == 40960, "the whole required envelope was over the window"
    assert exc.diagnostics() == {"schema": SCHEMA, "reason": "needs_scope_split", "section": "host_overhead",
                                 "observed_bytes": exc.observed, "limit_bytes": 4096, "unit": UNIT}
    assert "한" not in json.dumps(exc.diagnostics(), ensure_ascii=False) and "yyyy" not in str(exc)
    assert prompts == [], "provider entries: 0"
    assert details == frozen and delivery == council_delivery("conductor", details), "nothing resized or dropped"
    raw = "sha256:" + hashlib.sha256(canonical(details).encode("utf-8")).hexdigest()
    assert artifacts._body(raw) == canonical(details), "raw task artifact stored and untouched"


def test_recovery_sources_that_exceed_the_host_allowance_fail_safely_before_the_provider(tmp_path, monkeypatch):
    # INJECTED: a bound checkpoint and progress row for the same conductor task (a retried attempt), exactly the
    # rows the earlier delivery test injected. Measured in implementation011 at the pinned revision: the two
    # recovery evidence items plus the full reader catalogue put the complete prompt 4721 bytes outside the
    # serialized delivery, over the 4096 host allowance (unchanged in v2). The refusal is the typed needs_scope_split
    # BEFORE any provider entry; nothing is omitted, resized or retried and the raw task artifact is stored unchanged.
    details = details_for("conductor")
    executor, artifacts, prompts = harness(tmp_path, monkeypatch, entered=False)
    binding = {"stage": "dge:conductor", "evidence_ref": artifacts.put(canonical(details), "probe")["ref"], "basis_revision": BASE}
    with executor.service.store.transaction() as tx:
        tx.put("sessions", AGENTS["conductor"], {"generation": 1, "checkpoint": {"task_id": "task-conductor", "research_binding": binding}})
        tx.put("execution_progress", "task-conductor", {"id": "task-conductor", "recent": [], "research_binding": binding})
    with pytest.raises(CouncilInputOverflow) as info:
        deliver(executor, "conductor", details)
    assert info.value.section == "host_overhead" and info.value.limit == 4096 < info.value.observed
    assert str(info.value) == "needs_scope_split:host_overhead:" + str(info.value.observed) + "/4096"
    assert prompts == []
    raw = "sha256:" + hashlib.sha256(canonical(details).encode("utf-8")).hexdigest()
    assert artifacts._body(raw) == canonical(details), "raw task artifact stored and untouched"
    assert KOREAN in details["dba_report"]["summary"], "fixture content intact"
