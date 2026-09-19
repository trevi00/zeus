"""urn:zeus:council-input:1 boundaries (research-program-001, delivery implementation011).

Every fixture here is SYNTHETIC and labelled. No model runs: the executor tests use the prompt-recording fake
runtime of test_council_delivery, the council-run tests use the FakeExecutor of test_council with INJECTED
oversized role outputs. Sizes are UTF-8 bytes of canonical JSON, the policy's own unit; they prove deterministic
admission and refusal, never model comprehension.
"""
import copy
import hashlib
import json

import pytest
import test_council
import test_council_delivery
from test_autonomous import RESEARCH, ROLE_OUTPUTS
from test_council import DBA_REPORT, IMPROVEMENT, CouncilExecutor, build, valid
from test_council_delivery import BASE, KOREAN, deliver, details_for, harness, task_for
from test_operation import BOUND_GOAL, IDENTITY

from codex_harness.adapters.autonomous_roles import (
    COUNCIL_DEBATE_ROLES,
    OBJECTIVES,
    council_delivery,
    execute_role,
    role_schema,
)
from codex_harness.adapters.executor import VERDICT
from codex_harness.domain.council import AGENTS
from codex_harness.domain.council_input import (
    LIMITS,
    PAYLOAD_LIMITS,
    PAYLOAD_TOTAL,
    PRODUCERS,
    SCHEMA,
    UNIT,
    CouncilInputOverflow,
    admit,
    admit_delivery,
    admit_required,
    canonical_bytes,
    council_budget,
    output_limit,
    policy_manifest,
)
from codex_harness.domain.model import ContractError, canonical

ESCAPED = 'quote " backslash \\ newline \n tab \t '  # JSON escaping adds bytes the caps must count
PAYLOAD = ("packet", "dba_report", "research_proposal", "improvement_proposal")


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


# ----- policy -------------------------------------------------------------------------------------
def test_policy_manifest_states_the_owner_fixed_limits_the_council_window_and_the_untouched_legacy_pair():
    manifest = policy_manifest()
    assert manifest["schema"] == SCHEMA == "urn:zeus:council-input:1" and manifest["unit"] == UNIT
    assert manifest["limits"] == LIMITS == {"packet": 16384, "dba_report": 4096, "research_proposal": 4096,
                                            "improvement_proposal": 8192, "delivery_overhead": 4096,
                                            "host_overhead": 4096, "required": 40960}
    assert sum(PAYLOAD_LIMITS.values()) == PAYLOAD_TOTAL == manifest["payload_total"] == 32768
    assert PAYLOAD_TOTAL + LIMITS["delivery_overhead"] + LIMITS["host_overhead"] == LIMITS["required"] == manifest["usable"]
    assert council_budget() == (manifest["window"], manifest["reserved"]) == (49152, 8192)
    assert manifest["legacy"] == {"window": 28000, "reserved": 6000} and "not model tokens" in manifest["note"]
    for bad in (lambda: admit("bogus", {}), lambda: output_limit("bogus"), lambda: CouncilInputOverflow("bogus", 1, 0)):
        with pytest.raises(ContractError, match="Unknown council input section"):
            bad()
    # Output instructions name each producer's own limit and the no-drop rule; the researcher's is council-scoped.
    for section, role in PRODUCERS.items():
        assert str(PAYLOAD_LIMITS[section]) + " UTF-8 bytes" in OBJECTIVES[role], role
        assert "never drop or relabel" in OBJECTIVES[role] and output_limit(section) in OBJECTIVES[role]
    assert "urn:zeus:autonomous:2" in OBJECTIVES["researcher"] and "every finding" in output_limit("improvement_proposal")


# ----- exact cap / cap+1 per section, ASCII, multi-byte and escaped ---------------------------------
VARIANTS = {"ascii": ("", False), "multibyte": ("", True), "escaped": (ESCAPED, False), "escaped_multibyte": (ESCAPED, True)}


