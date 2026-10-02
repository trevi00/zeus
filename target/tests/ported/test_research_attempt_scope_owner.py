"""Ported SOURCE M7 suite `tests/test_research_attempt_scope_owner.py` (e38aa722) run against the S8 target (DESIGN-s8 §29).

Every assertion is M7's, unchanged. Adaptations, all import-only: the domain modules come from `codex_harness.research.domain` (`research_attempt_scope`, `research_program`, `research_investigations`, `audit_progress`) and `codex_harness.coordination.domain` (`continuation`, `owner_actions`), `family_id` and the portfolio buckets from `intake.domain.portfolio`, the owner-action/continuation/research bucket names from the `state` modules of `coordination.application`, `digest`/`canonical` from `kernel.ids`, `MemoryStore` from `storage.adapters.memory_store`; `packaged_policy` and `OwnerActions` come from the `m7_research` shim (see its docstring).

M7 docstring follows.

INV-RESEARCH-ATTEMPT-SCOPE-001 (U2(b) PR-1), owner-actions layer (FLEET-U2B-SPEC §1, §3 and the §4
INV-OWNER-ACTIONS-001 amendment): the scoped RO-1 decision table with its kept family disposition,
rivals and permanent overlap (U2B-12), the legacy reverse overlap and unchanged legacy policy digests
(U2B-12 pin), the exact scoped research outcome (U2B-13), and the owner's same-transaction scope read
and scope-only receipt binding.

LABELLED synthetic fixtures only: control-store rows built as dictionaries (or put into a MemoryStore),
a stand-in continuation `research_facts` reader (`FactsStandIn`), a stand-in lane evidence reader
(`LaneStandIn`) and a stand-in research launch port (`LaunchStandIn`) that only answers probes and polls.
Nothing here drives an executor, a provider, a model, a network or production state, and nothing here is
evidence of a live run. The legacy decision table itself is pinned, unmodified, by
tests/test_owner_actions_recovery.py.
"""
from __future__ import annotations

import copy

import pytest
from m7_research import OwnerActions

from codex_harness.coordination.application.owner_actions.state import (
    BUCKET_ACTIONS,
    BUCKET_CYCLES,
    BUCKET_DISPATCHES,
    BUCKET_PROGRAMS,
)
from codex_harness.coordination.domain import owner_actions as do
from codex_harness.coordination.domain.continuation import (
    RESEARCH_RECEIPT_SCHEMA,
    attempt_scope_id,
    research_attempts,
)
from codex_harness.intake.domain.portfolio import BUCKET_BINDINGS, BUCKET_INVESTIGATIONS, family_id
from codex_harness.kernel.ids import digest
from codex_harness.research.domain.research_attempt_scope import (
    candidate_identity,
    eligible_attempt_scopes,
    scope_snapshot,
)
from codex_harness.research.domain.research_investigations import dispatch_row
from codex_harness.research.domain.research_program import CYCLE_DONE, CYCLE_FAILED, cycle_id
from codex_harness.storage.adapters.memory_store import MemoryStore

POLICY, POLICY_SHA = "policy-1", digest(["labelled-fixture-policy", 1])
ROOT, OTHER_ROOT = "op-b2", "op-other"
STATUS, REASON = "failed", "worker_failed"
CAUSE = family_id(STATUS, REASON)
PROGRAM = "rp-scope"
NOW = "2026-09-28T00:00:00+00:00"
ROOM = {"ok": True, "remaining": 5}
SOURCE = {"topic": "storage", "continuation_policy": POLICY, "continuation_policy_sha256": POLICY_SHA,
          "families": [ROOT, OTHER_ROOT], "project_ids": ["zeus"], "reason_codes": [REASON]}
LEGACY_SOURCE = {"topic": "storage", "project_ids": ["zeus"], "reason_codes": [REASON]}
PAIR = ["job-f0", "job-s1"]


# ---- LABELLED synthetic rows ------------------------------------------------------------------------------
def intent(n: int, route: str, state: str, job: str, family: str = ROOT) -> dict:
    return {"id": digest(["labelled-fixture-intent", family, n]), "route": route, "state": state,
            "policy_id": POLICY, "policy_sha256": POLICY_SHA, "family": family, "origin_job": job,
            "evidence_sha256": digest(["labelled-fixture-evidence", job]), "lane": "a",
            "created_at": "2026-09-27T00:00:%02d+00:00" % n}


def job(job_id: str, status: str = STATUS, reason: str = REASON) -> dict:
    return {"id": job_id, "status": status, "reason_code": reason, "lane": "a"}


def lineage(family: str, first: str, second: str, base: int = 1) -> list:
    """A failed attempt, then the held research intent raised on it: the COMPLETE pair."""
    return [intent(base, "correction", "admitted", first, family),
            intent(base + 1, "research", "research_required", second, family)]


