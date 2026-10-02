"""Ported SOURCE M7 suite `tests/test_research_attempt_scope_receipt.py` (e38aa722) run against the S8 target (DESIGN-s8 §29).

Every assertion is M7's, unchanged. Adaptations, all import-only: the domain modules come from `codex_harness.research.domain` (`research_attempt_scope`, `research_program`, `research_investigations`, `audit_progress`) and `codex_harness.coordination.domain` (`continuation`, `owner_actions`), `family_id` and the portfolio buckets from `intake.domain.portfolio`, the owner-action/continuation/research bucket names from the `state` modules of `coordination.application`, `digest`/`canonical` from `kernel.ids`, `MemoryStore` from `storage.adapters.memory_store`; `packaged_policy` and `OwnerActions` come from the `m7_research` shim (see its docstring).

M7 docstring follows.

INV-RESEARCH-ATTEMPT-SCOPE-001 and INV-CONTINUATION-001: the attempt-scope research receipt (U2(b) PR-1,
FLEET-U2B-SPEC rows U2B-1 and U2B-14).

A schema-1 receipt may name the held intent's own `attempt-scope.<intent id>` claim instead of a Portfolio
investigation. It is checked against that exact claim (derived identity, scope binding, full member capture,
unchanged cause) after the unchanged held-intent, evidence and inspection checks, needs the resolved accepted
claim and its bound run, and is `original_capture` only. Once a scope claim exists for an intent, a receipt,
supplement or mixed receipt naming any other identity holds as `research_scope_claimed` on acceptance, on a
cached replay, in the writer transaction and at consumption. A family receipt with no scope claim is unchanged.

Every attempt-scope claim here is a LABELLED synthetic row built by the domain's own snapshot and dispatch
constructors (the claim writer is another layer), with a synthetic council run row: no program claim, council,
model, provider or network ran. The pure tests use literal dictionaries; the store tests use real MemoryStores,
the real `Fleet`, finite `Operation` with the `FakeExecutor` fixture and the real continuation owner.
"""
from __future__ import annotations

from copy import deepcopy

import pytest
from test_continuation import World, only
from test_continuation_research import (
    ATTESTATION,
    EVIDENCE,
    held,
    mixed_family,
    mixed_for,
    receipt_for,
    receipts,
    supplements,
    two_strikes,
)

from codex_harness.coordination.application.continuation.state import BUCKET_INTENTS
from codex_harness.coordination.application.owner_actions.state import BUCKET_DISPATCHES
from codex_harness.coordination.domain import continuation as dc
from codex_harness.intake.domain.portfolio import BUCKET_INVESTIGATIONS, family_id
from codex_harness.kernel.ids import digest
from codex_harness.research.domain import audit_progress as ap
from codex_harness.research.domain import research_attempt_scope as ras
from codex_harness.research.domain import research_investigations as ri
from codex_harness.research.domain.research_program import candidate_id, candidate_key

FROZEN = "2026-09-28T00:00:00+00:00"
INTENT, OTHER, POLICY_SHA = "1" * 64, "2" * 64, "3" * 64
PAIRS = [{"job": "job-a", "evidence_sha256": "4" * 64}, {"job": "job-b", "evidence_sha256": "5" * 64}]
CAUSE = ("failed", "evidence_gate_refused")
BOUND = ("program", "run_id", "manifest_sha256", "snapshot_sha256")
RECOVERIES, HEADS, SUCCESSORS = "research_dispatch_recoveries", "research_dispatch_heads", "research_dispatch_successors"


def claim_row(*, intent_id=INTENT, attempts=PAIRS, family="job-a", policy_id="policy-1", policy_sha256=POLICY_SHA,
              cause=CAUSE, program="rp-scope", state="resolved", result="accepted") -> dict:
    """LABELLED synthetic attempt-scope claim, resolved: exactly what the claim layer stores for one held
    intent, built by `scope_snapshot` and `dispatch_row` (never truncated, `scope` bound)."""
    candidate = {"investigation": dc.attempt_scope_id(intent_id), "intent_id": intent_id,
                 "continuation_policy": policy_id, "policy_sha256": policy_sha256, "family": family,
                 "family_investigation": family_id(*cause), "family_status": cause[0], "reason_code": cause[1],
                 "attempts": [dict(a) for a in attempts], "job_ids": sorted(a["job"] for a in attempts),
                 "projects": ["ops"]}
    document = ras.scope_snapshot(candidate=candidate, program_id=program, cycle_number=1, topic="storage",
                                  observed_at=FROZEN)
    row = ri.dispatch_row(document=document, candidate_id=ras.candidate_identity(intent_id),
                          cycle_ref=program + ":001", now=FROZEN)
    return {**row, "state": state, "result": result, "run_id": program + ".c001", "manifest_sha256": "d" * 64}