@pytest.mark.parametrize("section", PAYLOAD)
@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_exact_cap_is_admitted_and_one_more_byte_is_the_typed_overflow_with_safe_diagnostics(section, variant):
    prefix, multibyte = VARIANTS[variant]
    cap = PAYLOAD_LIMITS[section]
    exact = fill({"id": section, "text": ""}, ["text"], cap, prefix, multibyte)
    assert admit(section, exact) == cap
    if multibyte:
        assert len(canonical(exact)) < cap, "characters are not bytes: the cap counts encoded bytes"
    if prefix:
        assert '\\"' in canonical(exact) and "\\n" in canonical(exact) and "\\\\" in canonical(exact), "escaped forms are measured"
        assert canonical_bytes(exact) > len(canonical(exact).encode("utf-8")) - len(prefix) + len(prefix.encode("utf-8")) - 5
    over = {**exact, "text": exact["text"] + "!"}
    assert canonical_bytes(over) == cap + 1
    with pytest.raises(CouncilInputOverflow) as info:
        admit(section, over)
    exc = info.value
    assert isinstance(exc, ContractError) and (exc.section, exc.observed, exc.limit) == (section, cap + 1, cap)
    assert str(exc) == exc.reason_code == "needs_scope_split:" + section + ":" + str(cap + 1) + "/" + str(cap)
    assert exc.diagnostics() == {"schema": SCHEMA, "reason": "needs_scope_split", "section": section,
                                 "observed_bytes": cap + 1, "limit_bytes": cap, "unit": UNIT}
    assert "yyyy" not in str(exc) and "한" not in json.dumps(exc.diagnostics(), ensure_ascii=False), "no content leaks"
    assert over["text"].endswith("!"), "the value is never modified"


# ----- delivery (wrapper) and required (host) admission ---------------------------------------------
def test_delivery_admission_measures_components_and_wrapper_exactly_and_keeps_a_missing_field_a_shape_error():
    details = details_for("conductor")
    delivery = council_delivery("conductor", details)
    measure = admit_delivery(delivery)
    inline = delivery["inline"]
    assert measure["sections"] == {k: canonical_bytes(inline[k]) for k in PAYLOAD}
    assert measure["sections"]["packet"] == canonical_bytes(details["packet"]), "the exact task value is measured"
    assert measure["delivery_bytes"] == canonical_bytes(delivery) == len(canonical(delivery).encode("utf-8"))
    assert measure["delivery_overhead_bytes"] == measure["delivery_bytes"] - sum(measure["sections"].values())
    # Exactness of the subtraction: the wrapper with every component emptied to "" is the overhead plus the quotes.
    emptied = copy.deepcopy(delivery)
    for key in PAYLOAD:
        emptied["inline"][key] = ""
    assert canonical_bytes(emptied) == measure["delivery_overhead_bytes"] + 2 * len(PAYLOAD)
    assert delivery["input_policy"] == SCHEMA and measure["schema"] == SCHEMA
    lead = admit_delivery(council_delivery("research_lead", details_for("research_lead")))
    assert set(lead["sections"]) == {"packet", "dba_report"}, "a lead delivery bounds only its present components"
    assert set(admit_delivery(council_delivery("improvement_lead", details_for("improvement_lead")))["sections"]) == \
        {"packet", "dba_report", "research_proposal"}
    # Missing mandatory component or shape: a ContractError that is NOT an overflow.
    for document, message in (({"inline": {"packet": {}}}, "Council input missing: dba_report"),
                              ({"schema": "x"}, "inline object"), ("text", "inline object")):
        with pytest.raises(ContractError, match=message) as info:
            admit_delivery(document)
        assert not isinstance(info.value, CouncilInputOverflow)
    # Wrapper boundary: exactly 4096 bytes of overhead is admitted, one more byte is the typed overflow.
    room = LIMITS["delivery_overhead"] - measure["delivery_overhead_bytes"]
    exact = {**delivery, "guidance": delivery["guidance"] + "g" * room}
    assert admit_delivery(exact)["delivery_overhead_bytes"] == 4096
    with pytest.raises(CouncilInputOverflow) as info:
        admit_delivery({**exact, "guidance": exact["guidance"] + "g"})
    assert (info.value.section, info.value.observed, info.value.limit) == ("delivery_overhead", 4097, 4096)


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
    """INJECTED: valid claims (each under the DGE text limit) whose packet exceeds 16384 bytes."""
    claims = [RESEARCH["claims"][0]] + [{"id": "c" + str(i), "kind": "fact", "text": "claim " + str(i) + " " + "x" * 3000,
                                          "source_ids": ["s1"]} for i in range(2, 9)]
    return {**RESEARCH, "claims": claims}


def rows(svc, bucket):
    with svc.store.transaction() as tx:
        return list(tx.scan(bucket))