def program(config: dict | None = None, **fields) -> dict:
    row = {"id": PROGRAM, "state": "paused", "cycles": 0, "next_cycle": 1, "active_cycle": None, "adoptions": 0,
           "last_tick_at": None,
           "config": config or {"interval_seconds": 3600, "max_cycles": 2, "max_adoptions": 1,
                                "budget": {"per_host": 10, "total": 20}, "attempt_scope_source": copy.deepcopy(SOURCE)}}
    row.update(fields)
    return row


def fixture() -> tuple:
    """21-member-style history reduced to its shape: the cause row's historical members are never the
    capture; the held pair J_F0/S1 is. Returns (rows, held research intent)."""
    intents = lineage(ROOT, *PAIR)
    ids = [*PAIR, "job-h1", "job-h2"]
    rows = {"research_programs": [program()],
            "research_investigation_dispatches": [], "research_dispatch_recoveries": [], "research_dispatch_heads": [],
            "portfolio_investigations": [{"id": CAUSE, "kind": "failure_family", "state": "research_required",
                                          "family_status": STATUS, "reason_code": REASON,
                                          "job_ids": ["job-h1", "job-h2"]}],
            "fleet_jobs": [job(j) for j in ids],
            "portfolio_bindings": [{"job_id": j, "project_id": "zeus"} for j in ids],
            "continuation_policies": [{"id": POLICY, "policy_sha256": POLICY_SHA}],
            "continuation_intents": intents, "continuation_research_receipts": [],
            "research_dispatch_successors": []}
    return rows, intents[1]


def decide(rows: dict, held: dict, *, attempts=None, room=ROOM, family=CAUSE, investigation=None) -> dict:
    return do.research_decision(program_id=PROGRAM, investigation=investigation or attempt_scope_id(held["id"]),
                                attempts=sorted(attempts or PAIR), rows=rows, room=room, now=NOW,
                                family_investigation=family)


def the_program(rows: dict) -> dict:
    return next(r for r in rows["research_programs"] if r["id"] == PROGRAM)


def family_capture(ids, *, state="resolved", truncated=False, investigation="f" * 64) -> dict:
    """A LABELLED historical family dispatch capture (its full id set, or a truncated sample)."""
    return {"id": investigation, "investigation": investigation, "kind": "failure_family", "state": state,
            "family_status": STATUS, "reason_code": REASON, "job_ids": list(ids),
            "job_ids_total": len(ids) + (5 if truncated else 0), "job_ids_truncated": truncated,
            "result": "accepted", "program": "rp-old"}


def scope_claim(rows: dict, held: dict, *, cycle_ref: str | None = None, state="resolved", result="accepted") -> dict:
    """The claim row the transactional claim would write for this held intent, built from the SAME pure
    eligibility and snapshot helpers (LABELLED: no program runner ran)."""
    [candidate] = [c for c in eligible_attempt_scopes(
        source=SOURCE, policies=rows["continuation_policies"], intents=rows["continuation_intents"],
        receipts=rows["continuation_research_receipts"], jobs=rows["fleet_jobs"], bindings=rows["portfolio_bindings"],
        investigations=rows["portfolio_investigations"], dispatches=[], recoveries=[], heads=[],
        successors=[])["candidates"] if c["intent_id"] == held["id"]]
    document = scope_snapshot(candidate=candidate, program_id=PROGRAM, cycle_number=1, topic="storage", observed_at=NOW)
    row = dispatch_row(document=document, candidate_id=candidate_identity(held["id"]),
                       cycle_ref=cycle_ref or cycle_id(PROGRAM, 1), now=NOW)
    return {**row, "state": state, "result": result, "run_id": "run-scope", "manifest_sha256": "1" * 64}


# ===== U2B-12: the scoped owner decision table ==========================================================
def _claimed(bucket, **extra):
    def change(rows, held):
        scope = attempt_scope_id(held["id"])
        rows[bucket].append({"id": scope, "investigation": scope, **extra})
    return change


def _set_program(**fields):
    def change(rows, held):
        the_program(rows).update(fields)
    return change


def _second_lineage(rows, held):
    rows["continuation_intents"] += lineage(OTHER_ROOT, "job-o1", "job-o2", base=5)
    rows["fleet_jobs"] += [job("job-o1"), job("job-o2")]
    rows["portfolio_bindings"] += [{"job_id": j, "project_id": "zeus"} for j in ("job-o1", "job-o2")]


def _cause(**fields):
    def change(rows, held):
        rows["portfolio_investigations"][0].update(fields)
    return change