def pure():
    """One held intent, its two current attempt pairs, the Fleet rows, the lane observation, the scope claim
    and its accepted run: a scope receipt that every check accepts. No Portfolio row is supplied."""
    dispatch = claim_row()
    facts = {"intent": {"id": INTENT, "policy_id": "policy-1", "policy_sha256": POLICY_SHA, "route": dc.RESEARCH,
                        "state": dc.RESEARCH_REQUIRED, "family": "job-a"},
             "attempts": [dict(a) for a in PAIRS], "policy": {"id": "policy-1", "policy_sha256": POLICY_SHA},
             "jobs": {a["job"]: {"id": a["job"], "status": CAUSE[0], "reason_code": CAUSE[1]} for a in PAIRS},
             "observed": {a["job"]: {"evidence_sha256": a["evidence_sha256"], "inspection": "insp-" + a["job"]}
                          for a in PAIRS},
             "investigation": None, "dispatch": dispatch,
             "run_result": {"result": "accepted", "reason_code": None, "row_status": "accepted"}}
    receipt = dc.validate_research_receipt({
        "schema": dc.RESEARCH_RECEIPT_SCHEMA, "intent_id": INTENT, "policy_id": "policy-1",
        "policy_sha256": POLICY_SHA, "family": "job-a",
        "attempts": [{**a, "inspection": "insp-" + a["job"]} for a in PAIRS], "investigation": dispatch["id"],
        "dispatch": {k: dispatch[k] for k in BOUND}, "evidence_refs": ["sha256:" + "6" * 64]})
    return receipt, facts


# ---- U2B-1: one derived identity that nothing else can collide with -----------------------------------
def test_scope_identity_is_derived_full_length_pattern_valid_and_never_a_family_audit_or_lineage_key():
    intents = [INTENT, OTHER, digest({"labelled": "fixture intent"})]
    family, audit = family_id(*CAUSE), ap.candidate_identity("epoch-1")
    foreign = [family, audit, ri.replacement_dispatch_id(family), ri.successor_dispatch_id(family, 3),
               ri.successor_key(family, 2), ri.lineage_dispatch_id(family, 0), ri.replacement_dispatch_id(audit)]
    for intent in intents:
        scope = dc.attempt_scope_id(intent)
        assert scope == dc.attempt_scope_id(intent) == dc.ATTEMPT_SCOPE_PREFIX + intent and len(scope) == 78
        assert dc.INVESTIGATION_REF.fullmatch(scope) and ri.INVESTIGATION_ID.fullmatch(scope)
        assert not dc.SHA256.fullmatch(scope), "never a bare 64-hex family or audit id"
        assert scope not in foreign and not any(key.startswith(dc.ATTEMPT_SCOPE_PREFIX) for key in foreign)
        candidate = ras.candidate_identity(intent)
        assert candidate == "as-" + intent and len(candidate) == 67, "the full id, never a shortened second one"
        assert candidate not in {candidate_id(candidate_key(ri.SOURCE, scope)), ap.candidate_label(intent)}
    assert len({dc.attempt_scope_id(i) for i in intents}) == len(intents)
    for bad in (INTENT[:24], ("ab" * 32).upper(), INTENT + "0", dc.attempt_scope_id(INTENT), None, 1):
        with pytest.raises(dc.ContinuationRefused) as info:
            dc.attempt_scope_id(bad)
        assert info.value.reason_code == "research_scope_foreign", "refused, never truncated"