def test_oversized_packet_ends_the_run_before_the_snapshot_or_the_dba_and_keeps_the_researcher_evidence():
    svc, run, executor, budget, port = build(outputs={"researcher": big_research()})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"].startswith("needs_scope_split:packet:"), receipt["reason_code"]
    section, fraction = receipt["reason_code"].split(":")[1:]
    observed, limit = (int(v) for v in fraction.split("/"))
    assert section == "packet" and limit == 16384 and observed > 16384
    assert executor.calls == ["lead:researcher"] and port.calls == 0, "no snapshot, no DBA, no lead after the refusal"
    assert receipt["stage"] == "packet" and receipt["packet_digest"] is not None and receipt["snapshot"] is None
    # Raw role evidence retained and untouched: the researcher task row, its answer and its execution artifact.
    [task] = [t for t in rows(svc, "tasks") if t["agent"] == "lead:researcher"]
    assert task["status"] == "succeeded" and task["result"]["claims"] == big_research()["claims"]
    assert executor.artifacts.document(task["result"]["execution_ref"])["answer"]["claims"] == big_research()["claims"]
    assert "researcher" in receipt["roles"] and receipt["roles"]["researcher"]["execution_ref"] == task["result"]["execution_ref"]
    assert "xxxx" not in json.dumps(receipt), "the receipt carries digits and a section, never content"


def test_oversized_unicode_dba_report_stops_before_the_relay_and_either_lead(monkeypatch):
    # INJECTED: 1400 Korean characters are under the 4000-character report text rule but 4200 bytes: the byte
    # policy, not the character rule, decides, and it decides before the report is relayed to any lead.
    # (CouncilExecutor builds the DBA answer from the module constant, so the constant is patched.)
    monkeypatch.setattr(test_council, "DBA_REPORT", {**DBA_REPORT, "summary": "한" * 1400})
    svc, run, executor, budget, port = build()
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"].startswith("needs_scope_split:dba_report:"), receipt["reason_code"]
    assert int(receipt["reason_code"].split(":")[-1].split("/")[0]) > 4096 == int(receipt["reason_code"].split("/")[-1])
    assert executor.calls == ["lead:researcher", "lead:dba"] and port.calls == 1
    assert receipt["report"] is None, "the oversized report is never frozen into the run row"
    assert not [t for t in rows(svc, "tasks") if t["agent"] in {"lead:research", "lead:improvement", "conductor"}]
    [dba] = [t for t in rows(svc, "tasks") if t["agent"] == "lead:dba"]
    assert dba["status"] == "succeeded" and dba["result"]["summary"] == "한" * 1400, "raw DBA evidence retained"


def test_oversized_research_lead_proposal_stops_before_submit_and_before_the_improvement_lead():
    svc, run, executor, budget, port = build(outputs={"research_lead": {**ROLE_OUTPUTS["proposer"], "summary": "한" * 1400}})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"].startswith("needs_scope_split:research_proposal:") and receipt["status"] == "failed"
    assert receipt["reason_code"].endswith("/4096")
    assert executor.calls == ["lead:researcher", "lead:dba", "lead:research"]
    assert rows(svc, "dge_events") == [], "sessions.submit never ran for the refused proposal"


def test_oversized_improvement_proposal_including_findings_stops_before_the_conductor_with_findings_retained():
    # INJECTED: four minor findings under the text rule each; the COMPLETE proposal (findings included) is 8192+.
    findings = [{"id": "f" + str(i), "criterion": "focused tests pass", "severity": "minor", "scenario": "s" + str(i) + " " + "z" * 2500,
                 "claim_ids": ["c1"], "trigger": None, "impact": None, "mitigation": None} for i in range(1, 5)]
    proposal = {**IMPROVEMENT, "findings": findings}
    svc, run, executor, budget, port = build(outputs={"improvement_lead": proposal})
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["reason_code"].startswith("needs_scope_split:improvement_proposal:") and receipt["reason_code"].endswith("/8192")
    assert receipt["status"] == "failed"
    assert executor.calls == ["lead:researcher", "lead:dba", "lead:research", "lead:improvement"], "no conductor start"
    assert [e["role"] for e in rows(svc, "dge_events")] == ["proposer"], "the attacker event was never submitted"
    [task] = [t for t in rows(svc, "tasks") if t["agent"] == "lead:improvement"]
    assert task["result"]["findings"] == findings, "every finding stays in the raw evidence; none is dropped"
    assert not [t for t in rows(svc, "tasks") if t["agent"] == "conductor"]