TABLE = {
    "ready": (None, {}, "research_ready_resume_then_tick", True),
    "active": (_set_program(state="active"), {}, "research_ready_tick", True),
    "not_due": (_set_program(state="active", last_tick_at=NOW), {}, "research_program_not_due", False),
    "busy": (_set_program(active_cycle="rp-scope:1"), {}, "research_program_busy", False),
    "paused_by_owner": (_set_program(cycles=1), {}, "research_program_paused_by_owner", False),
    "adoptions": (_set_program(adoptions=1), {}, "research_program_adoptions_consumed", False),
    "cycles_exhausted": (_set_program(state="active", cycles=2), {}, "research_program_completed", False),
    "program_completed": (_set_program(state="completed"), {}, "research_program_completed", False),
    "program_blocked": (_set_program(state="blocked"), {}, "research_program_blocked", False),
    "unregistered": (lambda rows, held: rows.update(research_programs=[]), {}, "research_program_unregistered", False),
    "unreadable_budget": (None, {"room": None}, "research_headroom_unreadable", False),
    "headroom": (None, {"room": {"ok": False, "remaining": 0}}, "research_headroom_insufficient", False),
    "dispositioned": (_cause(state="researched"), {}, "research_family_dispositioned", False),
    "cause_missing": (lambda rows, held: rows.update(portfolio_investigations=[]), {},
                      "research_family_dispositioned", False),
    "cause_ambiguous": (lambda rows, held: rows["portfolio_investigations"].append(
        dict(rows["portfolio_investigations"][0])), {}, "research_family_dispositioned", False),
    "cause_malformed": (_cause(reason_code="other_reason"), {}, "research_family_dispositioned", False),
    "cause_other_kind": (_cause(kind="audit_progress"), {}, "research_family_dispositioned", False),
    "cause_unknown": (None, {"family": None}, "research_family_dispositioned", False),
    "claimed_dispatch": (_claimed("research_investigation_dispatches", kind="attempt_scope"), {},
                         "research_dispatch_claimed", False),
    "claimed_recovery": (_claimed("research_dispatch_recoveries"), {}, "research_dispatch_claimed", False),
    "claimed_head": (_claimed("research_dispatch_heads"), {}, "research_dispatch_claimed", False),
    "claimed_successor": (_claimed("research_dispatch_successors"), {}, "research_dispatch_claimed", False),
    "ambiguous": (_second_lineage, {}, "research_eligible_ambiguous", False),
    "mixed": (None, {"attempts": ["job-f0"]}, "research_scope_mixed", False),
    "not_a_scope_id": (None, {"investigation": CAUSE}, "research_scope_not_eligible", False),
}


@pytest.mark.parametrize("case", sorted(TABLE))
def test_the_scoped_owner_decision_table(case):
    """U2B-12 (new): each case changes exactly one fact of the ready P1-shaped fixture."""
    change, kwargs, reason, act = TABLE[case]
    rows, held = fixture()
    if change is not None:
        change(rows, held)
    decision = decide(rows, held, **kwargs)
    assert (decision["act"], decision["reason"]) == (act, reason), decision
    if act:
        assert decision["detail"] == {"expected_cycle": 1}
    if case.startswith("claimed_"):
        assert decision["detail"]["claims"] == [case.removeprefix("claimed_")]
    if case == "ambiguous":
        other = [c for c in rows["continuation_intents"] if c["family"] == OTHER_ROOT and c["route"] == "research"]
        assert decision["detail"]["investigations"] == [attempt_scope_id(other[0]["id"])]


@pytest.mark.parametrize("case, count", [
    ("overlap_resolved", "overlap"), ("overlap_rejected", "overlap"), ("overlap_unknown", "overlap"),
    ("overlap_claimed", "overlap"), ("pinned_successor", "overlap"), ("truncated_same_cause", "overlap_unverifiable"),
    ("receipted", "receipted"), ("policy_changed", "policy"), ("policy_unregistered", "policy"),
    ("not_held", "state"), ("project", "project"), ("single_attempt", "insufficient_attempts"),
])
def test_forward_overlap_and_every_other_exclusion_names_its_count(case, count):
    """U2B-12 (new): no eligible scope is `research_scope_not_eligible` with the fixed exclusion counts, and
    forward overlap is surfaced there: a member in any stored capture (every state), in an authorized
    unclaimed successor's pin, or a same-cause truncated capture that cannot prove disjointness."""
    rows, held = fixture()
    attempts = PAIR
    if case.startswith("overlap_"):
        state = case.removeprefix("overlap_")
        rows["research_investigation_dispatches"].append(family_capture(["job-f0", "job-h1"], state=state))
    elif case == "pinned_successor":
        rows["research_dispatch_successors"].append({"id": "s-1", "investigation": "e" * 64, "state": "authorized",
                                                     "members": {"job_ids": ["job-s1"], "sha256": "2" * 64}})
    elif case == "truncated_same_cause":
        rows["research_investigation_dispatches"].append(family_capture(["job-h1"], truncated=True))
    elif case == "receipted":
        rows["continuation_research_receipts"].append({"id": held["id"]})
    elif case == "policy_changed":
        rows["continuation_policies"][0]["policy_sha256"] = "3" * 64
    elif case == "policy_unregistered":
        rows["continuation_policies"] = []
    elif case == "not_held":
        held["state"] = "completed"
    elif case == "project":
        rows["portfolio_bindings"][1]["project_id"] = "elsewhere"
    elif case == "single_attempt":
        rows["continuation_intents"] = [held]
        attempts = ["job-s1"]
    decision = decide(rows, held, attempts=attempts)
    assert (decision["act"], decision["reason"]) == (False, "research_scope_not_eligible"), decision
    counts = decision["detail"]["counts"]
    assert counts[count] == 1 and counts["eligible"] == 0, counts