# ---- U2B-14: the exact scope receipt, checked without any Portfolio read -------------------------------
def test_an_exact_scope_receipt_is_original_capture_without_a_portfolio_row_or_a_supplement():
    receipt, facts = pure()
    assert dc.check_research_receipt(receipt, **facts) == dc.COVERAGE_ORIGINAL
    # A Portfolio row that the legacy membership gate would refuse is never read for a scope receipt.
    foreign = {"id": family_id(*CAUSE), "kind": "failure_family", "job_ids": [], "family_status": "rejected",
               "reason_code": "lead_rejected"}
    assert dc.check_research_receipt(receipt, **{**facts, "investigation": foreign}) == dc.COVERAGE_ORIGINAL
    # A supplement, even one naming this binding, never becomes the coverage of a scope.
    assert dc.check_research_receipt(receipt, **facts, supplement={"intent_id": INTENT}) == dc.COVERAGE_ORIGINAL


def _scope(facts, **change):
    facts["dispatch"]["scope"] = {**facts["dispatch"]["scope"], **change}


def _members(facts, ids):
    facts["dispatch"].update(job_ids=ids, job_ids_total=len(ids), job_ids_sha256=digest(ids))


REFUSALS = [
    # identity and scope binding
    ("another_intents_scope", lambda r, f: r.update(investigation=dc.attempt_scope_id(OTHER)), "research_scope_foreign"),
    ("scope_intent", lambda r, f: _scope(f, intent_id=OTHER), "research_scope_foreign"),
    ("scope_policy", lambda r, f: _scope(f, continuation_policy="policy-2"), "research_scope_foreign"),
    ("scope_policy_digest", lambda r, f: _scope(f, policy_sha256="7" * 64), "research_scope_foreign"),
    ("scope_family", lambda r, f: _scope(f, family="job-b"), "research_scope_foreign"),
    ("scope_attempt_pair", lambda r, f: _scope(f, attempts=[PAIRS[0], {**PAIRS[1], "evidence_sha256": "8" * 64}]),
     "research_scope_foreign"),
    ("scope_attempt_hash", lambda r, f: _scope(f, attempts_sha256="9" * 64), "research_scope_foreign"),
    ("scope_fewer_attempts", lambda r, f: _scope(f, attempts=PAIRS[:1], attempts_sha256=digest(PAIRS[:1])),
     "research_scope_foreign"),
    ("scope_schema", lambda r, f: _scope(f, schema="urn:zeus:research-attempt-scope:2"), "research_scope_foreign"),
    ("scope_unknown_key", lambda r, f: _scope(f, extra=None), "research_scope_foreign"),
    ("scope_absent", lambda r, f: f["dispatch"].update(scope=None), "research_scope_foreign"),
    ("claim_row_key", lambda r, f: f["dispatch"].update(id=ri.replacement_dispatch_id(r["investigation"])),
     "research_scope_foreign"),
    # full member capture: count, members and digest, never a sample
    ("member_count", lambda r, f: f["dispatch"].update(job_ids_total=3), "research_scope_mismatch"),
    ("member_missing", lambda r, f: _members(f, ["job-a"]), "research_scope_mismatch"),
    ("member_extra", lambda r, f: _members(f, ["job-a", "job-b", "job-c"]), "research_scope_mismatch"),
    ("member_digest", lambda r, f: f["dispatch"].update(job_ids_sha256="0" * 64), "research_scope_mismatch"),
    # the current cause of every member
    ("member_status", lambda r, f: f["jobs"]["job-b"].update(status="rejected"), "research_scope_membership"),
    ("member_reason", lambda r, f: f["jobs"]["job-a"].update(reason_code="lead_rejected"), "research_scope_membership"),
    ("claim_cause_absent", lambda r, f: f["dispatch"].update(family_status=None), "research_scope_membership"),
    # the unchanged held-intent, evidence and inspection checks
    ("receipt_policy_digest", lambda r, f: r.update(policy_sha256="7" * 64), "research_policy_foreign"),
    ("intent_not_held", lambda r, f: f["intent"].update(state=dc.COMPLETED), "research_intent_not_held"),
    ("attempt_set_grew", lambda r, f: f["attempts"].append({"job": "job-c", "evidence_sha256": "a" * 64}),
     "research_coverage_partial"),
    ("observed_evidence", lambda r, f: f["observed"]["job-a"].update(evidence_sha256="0" * 64),
     "research_attempt_changed"),
    ("inspection", lambda r, f: f["observed"]["job-b"].update(inspection="insp-other"), "research_inspection_mismatch"),
    # the resolved accepted claim and its bound run
    ("run_binding", lambda r, f: r.update(dispatch={**r["dispatch"], "run_id": "rp-scope.c999"}),
     "research_dispatch_mismatch"),
    ("claim_kind", lambda r, f: f["dispatch"].update(kind="failure_family"), "research_dispatch_mismatch"),
    ("claim_unfinished", lambda r, f: f["dispatch"].update(state="dispatched"), "research_unfinished"),
    ("claim_rejected", lambda r, f: f["dispatch"].update(result="rejected"), "research_not_accepted"),
    ("run_row_unknown", lambda r, f: f.update(run_result={"result": "unknown", "reason_code": "run_row_missing",
                                                          "row_status": None}), "research_not_accepted"),
    ("claim_absent", lambda r, f: f.update(dispatch=None), "research_dispatch_unknown"),
]