def test_normal_council_cycle_still_promotes_under_the_policy_control():
    svc, run, executor, budget, port = build()
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and receipt["reason_code"] == "promoted" and executor.calls == test_council.ORDER


class ConsumerOverflowExecutor(CouncilExecutor):
    """FIXTURE: the conductor task fails the way the real executor fails it when its own consumer gate refuses
    (task error = exception type + ': ' + the typed reason); every other role runs as the council fixture does."""

    def __init__(self, svc, artifacts, error="CouncilInputOverflow: needs_scope_split:host_overhead:4721/4096", **kwargs):
        super().__init__(svc, artifacts, **kwargs)
        self.error = error

    def execute_one(self, agent, expected=None):
        with self.svc.store.transaction() as tx:
            task = tx.get("tasks", expected["id"])
        if task["message"]["what"]["details"].get("role") != "conductor":
            return super().execute_one(agent, expected)
        self.calls.append(agent)
        with self.svc.store.transaction() as tx:
            task.update(attempt=1, generation=1, lease_owner="fixture", status="failed", error=self.error)
            tx.put("tasks", task["id"], task)
        return task


@pytest.mark.parametrize("error, reason", [
    ("CouncilInputOverflow: needs_scope_split:host_overhead:4721/4096", "needs_scope_split:host_overhead:4721/4096"),
    ("CouncilInputOverflow: needs_scope_split:required:40961/40960", "needs_scope_split:required:40961/40960"),
    ("CouncilInputOverflow: needs_scope_split:packet:<script>/16384", "role_failed"),  # not the safe shape: not lifted
    ("RuntimeError: needs_scope_split:packet:1/1", "role_failed"),  # another failure type: unchanged code
    ("ContractError: Council delivery input missing: packet", "role_failed"),  # missing field stays distinct
])
def test_consumer_gate_refusal_reaches_the_run_as_the_precise_reason_only_in_its_safe_shape(monkeypatch, error, reason):
    monkeypatch.setattr(test_council, "CouncilExecutor", lambda svc, artifacts, **kw: ConsumerOverflowExecutor(svc, artifacts, error, **kw))
    svc, run, executor, budget, port = build()
    receipt = run.run(valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == reason
    assert executor.calls[-1] == "conductor" and len(executor.calls) == 5 and receipt["promotion"] is None


# ----- consumer gates under the actual Executor and compiler (fake runtime records the prompt) ---------
def largest_details(role):
    """SYNTHETIC: every payload the role receives at EXACTLY its cap, each ending in escaped and Korean text."""
    details = details_for(role, claims=4, text_bytes=40)
    details["packet"] = fill(details["packet"], ["claims", 3, "text"], 16384, ESCAPED, True)
    details["dba_report"] = fill(details["dba_report"], ["summary"], 4096, ESCAPED, True)
    if role != "research_lead":
        details["research_proposal"] = fill(details["research_proposal"], ["summary"], 4096, ESCAPED, True)
        details["prior_outputs"]["research_lead"]["proposal"] = details["research_proposal"]
    if role == "conductor":
        details["improvement_proposal"] = fill(details["improvement_proposal"], ["findings", 0, "scenario"], 8192, ESCAPED, True)
        details["prior_outputs"]["improvement_lead"]["proposal"] = details["improvement_proposal"]
    return details


@pytest.mark.parametrize("role", COUNCIL_DEBATE_ROLES)
def test_largest_admitted_payloads_with_representative_metadata_reach_the_prompt_whole_and_cap_plus_one_never_reaches_a_provider(representative, role):
    executor, artifacts, prompts, config = representative
    details = largest_details(role)
    frozen = copy.deepcopy(details)
    result = deliver(executor, role, details)
    [prompt] = prompts
    rendered = len(canonical(prompt).encode("utf-8"))
    assert rendered <= 40960, rendered
    inline = prompt["required"]["council_delivery"]["inline"]
    present = [k for k in PAYLOAD if k in details]
    for key in present:
        assert inline[key] == details[key], key
        assert canonical_bytes(inline[key]) == PAYLOAD_LIMITS[key], key
    assert "한" * 10 in inline["packet"]["claims"][3]["text"] and "한" * 10 in inline["dba_report"]["summary"], "Korean whole"
    assert ESCAPED in inline["packet"]["claims"][3]["text"] and ESCAPED in inline["dba_report"]["summary"], "escaped text whole"
    assert details == frozen and artifacts._body(prompt["required"]["external_context"]["ref"]) == canonical(details)
    # Truthful byte telemetry in the execution receipt: policy, named sections, host overhead and the limit.
    receipt = json.loads(artifacts._body(result["execution_ref"]))["context_measurement"]
    assert receipt["policy"] == SCHEMA and (receipt["window"], receipt["reserved"], receipt["usable"]) == (49152, 8192, 40960)
    assert receipt["rendered_bytes"] == receipt["required_bytes"] == rendered and receipt["limit_bytes"] == 40960
    assert receipt["sections"] == {k: PAYLOAD_LIMITS[k] for k in present} and receipt["unit"] == UNIT
    assert receipt["host_overhead_bytes"] == rendered - receipt["delivery_bytes"] <= 4096
    assert receipt["delivery_overhead_bytes"] <= 4096 and "estimated_tokens" not in receipt
    print("\n", role, "rendered", rendered, "host", receipt["host_overhead_bytes"], "wrapper", receipt["delivery_overhead_bytes"])
    # Cap+1 on the largest payload the role carries: refused by the typed overflow before any provider entry.
    largest = present[-1]
    over = copy.deepcopy(details)
    path = {"packet": ["claims", 3, "text"], "dba_report": ["summary"], "research_proposal": ["summary"],
            "improvement_proposal": ["findings", 0, "scenario"]}[largest]
    target = over[largest]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] += "!"
    assert canonical_bytes(over[largest]) == PAYLOAD_LIMITS[largest] + 1
    with pytest.raises(CouncilInputOverflow) as info:
        execute_role(executor, task_for(role, over), heartbeat=None)
    assert (info.value.section, info.value.observed, info.value.limit) == (largest, PAYLOAD_LIMITS[largest] + 1, PAYLOAD_LIMITS[largest])
    assert len(prompts) == 1, "no second provider entry"