def test_portfolio_membership_of_the_pair_alone_does_not_refuse():
    """U2B-12 / U2B-5 shape: the cause row gaining S1 is membership reconciliation, not a capture."""
    rows, held = fixture()
    rows["portfolio_investigations"][0]["job_ids"] += ["job-s1", "job-q1"]
    assert decide(rows, held)["reason"] == "research_ready_resume_then_tick"


def _rival(state, config):
    return {"id": "rp-rival", "state": state, "cycles": 0, "adoptions": 0, "active_cycle": None, "config": config}


SCOPED_RIVAL = {"attempt_scope_source": {**SOURCE, "families": [ROOT], "project_ids": ["another-project"]}}


@pytest.mark.parametrize("state", ["active", "paused", "stopped", "a-state-no-release-knows"])
@pytest.mark.parametrize("config", [SCOPED_RIVAL, {"investigation_source": LEGACY_SOURCE}], ids=["scoped", "legacy"])
def test_a_live_paused_stopped_or_unknown_rival_refuses(state, config):
    """U2B-12 (new): scoped rivals share the policy and a root family (never narrowed by project); legacy
    rivals name the cause reason. Stopped and unknown states are conservative rivals."""
    rows, held = fixture()
    rows["research_programs"].append(_rival(state, config))
    decision = decide(rows, held)
    assert (decision["act"], decision["reason"]) == (False, "research_competing_program")
    assert decision["detail"]["programs"] == ["rp-rival"]


@pytest.mark.parametrize("state", ["completed", "blocked"])
def test_a_completed_or_blocked_rival_does_not_refuse_but_its_stored_overlap_does(state):
    """U2B-12 (new): a terminal program is no rival, yet every claim it stored still reserves its members."""
    rows, held = fixture()
    rows["research_programs"].append(_rival(state, SCOPED_RIVAL))
    assert decide(rows, held)["reason"] == "research_ready_resume_then_tick"
    rows["research_investigation_dispatches"].append({**family_capture(["job-s1"]), "program": "rp-rival"})
    decision = decide(rows, held)
    assert decision["reason"] == "research_scope_not_eligible" and decision["detail"]["counts"]["overlap"] == 1


@pytest.mark.parametrize("config", [
    {"attempt_scope_source": {**SOURCE, "continuation_policy": "policy-2"}},
    {"attempt_scope_source": {**SOURCE, "families": ["op-unrelated"]}},
    {"investigation_source": {**LEGACY_SOURCE, "reason_codes": ["other_reason"]}},
    {"audit_progress_source": {"topic": "storage"}},
], ids=["other-policy", "other-family", "other-reason", "audit-progress"])
def test_programs_that_cannot_take_this_scope_are_not_rivals(config):
    rows, held = fixture()
    rows["research_programs"].append(_rival("active", config))
    assert decide(rows, held)["reason"] == "research_ready_resume_then_tick"


def test_the_scoped_decision_is_the_shared_rule_and_writes_nothing():
    """The same pure eligibility as the claim, over one read; the rows are never modified."""
    rows, held = fixture()
    before = copy.deepcopy(rows)
    decide(rows, held)
    assert rows == before


# ===== U2B-12 pin: the legacy branch, its reverse overlap and the unchanged policy digests ================
def legacy_fixture() -> tuple:
    """A legacy program over the cause family whose scoped members are exactly the pair. The rows carry
    NONE of the four keys the scoped branch reads: the legacy branch must never need them."""
    rows, held = fixture()
    for key in ("continuation_policies", "continuation_intents", "continuation_research_receipts",
                "research_dispatch_successors"):
        del rows[key]
    rows["research_programs"] = [program({"interval_seconds": 3600, "max_cycles": 2, "max_adoptions": 1,
                                          "budget": {"per_host": 10, "total": 20},
                                          "investigation_source": LEGACY_SOURCE})]
    rows["portfolio_investigations"][0]["job_ids"] = list(PAIR)
    return rows, held


def legacy_decide(rows):
    return do.research_decision(program_id=PROGRAM, investigation=CAUSE, attempts=PAIR, rows=rows, room=ROOM, now=NOW)


def test_with_no_scope_claim_the_legacy_decision_reads_no_scoped_rows():
    rows, _ = legacy_fixture()
    assert legacy_decide(rows) == {"act": True, "reason": "research_ready_resume_then_tick", "steps": ["resume", "tick"],
                                   "detail": {"expected_cycle": 1}}
    rows["research_investigation_dispatches"].append({**family_capture(["job-x"]), "investigation": "a" * 64,
                                                      "kind": "audit_progress", "job_ids": None})
    assert legacy_decide(rows)["reason"] == "research_ready_resume_then_tick", "membership-free kinds hold nothing"