@pytest.mark.parametrize("change, reason", [case[1:] for case in REFUSALS], ids=[case[0] for case in REFUSALS])
def test_every_wrong_scope_member_cause_evidence_or_run_binding_refuses_by_name(change, reason):
    receipt, facts = pure()
    change(receipt, facts)
    with pytest.raises(dc.ContinuationRefused) as info:
        dc.check_research_receipt(receipt, **facts, supplement={"intent_id": INTENT})
    assert info.value.reason_code == reason


def test_the_held_intent_checks_run_first_and_a_partial_capture_never_falls_back_to_a_supplement():
    receipt, facts = pure()
    _scope(facts, intent_id=OTHER)
    facts["observed"]["job-a"]["inspection"] = "insp-other"
    with pytest.raises(dc.ContinuationRefused, match="research_inspection_mismatch"):
        dc.check_research_receipt(receipt, **facts)
    receipt, facts = pure()
    _members(facts, ["job-a"])      # the legacy gate would ask for a supplement here
    supplement = {**{k: receipt[k] for k in ("intent_id", "policy_id", "policy_sha256", "family", "attempts",
                                              "investigation")}, "dispatch": dict(receipt["dispatch"])}
    with pytest.raises(dc.ContinuationRefused) as info:
        dc.check_research_receipt(receipt, **facts, supplement=supplement)
    assert info.value.reason_code == "research_scope_mismatch"


def test_the_expected_dispatch_kind_keeps_its_legacy_default_for_a_family_receipt():
    receipt, facts = pure()
    investigation = family_id(*CAUSE)
    family = {**facts["dispatch"], "id": investigation, "investigation": investigation, "kind": "failure_family",
              "scope": None}
    legacy = {**receipt, "investigation": investigation}
    portfolio = {"id": investigation, "job_ids": ["job-a", "job-b"], "family_status": CAUSE[0],
                 "reason_code": CAUSE[1]}
    facts = {**facts, "investigation": portfolio}
    assert dc.check_research_receipt(legacy, **{**facts, "dispatch": family}) == dc.COVERAGE_ORIGINAL
    unkinded = {k: v for k, v in family.items() if k not in {"kind", "scope", "id"}}     # a pre-kind legacy row
    assert dc.check_research_receipt(legacy, **{**facts, "dispatch": unkinded}) == dc.COVERAGE_ORIGINAL
    # A family receipt never takes an attempt-scope row as its capture.
    with pytest.raises(dc.ContinuationRefused, match="research_dispatch_mismatch"):
        dc.check_research_receipt(legacy, **{**facts, "dispatch": {**family, "kind": ras.KIND}})


def _mixed(investigation=None, dispatch_id=None, member_investigation=None):
    receipt, _ = pure()
    family, other = family_id(*CAUSE), family_id("rejected", "lead_rejected")
    return dc.validate_mixed_receipt({
        **{k: receipt[k] for k in ("intent_id", "policy_id", "policy_sha256", "family", "evidence_refs")},
        "schema": dc.MIXED_RECEIPT_SCHEMA, "investigation": investigation or family,
        "attempts": [{**receipt["attempts"][0], "investigation": member_investigation or other, "status": "rejected",
                      "reason_code": "lead_rejected"},
                     {**receipt["attempts"][1], "investigation": family, "status": CAUSE[0], "reason_code": CAUSE[1]}],
        "lineage": [{"parent_job": "job-a", "job": "job-b", "intent_id": OTHER}],
        "dispatch": {**receipt["dispatch"], "id": dispatch_id or family, "job_ids_sha256": "e" * 64},
        "captured": ["job-b"], "acceptance": {"graph_sha256": "7" * 64, "candidate_revision": "9" * 40,
                                              "decision_id": "review-003"},
        "attestation_ref": "sha256:" + "f" * 64})