def test_caller_cannot_obtain_the_council_budget_with_a_foreign_trimmed_or_misrouted_delivery(tmp_path, monkeypatch):
    details = details_for("conductor")
    delivery = council_delivery("conductor", details)
    executor, _, _ = harness(tmp_path, monkeypatch, entered=False)
    cwd, schema = str(executor.git.root), role_schema("conductor", details)

    def run(agent="conductor", **overrides):
        kwargs = dict(read_only=True, stage="dge:conductor", workload="design", action="dge_role", max_handoffs=1, delivery=delivery)
        kwargs.update(overrides)
        return executor._run(agent, "task-conductor", OBJECTIVES["conductor"], details, cwd, schema, **kwargs)

    trimmed = copy.deepcopy(delivery)
    trimmed["inline"]["packet"]["claims"].clear()
    inflated = {**delivery, "guidance": delivery["guidance"] + " (edited)"}
    cases = [(dict(action="implement"), "read-only dge_role"), (dict(action=None), "read-only dge_role"),
             (dict(read_only=False), "read-only dge_role"), (dict(stage="dge:dba"), "role, stage and agent"),
             (dict(stage=None), "role, stage and agent"), (dict(agent="lead:dba"), "role, stage and agent"),
             (dict(delivery=trimmed), "not the projection"), (dict(delivery=inflated), "not the projection"),
             (dict(delivery={"schema": "urn:zeus:council-delivery:1"}), "names no debate role"),
             (dict(delivery={"inline": {"role": "dba"}}), "names no debate role"),
             (dict(delivery={**delivery, "inline": {**delivery["inline"], "role": "research_lead"}}, stage="dge:research_lead",
                   agent="lead:research"), "role mismatch")]
    for overrides, message in cases:
        with pytest.raises(ContractError, match=message):
            run(**overrides)


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


def test_recovery_sources_that_exceed_the_host_allowance_fail_safely_before_the_provider(tmp_path, monkeypatch):
    # INJECTED: a bound checkpoint and progress row for the same conductor task (a retried attempt), exactly the
    # rows the earlier delivery test injected. Measured in this batch at the pinned revision: the two recovery
    # evidence items plus the full reader catalogue put the complete prompt 4721 bytes outside the serialized
    # delivery, over the 4096 host allowance. The refusal is the typed needs_scope_split BEFORE any provider entry;
    # nothing is omitted, resized or retried and the raw task artifact is stored unchanged.
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