@pytest.mark.parametrize("state, result", [("claimed", None), ("running", None), ("resolved", "accepted"),
                                           ("resolved", "rejected"), ("failed", None), ("resolved", "unknown")])
def test_a_scope_claim_in_any_state_holds_its_members_against_the_family(state, result):
    """U2B-12 pin / risk 3: reverse overlap is permanent, whatever the scope claim's result."""
    rows, held = legacy_fixture()
    scope_rows, _ = fixture()
    rows["research_investigation_dispatches"].append(scope_claim(scope_rows, held, state=state, result=result))
    decision = legacy_decide(rows)
    assert (decision["act"], decision["reason"]) == (False, "research_family_not_eligible")
    assert decision["detail"]["counts"]["claimed"] == 1 and decision["detail"]["counts"]["eligible"] == 0


def test_a_disjoint_scope_claim_leaves_the_family_decision_unchanged():
    rows, _ = legacy_fixture()
    expected = legacy_decide(rows)
    scope = attempt_scope_id("c" * 64)
    rows["research_investigation_dispatches"].append({"id": scope, "investigation": scope, "kind": "attempt_scope",
                                                      "state": "resolved", "family_status": STATUS,
                                                      "reason_code": REASON, "job_ids": ["job-h1", "job-h2"]})
    assert legacy_decide(rows) == expected


@pytest.mark.parametrize("reason, blocked", [(REASON, True), ("other_reason", False)])
def test_an_unreadable_scope_claim_holds_only_its_own_cause(reason, blocked):
    """Membership that cannot be read never proves disjointness for its cause; other causes are unaffected."""
    rows, _ = legacy_fixture()
    scope = attempt_scope_id("c" * 64)
    rows["research_investigation_dispatches"].append({"id": scope, "investigation": scope, "kind": "attempt_scope",
                                                      "state": "resolved", "family_status": STATUS,
                                                      "reason_code": reason, "job_ids": None})
    assert legacy_decide(rows)["reason"] == ("research_family_not_eligible" if blocked
                                             else "research_ready_resume_then_tick")


def _owner_policy(schema):
    document = {"schema": schema, "id": "owners-1", "enabled": True, "continuation_policy": "policy-1",
                "assessment": {"model_label": "labelled-fixture-assessor"},
                "delivery": {"target_id": "fleet-host", "repository": "github:zeus-owner/zeus-harness",
                             "required_checks": ["ci"], "canary_check_id": "startup_identity",
                             "ci_timeout_seconds": 300, "consumption_timeout_seconds": 120}, "canary": None}
    if schema == do.POLICY_SCHEMA_V2:
        document.update(id="owners-2", requalification={"enabled": True, "reasons": ["reviewed_base_moved"],
                                                        "max_per_family": 1},
                        research={"enabled": True, "program_id": PROGRAM, "lane": "a"})
    return document


def test_version1_and_version2_owner_policy_digests_are_unchanged():
    """U2B-12 pin: goldens computed from base main d71febf's own domain module (identical at 96d15cf); the scope
    capability adds no owner-policy field, so a registered v1/v2 policy keeps its digest."""
    assert do.policy_digest(do.validate_policy(_owner_policy(do.POLICY_SCHEMA))) \
        == "84d7ff081aff643755738942434a20b355c8b79187aa90115946579710f9d270"
    assert do.policy_digest(do.validate_policy(_owner_policy(do.POLICY_SCHEMA_V2))) \
        == "147dc220be1a28014389fd119b5a41a8fede2df044ed3e1f2154c73e41f1197d"


# ===== U2B-13: the scoped outcome is exact ================================================================
LAUNCH = do.research_launch_id("labelled-fixture-action", 1)


def outcome_world(**cycle_fields):
    rows, held = fixture()
    binding = do.research_dispatch_binding(held, {"program_id": PROGRAM}, attempt_scope_id(held["id"]), PAIR, 1)
    cycle = {"id": cycle_id(PROGRAM, 1), "owner": LAUNCH, "status": CYCLE_DONE,
             "selection": {"candidate": candidate_identity(held["id"])}, **cycle_fields}
    attempts = research_attempts(rows["continuation_intents"], held)
    return rows, held, binding, cycle, attempts


def outcome(binding, cycle, dispatch, attempts):
    return do.research_outcome(binding, LAUNCH, {"id": PROGRAM, "active_cycle": None, "next_cycle": 2}, cycle,
                               dispatch, attempts=attempts)


def test_the_exact_scope_capture_of_the_bound_cycle_is_the_only_completed_outcome():
    rows, held, binding, cycle, attempts = outcome_world()
    dispatch = scope_claim(rows, held)
    assert outcome(binding, cycle, dispatch, attempts) == {"state": do.COMPLETED,
                                                           "reason_code": "research_dispatch_accepted"}
    assert outcome(binding, cycle, {**dispatch, "result": "rejected"}, attempts) == {
        "state": do.REJECTED, "reason_code": "research_dispatch_rejected"}
    failed = {**cycle, "status": CYCLE_FAILED}
    assert outcome(binding, failed, dispatch, attempts) == {"state": do.REJECTED, "reason_code": "research_cycle_failed"}