def _supplement(investigation=None, dispatch_id=None):
    receipt, _ = pure()
    family = family_id(*CAUSE)
    return dc.validate_scope_supplement({
        **{k: receipt[k] for k in ("intent_id", "policy_id", "policy_sha256", "family", "attempts")},
        "schema": dc.SUPPLEMENT_SCHEMA, "investigation": investigation or family,
        "dispatch": {**receipt["dispatch"], "id": dispatch_id or family, "job_ids_sha256": "e" * 64},
        "captured": ["job-a"], "descendants": [{"job": "job-b", "parent_job": "job-a", "intent_id": OTHER}],
        "acceptance": {"graph_sha256": "7" * 64, "candidate_revision": "9" * 40, "decision_id": "review-003"},
        "report_ref": "sha256:" + "6" * 64, "attestation_ref": "sha256:" + "f" * 64})


def test_a_mixed_receipt_or_an_owner_supplement_naming_a_scope_refuses_explicitly():
    receipt, facts = pure()
    scope = receipt["investigation"]
    reads = {k: facts[k] for k in ("intent", "attempts", "policy", "jobs", "observed", "dispatch", "run_result")}
    mixed = {**reads, "investigations": {}, "lineage": {}, "bindings": {}, "acceptance": {}}
    for document in (_mixed(investigation=scope), _mixed(dispatch_id=scope), _mixed(member_investigation=scope)):
        with pytest.raises(dc.ContinuationRefused) as info:
            dc.check_mixed_receipt(document, **mixed)
        assert info.value.reason_code == "research_scope_original_only"
    with pytest.raises(dc.ContinuationRefused) as info:
        dc.check_mixed_receipt(_mixed(), **mixed)
    assert info.value.reason_code != "research_scope_original_only", "a family mixed receipt keeps its own checks"
    supplement = {**reads, "investigation": None, "lineage": {}, "bindings": {}, "acceptance": {}}
    for document in (_supplement(investigation=scope), _supplement(dispatch_id=scope)):
        with pytest.raises(dc.ContinuationRefused) as info:
            dc.check_scope_supplement(document, **supplement)
        assert info.value.reason_code == "research_scope_original_only"
    with pytest.raises(dc.ContinuationRefused) as info:
        dc.check_scope_supplement(_supplement(), **supplement)
    assert info.value.reason_code != "research_scope_original_only"


# ---- the store path: a synthetic claim, the real continuation owner ------------------------------------
def claim(world, research, *, program="rp-scope") -> dict:
    """LABELLED synthetic attempt-scope claim of `research` in the control store, resolved and accepted, and
    its council run row: the claim writer and the council are other layers and do not run here."""
    with world.control.transaction() as tx:
        intents = [row for row in tx.scan(BUCKET_INTENTS) if row.get("policy_id") == "policy-1"]
    attempts = dc.research_attempts(intents, research)
    job = world.jobs()[attempts[0]["job"]]
    row = claim_row(intent_id=research["id"], attempts=attempts, family=research["family"],
                    policy_sha256=research["policy_sha256"], cause=(job["status"], job["reason_code"]), program=program)
    with world.control.transaction() as tx:
        tx.put(BUCKET_DISPATCHES, row["id"], row)
        tx.put("autonomous_runs", row["run_id"], {"id": row["run_id"], "manifest_sha256": row["manifest_sha256"],
                                                  "status": "accepted", "reason_code": None})
    return row


def unclaim(world, row):
    """LABELLED fixture surgery (claims are permanent in production): the control case without the claim."""
    world.control.data.pop((BUCKET_DISPATCHES, row["id"]))


def scoped(world, tmp_path):
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    return root, successor, research, claim(world, research)