def _foreign(case, dispatch, attempts, held):
    scope = dict(dispatch["scope"])
    if case == "family_kind":
        return {**dispatch, "kind": "failure_family"}, attempts
    if case == "other_intent":
        return {**dispatch, "scope": {**scope, "intent_id": "d" * 64}}, attempts
    if case == "other_identity":
        return {**dispatch, "id": attempt_scope_id("d" * 64), "investigation": attempt_scope_id("d" * 64)}, attempts
    if case == "extra_member":
        ids = sorted([*dispatch["job_ids"], "job-q1"])
        return {**dispatch, "job_ids": ids, "job_ids_total": len(ids), "job_ids_sha256": digest(ids)}, attempts
    if case == "wrong_total":
        return {**dispatch, "job_ids_total": 3}, attempts
    if case == "changed_evidence":
        return dispatch, [{**attempts[0], "evidence_sha256": "9" * 64}, *attempts[1:]]
    if case == "other_cycle":
        return {**dispatch, "cycle": cycle_id("rp-other", 1)}, attempts
    if case == "attempts_unread":
        return dispatch, None
    raise AssertionError(case)


@pytest.mark.parametrize("case", ["family_kind", "other_intent", "other_identity", "extra_member", "wrong_total",
                                  "changed_evidence", "other_cycle", "attempts_unread"])
@pytest.mark.parametrize("status", [CYCLE_DONE, CYCLE_FAILED])
def test_a_foreign_or_inexact_capture_at_the_scope_id_is_unknown_before_any_result(case, status):
    """U2B-13 (new): a foreign accepted dispatch (kind, intent, identity, members, evidence, cycle) is
    `unknown`/`research_scope_capture_mismatch`, never completed and never a failed-cycle rejection."""
    rows, held, binding, cycle, attempts = outcome_world(status=status)
    dispatch, attempts = _foreign(case, scope_claim(rows, held), attempts, held)
    assert outcome(binding, cycle, dispatch, attempts) == {"state": do.UNKNOWN,
                                                           "reason_code": "research_scope_capture_mismatch"}


def test_the_bound_cycle_and_launch_still_decide_first_and_absence_keeps_its_legacy_meaning():
    rows, held, binding, cycle, attempts = outcome_world()
    dispatch = scope_claim(rows, held)
    assert outcome(binding, {**cycle, "owner": "f" * 64}, dispatch, attempts)["reason_code"] == "research_cycle_foreign"
    empty = {**cycle, "selection": {"candidate": None}}
    assert outcome(binding, empty, None, attempts) == {"state": do.REFUSED, "reason_code": "research_cycle_empty"}


def test_a_legacy_binding_outcome_is_unchanged():
    """U2B-13 pin: a family binding never reads attempts; its outcome is the anchor rule."""
    rows, held, _, cycle, _ = outcome_world()
    binding = do.research_dispatch_binding(held, {"program_id": PROGRAM}, CAUSE, PAIR, 1)
    dispatch = {**family_capture(PAIR, investigation=CAUSE), "cycle": cycle["id"]}
    assert outcome(binding, cycle, dispatch, None) == {"state": do.COMPLETED, "reason_code": "research_dispatch_accepted"}


# ===== application: same-transaction scope read, scoped identity, scope-only receipt binding ================
class LaunchStandIn:
    """LABELLED research launch port: never spawns anything; `poll` answers a finished, cleaned-up child."""

    def __init__(self):
        self.starts = []

    def probe(self):
        return {"ok": True, "reason_code": None, "codex": None, "node": None}

    def start(self, launch, program_id, lane):
        self.starts.append(launch)
        return {"cached": False}

    def poll(self, launch):
        return {"state": "exited", "owned": False, "exit_code": 0, "cleanup_confirmed": True}


class FactsStandIn:
    """LABELLED `Continuation.research_facts` stand-in over the same store: the dispatch keyed by the asked
    investigation and an accepted run result when that dispatch is accepted. `asked` records the ids."""

    def __init__(self, store):
        self.store, self.asked = store, []

    def research_facts(self, document):
        self.asked.append(document["investigation"])
        with self.store.transaction() as tx:
            dispatch = tx.get(BUCKET_DISPATCHES, document["investigation"])
        accepted = isinstance(dispatch, dict) and dispatch.get("result") == "accepted"
        return {"dispatch": dispatch, "recovery_held": None,
                "run_result": {"result": "accepted" if accepted else "unknown"}}


class LaneStandIn:
    """LABELLED lane evidence reader: every attempt shows its bound inspection."""

    def __call__(self, lane_id):
        return self

    def read(self, job_row):
        return {"operation": {"reason_code": REASON, "owner_handoff": {"inspection": {"id": "insp-" + job_row["id"]}}},
                "markers": []}


def seeded(rows: dict) -> MemoryStore:
    store = MemoryStore()
    keys = {"research_programs": "id", BUCKET_DISPATCHES: "id", "research_dispatch_recoveries": "id",
            "research_dispatch_heads": "id", BUCKET_INVESTIGATIONS: "id", "fleet_jobs": "id",
            BUCKET_BINDINGS: "job_id", "continuation_policies": "id", "continuation_intents": "id",
            "continuation_research_receipts": "id", "research_dispatch_successors": "id"}
    with store.transaction() as tx:
        for bucket, key in keys.items():
            for row in rows.get(bucket, []):
                tx.put(bucket, row[key], row)
    return store


def owner(store: MemoryStore, **ports) -> OwnerActions:
    return OwnerActions(store, research=LaunchStandIn(), ledger=lambda: {"host": "fixture", "this_host": 0,
                                                                         "all_hosts": 0, "unreadable": 0},
                        clock=lambda: NOW, **ports)


def test_the_scoped_read_uses_the_scope_identity_and_rereads_the_lineage_in_one_transaction():
    rows, held = fixture()
    coordinator = owner(seeded(rows))
    scope, decision = coordinator._research_decide(held, [held], PROGRAM)     # a stale caller read: S1 only
    assert scope["investigation"] == attempt_scope_id(held["id"]) and scope["family_investigation"] == CAUSE
    assert scope["attempts"] == PAIR, "re-derived from the intents of the same read, not the caller's"
    assert {"continuation_policies", "continuation_intents", "continuation_research_receipts",
            "research_dispatch_successors"} <= set(scope["rows"])
    assert decision["reason"] == "research_ready_resume_then_tick"


def test_a_held_intent_that_moved_on_after_the_callers_read_is_not_decided_on_that_read():
    rows, held = fixture()
    store = seeded(rows)
    with store.transaction() as tx:
        tx.put("continuation_intents", held["id"], {**held, "state": "completed"})
    _, decision = owner(store)._research_decide(held, rows["continuation_intents"], PROGRAM)
    assert decision["reason"] == "research_scope_not_eligible" and decision["detail"]["counts"]["state"] == 1
    gone = seeded({**rows, "continuation_intents": [r for r in rows["continuation_intents"] if r["id"] != held["id"]]})
    with pytest.raises(do.OwnerActionRefused, match="research_intent_not_held"):
        owner(gone)._research_decide(held, rows["continuation_intents"], PROGRAM)


def test_discovery_binds_the_research_dispatch_to_the_scope_id_with_the_unchanged_binding_shape():
    rows, held = fixture()
    store = seeded(rows)
    coordinator = owner(store)
    policy_row = {"id": "owners-2", "policy_sha256": "4" * 64}
    [identity] = coordinator._discover_research(policy_row, {"enabled": True, "program_id": PROGRAM, "lane": "a"},
                                                held, [held])
    with store.transaction() as tx:
        action = tx.get(BUCKET_ACTIONS, identity)
    assert action["binding"] == {"intent_id": held["id"], "continuation_policy": POLICY, "family": ROOT,
                                 "program_id": PROGRAM, "investigation": attempt_scope_id(held["id"]),
                                 "attempts": PAIR, "expected_cycle": 1}


def test_a_legacy_program_read_is_the_anchor_read():
    """Inertness: a legacy program gets exactly the anchor's keys and rows, and the family identity."""
    rows, held = legacy_fixture()
    rows["continuation_intents"] = lineage(ROOT, *PAIR)
    scope, decision = owner(seeded(rows))._research_decide(held, rows["continuation_intents"], PROGRAM)
    assert set(scope) == {"attempts", "investigation", "program", "room", "rows"}
    assert set(scope["rows"]) == {"research_programs", "research_investigation_dispatches", "research_dispatch_recoveries",
                                  "research_dispatch_heads", "portfolio_investigations", "fleet_jobs",
                                  "portfolio_bindings"}
    assert scope["investigation"] == CAUSE and decision["reason"] == "research_ready_resume_then_tick"


def binding_world(*, scope_state="resolved", scope_result="accepted", scope=True, family=True):
    rows, held = fixture()
    if family:      # a historical accepted family dispatch whose capture names the pair
        rows[BUCKET_DISPATCHES].append({**family_capture([*PAIR, "job-h1"], investigation=CAUSE),
                                        "run_id": "run-family", "manifest_sha256": "5" * 64})
    if scope:
        rows[BUCKET_DISPATCHES].append(scope_claim(rows, held, state=scope_state, result=scope_result))
    store = seeded(rows)
    facts = FactsStandIn(store)
    return store, facts, held, rows["continuation_intents"], owner(store, continuation=facts, lanes=LaneStandIn())


CONTINUATION = {"id": POLICY, "policy_sha256": POLICY_SHA}