def test_an_exact_scope_receipt_is_accepted_and_consumed_once_as_original_capture_with_no_portfolio_row(tmp_path):
    world = World(tmp_path)
    root, successor, research, row = scoped(world, tmp_path)
    with world.control.transaction() as tx:
        assert tx.scan(BUCKET_INVESTIGATIONS) == [], "no Portfolio investigation exists at all"
    before = deepcopy(row)
    document = receipt_for(world, research, row["id"], row)
    accepted = world.controller.accept_research(document)
    assert accepted["accepted"] is True and accepted["cached"] is False and accepted["coverage"] == "original_capture"
    assert accepted["investigation"] == dc.attempt_scope_id(research["id"])
    assert accepted["covered_jobs"] == sorted([root, successor]) == row["job_ids"]
    assert world.controller.accept_research(document)["cached"] is True
    world.tick()
    done = world.intents()[research["id"]]
    assert done["state"] == dc.COMPLETED and done["research_coverage"] == "original_capture"
    assert done["research_receipt"] == receipts(world)[research["id"]]["receipt_sha256"]
    world.tick(controller=world.build())
    assert [h["state"] for h in world.intents()[research["id"]]["history"]].count(dc.COMPLETED) == 1
    with world.control.transaction() as tx:
        assert tx.get(BUCKET_DISPATCHES, row["id"]) == before, "the claim is never rewritten"


def _other_scope(world, research, row, document):
    return {**document, "investigation": dc.attempt_scope_id("0" * 64)}


def _wrong_inspection(world, research, row, document):
    return {**document, "attempts": [{**document["attempts"][0], "inspection": "insp-other"},
                                     document["attempts"][1]]}


def _other_run(world, research, row, document):
    return {**document, "dispatch": {**document["dispatch"], "run_id": "rp-001.c001"}}


def _members_changed(world, research, row, document):
    with world.control.transaction() as tx:     # LABELLED injected fault: a forged claim row
        tx.put(BUCKET_DISPATCHES, row["id"], {**row, "job_ids_total": row["job_ids_total"] + 1})
    return document


def _cause_changed(world, research, row, document):
    with world.control.transaction() as tx:
        tx.put(BUCKET_DISPATCHES, row["id"], {**row, "reason_code": "lead_rejected"})
    return document


def _rejected(world, research, row, document):
    with world.control.transaction() as tx:
        tx.put("autonomous_runs", row["run_id"], {**tx.get("autonomous_runs", row["run_id"]), "status": "rejected"})
    return document


@pytest.mark.parametrize("change, reason", [
    (_other_scope, "research_scope_claimed"), (_wrong_inspection, "research_inspection_mismatch"),
    (_other_run, "research_dispatch_mismatch"), (_members_changed, "research_scope_mismatch"),
    (_cause_changed, "research_scope_membership"), (_rejected, "research_not_accepted")])
def test_a_wrong_scope_receipt_is_refused_through_the_owner_and_stays_held(tmp_path, change, reason):
    world = World(tmp_path)
    root, successor, research, row = scoped(world, tmp_path)
    document = change(world, research, row, receipt_for(world, research, row["id"], row))
    with pytest.raises(dc.ContinuationRefused) as info:
        world.controller.accept_research(document)
    assert info.value.reason_code == reason
    assert receipts(world) == {}
    world.tick()
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED


def test_another_intents_scope_is_foreign_while_this_intent_holds_no_claim(tmp_path):
    world = World(tmp_path)
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    y_root, y_successor, other = two_strikes(world, "op-y", "docs/b.md")
    row = claim(world, other)
    with pytest.raises(dc.ContinuationRefused, match="research_scope_foreign"):
        world.controller.accept_research(receipt_for(world, research, row["id"], row))
    assert receipts(world) == {}


def test_a_scope_receipt_rechecked_at_consumption_holds_when_the_claim_no_longer_matches(tmp_path):
    world = World(tmp_path)
    root, successor, research, row = scoped(world, tmp_path)
    world.controller.accept_research(receipt_for(world, research, row["id"], row))
    with world.control.transaction() as tx:     # LABELLED injected fault after acceptance
        tx.put(BUCKET_DISPATCHES, row["id"], {**row, "job_ids": [root]})
    ticked = world.tick()
    assert [s["reason_code"] for s in ticked["skipped"] if s["subject"] == research["id"]] == [
        "research_scope_mismatch"]
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED


@pytest.mark.skip(reason="S8: batch U (Portfolio, DEFINITIONS, build, registered, FakeCouncil: unavailable placeholders in test_continuation_research.py)")
def test_a_family_receipt_for_a_scoped_intent_refuses_research_scope_claimed_on_accept_supplement_and_recheck(
        tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    document = receipt_for(world, research, investigation, dispatch)
    row = claim(world, research)
    before = deepcopy(world.control.data)
    with pytest.raises(dc.ContinuationRefused) as info:
        world.controller.accept_research(document)
    assert (info.value.reason_code, info.value.field) == ("research_scope_claimed", "dispatch")
    # The owner's reader names the same held condition, and a supplement of the family is refused alike.
    assert world.controller.research_facts(document)["recovery_held"] == "scope_claimed"
    repair = only(world.intents(), origin_job=root, route=dc.EVIDENCE_REPAIR)
    family_supplement = {
        "schema": dc.SUPPLEMENT_SCHEMA,
        **{k: document[k] for k in ("intent_id", "policy_id", "policy_sha256", "family", "attempts", "investigation")},
        "dispatch": {**document["dispatch"], "id": dispatch["id"], "job_ids_sha256": dispatch["job_ids_sha256"]},
        "captured": [root], "descendants": [{"job": successor, "parent_job": root, "intent_id": repair["id"]}],
        "acceptance": {"graph_sha256": "7" * 64, "candidate_revision": "9" * 40, "decision_id": "review-003"},
        "report_ref": EVIDENCE[0], "attestation_ref": world.artifacts.put(ATTESTATION, "owner-attestation")["ref"]}
    with pytest.raises(dc.ContinuationRefused, match="research_scope_claimed"):
        world.controller.supplement_research_scope(family_supplement)
    assert receipts(world) == {} and supplements(world) == {}
    assert world.control.data == before, "a refusal writes nothing"

    # Control (the claim removed): the very same family receipt is accepted.
    unclaim(world, row)
    assert world.controller.accept_research(document)["cached"] is False
    # A claim appearing after acceptance: the cached replay and the consumption both hold.
    claim(world, research)
    with pytest.raises(dc.ContinuationRefused, match="research_scope_claimed"):
        world.controller.accept_research(document)
    ticked = world.tick()
    assert [s["reason_code"] for s in ticked["skipped"] if s["subject"] == research["id"]] == [
        "research_scope_claimed"]
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED and len(world.jobs()) == 2


@pytest.mark.skip(reason="S8: batch U (Portfolio, DEFINITIONS, build, registered, FakeCouncil: unavailable placeholders in test_continuation_research.py)")
def test_the_writer_transaction_rechecks_a_scope_claim_that_appeared_after_verification(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    document, controller = receipt_for(world, research, investigation, dispatch), world.build()
    verify = controller._verify_evidence

    def between(refs):      # LABELLED forced interleaving: a claim commits between the reads and the write
        verify(refs)
        claim(world, research)
    controller._verify_evidence = between
    with pytest.raises(dc.ContinuationRefused, match="research_scope_claimed"):
        controller.accept_research(document)
    assert receipts(world) == {}


@pytest.mark.skip(reason="S8: batch U (Portfolio, DEFINITIONS, build, registered, FakeCouncil: unavailable placeholders in test_continuation_research.py)")
def test_a_mixed_receipt_cannot_cover_or_bypass_a_scope(tmp_path):
    world = World(tmp_path)
    family = mixed_family(world, tmp_path)
    research = family["research"]
    document = mixed_for(world, family)
    row = claim(world, research)
    with pytest.raises(dc.ContinuationRefused, match="research_scope_claimed"):
        world.controller.accept_research(document)
    scope = row["id"]
    with pytest.raises(dc.ContinuationRefused, match="research_scope_original_only"):
        world.controller.accept_research(mixed_for(world, family, investigation=scope,
                                                   dispatch={**document["dispatch"], "id": scope}))
    unclaim(world, row)
    member = [{**document["attempts"][0], "investigation": scope}, *document["attempts"][1:]]
    with pytest.raises(dc.ContinuationRefused, match="research_scope_original_only"):
        world.controller.accept_research({**document, "attempts": member})
    assert set(receipts(world)) == {family["earlier"]["id"]}
    # Control: with no scope claim the unchanged mixed receipt is accepted.
    assert world.controller.accept_research(document)["coverage"] == "mixed_family"


def test_an_owner_supplement_naming_the_scope_is_refused_and_nothing_is_recorded(tmp_path):
    world = World(tmp_path)
    root, successor, research, row = scoped(world, tmp_path)
    receipt = receipt_for(world, research, row["id"], row)
    repair = only(world.intents(), origin_job=root, route=dc.EVIDENCE_REPAIR)
    document = {
        "schema": dc.SUPPLEMENT_SCHEMA,
        **{k: receipt[k] for k in ("intent_id", "policy_id", "policy_sha256", "family", "attempts", "investigation")},
        "dispatch": {**receipt["dispatch"], "id": row["id"], "job_ids_sha256": row["job_ids_sha256"]},
        "captured": [root], "descendants": [{"job": successor, "parent_job": root, "intent_id": repair["id"]}],
        "acceptance": {"graph_sha256": "7" * 64, "candidate_revision": "9" * 40, "decision_id": "review-003"},
        "report_ref": EVIDENCE[0], "attestation_ref": world.artifacts.put(ATTESTATION, "owner-attestation")["ref"]}
    with pytest.raises(dc.ContinuationRefused, match="research_scope_original_only"):
        world.controller.supplement_research_scope(document)
    assert supplements(world) == {}
    # The scope receipt itself is still covered by its original capture only.
    assert world.controller.accept_research(receipt)["coverage"] == "original_capture"


# ---- U2B-1: no recovery or successor head ever redirects a scope ---------------------------------------
@pytest.mark.skip(reason="S8: batch U (Portfolio, DEFINITIONS, build, registered, FakeCouncil: unavailable placeholders in test_continuation_research.py)")
def test_no_family_or_forged_recovery_or_head_redirects_a_scope_dispatch(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    row = claim(world, research)
    scope = row["id"]
    document = receipt_for(world, research, scope, row)
    replacement = {**row, "id": ri.replacement_dispatch_id(scope), "run_id": "rp-forged.c001"}
    with world.control.transaction() as tx:     # LABELLED forged lineage rows the writers never create
        tx.put(BUCKET_DISPATCHES, replacement["id"], replacement)
        tx.put("autonomous_runs", "rp-forged.c001", {"id": "rp-forged.c001", "manifest_sha256": row["manifest_sha256"],
                                                     "status": "accepted", "reason_code": None})
        tx.put(RECOVERIES, scope, {"id": scope, "investigation": scope, "state": "authorized",
                                   "replacement": {"dispatch": replacement["id"]}})
        tx.put(HEADS, investigation, {"dispatch": scope, "version": 2})
    facts = world.controller.research_facts(document)
    assert facts["dispatch"] == row and facts["recovery_held"] is None, "the scope row itself, never redirected"
    with pytest.raises(dc.ContinuationRefused, match="research_dispatch_mismatch"):
        world.controller.accept_research({**document, "dispatch": {**document["dispatch"], "run_id": "rp-forged.c001"}})
    # A family head naming the scope row never lends it to the family receipt.
    with pytest.raises(dc.ContinuationRefused, match="research_scope_claimed"):
        world.controller.accept_research(receipt_for(world, research, investigation, dispatch))
    accepted = world.controller.accept_research(document)
    assert accepted["dispatch"]["run_id"] == row["run_id"] and accepted["coverage"] == "original_capture"
    # A forged successor head at the scope key: still the scope row, and the lineage holds rather than answers.
    with world.control.transaction() as tx:
        tx.put(HEADS, scope, {"dispatch": replacement["id"], "version": 2})
    facts = world.controller.research_facts(document)
    assert facts["dispatch"] == row and facts["recovery_held"] == "recovery_successor_corrupt"
    with pytest.raises(dc.ContinuationRefused, match="research_recovery_successor_corrupt"):
        world.controller.accept_research(document)
    ticked = world.tick()
    assert [s["reason_code"] for s in ticked["skipped"] if s["subject"] == research["id"]] == [
        "research_recovery_successor_corrupt"]
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED
    with world.control.transaction() as tx:
        assert tx.scan(SUCCESSORS) == []