def test_a_claimed_scope_is_the_only_receipt_identity_and_never_a_historical_family_dispatch():
    store, facts, held, intents, coordinator = binding_world()
    found = coordinator._research_binding(CONTINUATION, held, intents)
    binding = found["binding"]
    assert facts.asked == [attempt_scope_id(held["id"])], "the family dispatch is never consulted"
    assert binding["schema"] == RESEARCH_RECEIPT_SCHEMA and binding["investigation"] == attempt_scope_id(held["id"])
    assert binding["dispatch"]["id"] == attempt_scope_id(held["id"]) and binding["dispatch"]["run_id"] == "run-scope"
    assert [a["job"] for a in binding["attempts"]] == PAIR and all(set(a) == {"job", "evidence_sha256", "inspection"}
                                                                   for a in binding["attempts"])


@pytest.mark.parametrize("state, result", [("claimed", None), ("running", None), ("resolved", "rejected"),
                                           ("failed", None), ("resolved", "unknown")])
def test_a_pending_or_failed_scope_never_falls_back_to_the_family(state, result):
    _, facts, held, intents, coordinator = binding_world(scope_state=state, scope_result=result)
    with pytest.raises(do.OwnerActionRefused, match="research_dispatch_pending"):
        coordinator._research_binding(CONTINUATION, held, intents)
    assert facts.asked == [attempt_scope_id(held["id"])]


def test_an_inexact_scope_capture_or_drifted_membership_is_a_named_wait():
    store, _, held, intents, coordinator = binding_world()
    scope = attempt_scope_id(held["id"])
    with store.transaction() as tx:
        row = tx.get(BUCKET_DISPATCHES, scope)
        tx.put(BUCKET_DISPATCHES, scope, {**row, "scope": {**row["scope"], "attempts_sha256": "6" * 64}})
    with pytest.raises(do.OwnerActionRefused, match="research_scope_capture_mismatch"):
        coordinator._research_binding(CONTINUATION, held, intents)
    store, _, held, intents, coordinator = binding_world()
    with store.transaction() as tx:
        tx.put("fleet_jobs", "job-f0", job("job-f0", reason="other_reason"))
    with pytest.raises(do.OwnerActionRefused, match="research_scope_membership"):
        coordinator._research_binding(CONTINUATION, held, intents)


def test_without_a_scope_claim_the_family_binding_is_unchanged():
    _, facts, held, intents, coordinator = binding_world(scope=False)
    binding = coordinator._research_binding(CONTINUATION, held, intents)["binding"]
    assert facts.asked == [CAUSE] and binding["investigation"] == CAUSE and binding["dispatch"]["run_id"] == "run-family"


def running_dispatch(store, held):
    binding = do.research_dispatch_binding(held, {"program_id": PROGRAM}, attempt_scope_id(held["id"]), PAIR, 1)
    row = do.new_action(do.RESEARCH_DISPATCH, binding, {"id": "owners-2", "policy_sha256": "4" * 64},
                        {"intent_id": held["id"], "lane": "a"}, NOW)
    row = {**do.moved(do.moved(row, do.LAUNCHING, NOW, "research_launch_intended"), do.RUNNING, NOW,
                      "research_launched"), "launch_id": LAUNCH, "launches": 1}
    with store.transaction() as tx:
        tx.put(BUCKET_ACTIONS, row["id"], row)
        tx.put(BUCKET_PROGRAMS, PROGRAM, program(state="active", cycles=1, next_cycle=2, adoptions=1))
        tx.put(BUCKET_CYCLES, cycle_id(PROGRAM, 1), {"id": cycle_id(PROGRAM, 1), "owner": LAUNCH, "status": CYCLE_DONE,
                                                    "selection": {"candidate": candidate_identity(held["id"])}})
    return row


@pytest.mark.parametrize("change, expected", [
    (None, (do.COMPLETED, "research_dispatch_accepted")),
    ("foreign_intent", (do.UNKNOWN, "research_scope_capture_mismatch")),
    ("lineage_changed", (do.UNKNOWN, "research_scope_capture_mismatch")),
])
def test_the_observed_scoped_outcome_is_checked_against_the_lineage_read_with_it(change, expected):
    """U2B-13 through the coordinator: the attempt pairs come from the intent rows of the outcome read."""
    rows, held = fixture()
    rows[BUCKET_DISPATCHES].append(scope_claim(rows, held))
    store = seeded(rows)
    action = running_dispatch(store, held)
    with store.transaction() as tx:
        scope = attempt_scope_id(held["id"])
        if change == "foreign_intent":
            row = tx.get(BUCKET_DISPATCHES, scope)
            tx.put(BUCKET_DISPATCHES, scope, {**row, "scope": {**row["scope"], "intent_id": "d" * 64}})
        elif change == "lineage_changed":
            late = intent(0, "correction", "admitted", "job-q1")        # an earlier failed attempt now counts
            tx.put("continuation_intents", late["id"], late)
    effect = owner(store)._observe_dispatch(action)
    assert (effect["state"], effect["reason_code"]) == expected
