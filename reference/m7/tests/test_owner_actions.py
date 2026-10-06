"""INV-OWNER-ACTIONS-001, aibox-migration-001 SPEC s14 G1: server-owned scoped research acceptance.

Real MemoryStores, the real Fleet, finite Operation, Portfolio, ResearchProgram runner and the real
continuation owner (`Continuation.accept_research` and its tick) from `test_continuation_research`. The
independent assessor is a LABELLED fixture (`FakeAssessor`): it plays the guarded `decide_one` of the
assessor by writing the decision row's terminal status and an execution-receipt artifact, exactly the
shape the executor commits; no model, provider, network or production store is touched, and an injected
verdict is never evidence of a real assessment. Crashes are LABELLED injected faults.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest
from test_continuation import World, only
from test_continuation_research import (
    held,
    mixed_family,
    receipts,
    research_rows,
    two_strikes,
)

from codex_harness.application.owner_actions import BUCKET_ACTIONS, OwnerActions
from codex_harness.bootstrap import organization
from codex_harness.domain import continuation as dc
from codex_harness.domain import owner_actions as do
from codex_harness.domain.model import canonical

PIN = {"revision": "e" * 40, "path": "ops/owner-actions.json", "sha256": "d" * 64, "lane": "a"}
REPORT = "LABELLED fixture accepted research report text for the assessor (not a real report)\n"


def owner_policy(**overrides):
    return {"schema": do.POLICY_SCHEMA, "id": "owners-1", "enabled": True, "continuation_policy": "policy-1",
            "assessment": {"model_label": "labelled-fixture-assessor"},
            "delivery": {"target_id": "fleet-host", "repository": "github:zeus-owner/zeus-harness",
                         "required_checks": ["ci / required"], "canary_check_id": "startup_identity",
                         "ci_timeout_seconds": 300, "consumption_timeout_seconds": 120},
            "canary": None, **overrides}


class FakeAssessor:
    """LABELLED fixture of the assessment port. `verdict` is what the guarded decision commits when a
    launch runs: True / False (accepted / rejected), "blocked" (a blocked decision), "retry" (a failed
    attempt left for the executor's retry budget) or None (the launch keeps running). `spawn_fails`
    raises before any guardian exists; `lost` spawns and decides but loses the start response."""

    def __init__(self, world, verdict=True, *, spawn_fails=0, lost=False):
        self.world, self.verdict, self.spawn_fails, self.lost = world, verdict, spawn_fails, lost
        self.starts, self.launches, self.contexts, self.documents = [], {}, 0, []

    def context(self, binding, found):
        self.contexts += 1
        return {"report": REPORT, "report_digest": hashlib.sha256(REPORT.encode()).hexdigest(),
                "evidence_refs": [], "members": found["members"]}

    def document(self, document):
        self.documents.append(document)
        return self.world.artifacts.put(canonical(document), "owner-assessment")["ref"]

    def start(self, launch, decision_id, correlation_id):
        if self.spawn_fails:
            self.spawn_fails -= 1
            raise OSError("guardian could not be spawned (labelled injected fault)")
        self.starts.append((launch, decision_id))
        self.launches[launch] = "running"
        if self.verdict is not None:
            self.decide(decision_id)
            self.launches[launch] = "exited"
        if self.lost:
            self.lost = False
            raise TimeoutError("start response lost after the guardian decided (labelled injected fault)")
        return {"pid": 4242}

    def decide(self, decision_id, verdict=None):
        verdict = self.verdict if verdict is None else verdict
        ref = self.world.artifacts.put("LABELLED fixture assessor execution receipt " + decision_id,
                                       "owner-assessment-execution")["ref"]
        with self.world.control.transaction() as tx:
            row = tx.get("decisions_pending", decision_id)
            if verdict == "retry":
                row.update(status="retry", attempt=1, error="labelled injected provider failure")
            elif verdict == "blocked":
                row.update(status="blocked", attempt=1, result={"accepted": False, "blocked": True,
                                                                "execution_ref": ref, "reason": "blocked"})
            else:
                row.update(status="succeeded", attempt=1, result={"accepted": verdict, "execution_ref": ref,
                                                                  "reason": "labelled fixture verdict"})
            tx.put("decisions_pending", decision_id, row)

    def poll(self, launch):
        # The launch directory's observation shapes of `continuation_process.observe`; `exit_code` is the
        # assess child's own exit (0 only when it owned the claim and settled every call reservation).
        state = self.launches.get(launch)
        if state is None:
            return {"state": "absent", "owned": False, "proof": {"kind": "fenced"}}
        if state == "running":
            return {"state": "running", "owned": True}
        if state == "unknown":
            return {"state": "unknown", "owned": False, "exit_code": None, "cleanup_confirmed": False}
        if state == "timeout":
            return {"state": "timeout", "owned": False, "exit_code": None, "cleanup_confirmed": True}
        return {"state": "exited", "owned": False, "exit_code": 1 if state == "unsettled" else 0,
                "cleanup_confirmed": True}


def owners_for(world, assessor, **ports):
    owner = OwnerActions(world.control, continuation=world.controller, org=organization(), lanes=world.lanes,
                         assessments=assessor, **ports)
    return owner


def actions(world):
    with world.control.transaction() as tx:
        return {row["id"]: row for row in tx.scan(BUCKET_ACTIONS)}


def decisions(world):
    with world.control.transaction() as tx:
        return [row for row in tx.scan("decisions_pending") if row.get("phase") == do.OWNER_PHASE]


def settle(owner, ticks=6):
    results = []
    for _ in range(ticks):
        results.append(owner.tick("owners-1"))
    return results


def registered(world, assessor=None, **policy):
    assessor = assessor or FakeAssessor(world)
    owner = owners_for(world, assessor)
    owner.register(owner_policy(**policy), PIN)
    return owner, assessor


# ---- accepted: one assessment, one receipt through the existing API, the hold released once ----------------
def test_accepted_assessment_assembles_the_exact_receipt_and_the_existing_tick_releases_the_hold_once(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    before = research_rows(world, investigation)
    owner, assessor = registered(world)
    settle(owner)
    [action] = actions(world).values()
    assert action["kind"] == do.RESEARCH_RECEIPT and action["state"] == do.COMPLETED
    assert action["binding"]["intent_id"] == research["id"] and action["binding"]["investigation"] == investigation
    assert [a["job"] for a in action["binding"]["attempts"]] == sorted([root, successor])
    # Exactly one independent assessment row and one launch: Claude's report never judged itself.
    [decision] = decisions(world)
    assert decision["actor"] == do.ASSESSOR == "conductor" and decision["input"]["report"] == REPORT
    assert decision["input"]["binding_sha256"] == action["binding_sha256"] and len(assessor.starts) == 1
    # The receipt went through `accept_research`: stored once, bound to the assessment artifact.
    stored = receipts(world)[research["id"]]
    assert stored["receipt"] == action["receipt"] and stored["receipt_sha256"] == action["receipt_sha256"]
    assert action["assessment_ref"] in stored["receipt"]["evidence_refs"]
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED, "acceptance moves nothing"
    world.tick()
    done = world.intents()[research["id"]]
    assert done["state"] == dc.COMPLETED and done["reason_code"] == "research_receipt_accepted"
    repair = only(world.intents(), origin_job=successor, route=dc.EVIDENCE_REPAIR)
    assert repair["state"] == dc.ADMITTED
    assert research_rows(world, investigation) == before, "research owners' rows are never rewritten"
    # Duplicate wakeups (this coordinator, a second one, a restart): nothing more is called or written.
    idle = deepcopy(world.control.data)
    settle(owner, 3)
    settle(owners_for(world, assessor), 3)
    assert world.control.data == idle and len(assessor.starts) == 1 and assessor.contexts == 1


@pytest.mark.parametrize("verdict, state, code", [
    (False, do.REJECTED, "assessment_rejected"), ("blocked", do.UNKNOWN, "assessment_blocked")])
def test_a_rejected_or_blocked_assessment_is_a_named_terminal_state_and_the_family_stays_held(tmp_path, verdict,
                                                                                              state, code):
    world = World(tmp_path)
    _, _, research, _, _ = held(world, tmp_path)
    owner, assessor = registered(world, FakeAssessor(world, verdict=verdict))
    settle(owner)
    [action] = actions(world).values()
    assert action["state"] == state and action["reason_code"] == code
    assert receipts(world) == {} and len(assessor.starts) == 1
    world.tick()
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED
    # No endless retries: further wakeups neither assess again nor create another action.
    snapshot = deepcopy(world.control.data)
    settle(owner, 4)
    assert world.control.data == snapshot and len(assessor.starts) == 1


def test_an_unfinished_assessment_is_relaunched_at_most_once_and_then_unknown(tmp_path):
    world = World(tmp_path)
    held(world, tmp_path)
    assessor = FakeAssessor(world, verdict="retry")
    owner, _ = registered(world, assessor)
    settle(owner, 3)
    [action] = actions(world).values()
    # A launch that ended with the decision left for retry is an unfinished assessment: unknown, no relaunch.
    assert action["state"] == do.UNKNOWN and action["reason_code"] == "assessment_unfinished"
    assert len(assessor.starts) == 1 and receipts(world) == {}


def test_a_guardian_that_never_spawned_is_relaunched_once_under_a_new_launch_identity(tmp_path):
    world = World(tmp_path)
    _, _, research, _, _ = held(world, tmp_path)
    assessor = FakeAssessor(world, spawn_fails=1)
    owner, _ = registered(world, assessor)
    first = owner.tick("owners-1")
    [action] = actions(world).values()
    # The intent and the decision row were committed before the spawn failed (crash BEFORE the model).
    assert action["state"] == do.ASSESSING and len(decisions(world)) == 1
    assert list(first["waits"].values()) == ["OSError"]
    settle(owner)
    [action] = actions(world).values()
    assert action["state"] == do.COMPLETED and action["launches"] == 2 and len(assessor.starts) == 1
    assert len(decisions(world)) == 1 and research["id"] in receipts(world)


def test_a_lost_start_response_after_the_model_decided_is_recognized_never_repeated(tmp_path):
    world = World(tmp_path)
    _, _, research, _, _ = held(world, tmp_path)
    assessor = FakeAssessor(world, lost=True)
    owner, _ = registered(world, assessor)
    settle(owner)
    [action] = actions(world).values()
    assert action["state"] == do.COMPLETED and action["launches"] == 1 and len(assessor.starts) == 1
    assert research["id"] in receipts(world)


def test_a_restarted_coordinator_resumes_after_the_model_and_after_the_receipt_without_a_second_call(tmp_path):
    world = World(tmp_path)
    _, _, research, _, _ = held(world, tmp_path)
    assessor = FakeAssessor(world, verdict=None)       # the guardian is still running at the "crash"
    owner, _ = registered(world, assessor)
    owner.tick("owners-1")
    [decision] = decisions(world)
    assessor.decide(decision["id"], True)              # the model finished while no coordinator watched
    assessor.launches = {k: "exited" for k in assessor.launches}

    class CrashOnAccept:
        """LABELLED injected fault: the process dies right after the receipt was persisted."""

        def __init__(self, inner):
            self.inner, self.calls = inner, 0

        def policy(self, policy_id):
            return self.inner.policy(policy_id)

        def research_facts(self, document):
            return self.inner.research_facts(document)

        def accept_research(self, document):
            self.calls += 1
            raise RuntimeError("coordinator crashed before the existing API answered (injected)")

    crashing = CrashOnAccept(world.controller)
    restarted = OwnerActions(world.control, continuation=crashing, org=organization(), lanes=world.lanes,
                             assessments=assessor)
    settle(restarted, 3)
    [action] = actions(world).values()
    assert action["state"] == do.INVOKING and crashing.calls >= 1 and receipts(world) == {}
    persisted = action["receipt"]
    settle(owners_for(world, assessor), 2)
    [action] = actions(world).values()
    assert action["state"] == do.COMPLETED and receipts(world)[research["id"]]["receipt"] == persisted
    assert len(assessor.starts) == 1 and len(decisions(world)) == 1


def test_an_executed_assessment_bound_to_the_exact_binding_is_reused_without_a_new_call(tmp_path):
    world = World(tmp_path)
    _, _, research, _, _ = held(world, tmp_path)
    first = FakeAssessor(world)
    owner, _ = registered(world, first)
    owner.tick("owners-1")      # schedules and (fixture) executes the one assessment
    [action] = actions(world).values()
    # LABELLED: a fresh coordinator whose own row is gone (e.g. a lost bucket write) finds the executed
    # decision bound to exactly this binding digest and reuses it.
    del world.control.data[BUCKET_ACTIONS, action["id"]]   # LABELLED injected loss of the action row
    second = FakeAssessor(world)
    second.launches = first.launches        # the same launch directories (the executed launch's proof)
    settle(owners_for(world, second))
    [again] = actions(world).values()
    assert again["state"] == do.COMPLETED and again.get("reused") is True and second.starts == []
    assert research["id"] in receipts(world)


def test_reuse_accepts_only_an_executed_decision_of_the_exact_binding():
    row = {"id": "a" * 64, "kind": do.RESEARCH_RECEIPT, "binding_sha256": "b" * 64}
    base = {"id": "d1", "phase": do.OWNER_PHASE, "actor": do.ASSESSOR, "status": "succeeded",
            "input": {"owner_action": row["id"], "binding_sha256": row["binding_sha256"]},
            "result": {"accepted": True, "execution_ref": "sha256:" + "c" * 64}}
    assert do.reusable_assessment([base], row) == base
    for change in ({"status": "running"}, {"actor": "lead:improvement"}, {"phase": "review_lead"},
                   {"input": {"owner_action": row["id"], "binding_sha256": "f" * 64}},
                   {"result": {"accepted": True}}, {"status": "blocked"}):
        assert do.reusable_assessment([{**base, **change}], row) is None, change
    assert do.assessment_verdict({**base, "result": {"accepted": False, "execution_ref": "sha256:" + "c" * 64}},
                                 row)["verdict"] == do.VERDICT_REJECTED


# ---- changed evidence: the old action is refused, a new exact identity is assessed anew -------------------
def test_a_changed_attempt_refuses_the_stale_action_and_only_a_new_exact_binding_is_assessed(tmp_path):
    world = World(tmp_path)
    root, successor, research, _, _ = held(world, tmp_path)
    assessor = FakeAssessor(world, verdict=None)
    owner, _ = registered(world, assessor)
    owner.tick("owners-1")
    [stale] = actions(world).values()
    # LABELLED injected change: the lane evidence of one covered attempt changes while assessing.
    with world.lane.store.transaction() as tx:
        row = tx.get("operations", successor)
        row["owner_handoff"] = {**row["owner_handoff"],
                                "inspection": {**row["owner_handoff"]["inspection"], "id": "insp-replaced"}}
        tx.put("operations", successor, row)
    [decision] = decisions(world)
    assessor.decide(decision["id"], True)
    assessor.launches = {k: "exited" for k in assessor.launches}
    settle(owner, 3)
    rows = actions(world)
    assert rows[stale["id"]]["state"] == do.REFUSED
    assert rows[stale["id"]]["reason_code"] in {"research_binding_changed", "research_attempt_changed"}
    assert receipts(world) == {}, "an assessment of other evidence never becomes this receipt"
    world.tick()
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED


def test_no_accepted_research_yet_is_a_named_wait_that_writes_nothing(tmp_path):
    world = World(tmp_path)
    world.register()
    two_strikes(world, "op-x", "docs/a.md")
    owner, assessor = registered(world)
    before = deepcopy(world.control.data)
    result = owner.tick("owners-1")
    assert result["outcome"] == "idle" and "research_dispatch_pending" in result["waits"].values()
    assert world.control.data == before and assessor.starts == [] and assessor.contexts == 0


def test_an_absent_or_disabled_policy_or_a_foreign_target_does_nothing(tmp_path):
    world = World(tmp_path)
    held(world, tmp_path)
    assessor = FakeAssessor(world)
    owner = owners_for(world, assessor)
    assert owner.tick("owners-1")["outcome"] == "unregistered"
    owner.register(owner_policy(enabled=False), PIN)
    before = deepcopy(world.control.data)
    assert owner.tick("owners-1")["outcome"] == "disabled" and world.control.data == before
    other = owners_for(world, assessor)
    other.register(owner_policy(id="owners-2", delivery={**owner_policy()["delivery"], "target_id": "elsewhere"}),
                   PIN)
    refused = other.tick("owners-2")
    assert refused["outcome"] == "refused" and refused["reason_code"] == "delivery_target_mismatch"
    assert other.tick("owners-2", pin_sha256="0" * 64)["reason_code"] == "policy_changed"
    assert assessor.starts == []


# ---- the actual mixed-cause family: schema 2 assembled from persisted lineage and promotion rows -----------
def test_the_mixed_cause_family_is_assembled_as_a_schema2_receipt_and_released_once(tmp_path):
    world = World(tmp_path)
    family = mixed_family(world, tmp_path)
    research = family["research"]
    owner, assessor = registered(world)
    settle(owner)
    rows = [row for row in actions(world).values() if row["subject"]["intent_id"] == research["id"]]
    [action] = rows
    assert action["state"] == do.COMPLETED, (action["state"], action["reason_code"])
    receipt = receipts(world)[research["id"]]
    assert receipt["coverage"] == "mixed_family" and receipt["receipt"]["captured"] == [family["child"]]
    assert receipt["receipt"]["lineage"] == [{"intent_id": family["edge"]["id"], "job": family["child"],
                                              "parent_job": family["parent"]}]
    assert receipt["receipt"]["acceptance"] == family["acceptance"]
    assert receipt["receipt"]["attestation_ref"] == action["assessment_ref"]
    world.tick()
    assert world.intents()[research["id"]]["state"] == dc.COMPLETED
    # One launch for this family; the fixture's unrelated second held family (op-z) gets its own action.
    assert [start for start in assessor.starts if start[1] == action["decision_id"]] == [
        (do.assessment_launch_id(action["id"], 1), action["decision_id"])]
    others = [row for row in actions(world).values() if row["id"] != action["id"]]
    assert all(row["subject"]["intent_id"] != research["id"] for row in others)


# ---- R1: a decided assessment is promoted only on its bound launch's cleanup and settlement proof ----------
def test_a_success_persisted_before_the_launch_exits_waits_and_completes_only_after_the_proof(tmp_path):
    world = World(tmp_path)
    _, _, research, _, _ = held(world, tmp_path)
    assessor = FakeAssessor(world, verdict=None)       # the guardian (and its call ledger) is still running
    owner, _ = registered(world, assessor)
    owner.tick("owners-1")
    [decision] = decisions(world)
    assessor.decide(decision["id"], True)              # LABELLED: the verdict row commits before the exit
    settle(owner, 3)
    [action] = actions(world).values()
    assert action["state"] == do.ASSESSING and action["reason_code"] == "assessment_awaiting_cleanup"
    assert action["decided"]["verdict"] == do.VERDICT_ACCEPTED and receipts(world) == {}
    waiting = deepcopy(world.control.data)
    settle(owner, 2)
    assert world.control.data == waiting, "a still-running launch writes nothing more"
    assessor.launches = {k: "exited" for k in assessor.launches}
    settle(owner)
    [action] = actions(world).values()
    assert action["state"] == do.COMPLETED and research["id"] in receipts(world)
    assert len(assessor.starts) == 1 and len(decisions(world)) == 1


@pytest.mark.parametrize("launch, code", [
    ("unknown", "assessment_launch_unknown"), ("unsettled", "assessment_settlement_unresolved"),
    ("timeout", "assessment_launch_timeout")])
@pytest.mark.parametrize("verdict", [True, False])
def test_an_unproven_cleanup_or_settlement_after_a_verdict_is_a_named_unknown_never_a_receipt(tmp_path, launch,
                                                                                            code, verdict):
    world = World(tmp_path)
    _, _, research, _, _ = held(world, tmp_path)
    assessor = FakeAssessor(world, verdict=None)
    owner, _ = registered(world, assessor)
    owner.tick("owners-1")
    [decision] = decisions(world)
    assessor.decide(decision["id"], verdict)
    assessor.launches = {k: launch for k in assessor.launches}   # LABELLED injected launch outcome
    settle(owner, 4)
    [action] = actions(world).values()
    assert action["state"] == do.UNKNOWN and action["reason_code"] == code
    # The executed verdict is retained as evidence; it is neither promoted nor asked for again.
    assert action["decided"]["verdict"] == (do.VERDICT_ACCEPTED if verdict else do.VERDICT_REJECTED)
    assert action["decided"]["decision_id"] == decision["id"] and "receipt" not in action
    assert receipts(world) == {} and len(assessor.starts) == 1
    world.tick()
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED
    snapshot = deepcopy(world.control.data)
    settle(owner, 3)
    assert world.control.data == snapshot and len(assessor.starts) == 1


def test_the_review_probe_accepted_decision_with_an_unknown_guardian_stores_no_receipt(tmp_path):
    """REVIEW-pr202 R1 probe: succeeded bound decision, poll unknown with cleanup_confirmed false."""
    world = World(tmp_path)
    _, _, research, _, _ = held(world, tmp_path)
    assessor = FakeAssessor(world, verdict=True)
    assessor.poll = lambda _: {"state": "unknown", "cleanup_confirmed": False}
    owner, _ = registered(world, assessor)
    settle(owner, 5)
    [action] = actions(world).values()
    assert action["state"] == do.UNKNOWN and action["reason_code"] == "assessment_launch_unknown"
    assert research["id"] not in receipts(world)


@pytest.mark.parametrize("launch, state, code", [
    ("running", do.ASSESSING, "assessment_reused"), ("unknown", do.UNKNOWN, "assessment_launch_unknown"),
    ("unsettled", do.UNKNOWN, "assessment_settlement_unresolved"), (None, do.UNKNOWN, "assessment_execution_unbound")])
def test_a_reused_decision_after_a_restart_passes_the_same_launch_gate_without_a_new_call(tmp_path, launch, state,
                                                                                          code):
    world = World(tmp_path)
    _, _, research, _, _ = held(world, tmp_path)
    first = FakeAssessor(world)
    owner, _ = registered(world, first)
    owner.tick("owners-1")
    [action] = actions(world).values()
    del world.control.data[BUCKET_ACTIONS, action["id"]]   # LABELLED injected loss of the action row
    second = FakeAssessor(world)
    # LABELLED launch directory state seen by the restarted coordinator; None = no launch ever entered.
    second.launches = {} if launch is None else {k: launch for k in first.launches}
    settle(owners_for(world, second), 3)
    [again] = actions(world).values()
    assert (again["state"], again["reason_code"]) == (state, code) and again["reused"] is True
    assert again["decided"]["verdict"] == do.VERDICT_ACCEPTED and research["id"] not in receipts(world)
    assert second.starts == [] and len(decisions(world)) == 1
    if launch == "running":
        second.launches = {k: "exited" for k in second.launches}
        settle(owners_for(world, second))
        [again] = actions(world).values()
        assert again["state"] == do.COMPLETED and research["id"] in receipts(world) and second.starts == []


def test_a_reused_decision_without_this_actions_launch_identity_is_unbound(tmp_path):
    world = World(tmp_path)
    held(world, tmp_path)
    first = FakeAssessor(world)
    owner, _ = registered(world, first)
    owner.tick("owners-1")
    [action] = actions(world).values()
    [decision] = decisions(world)
    # LABELLED: the same executed row under a foreign id (e.g. run by hand), and the action row lost.
    world.control.data["decisions_pending", "hand-run"] = {**decision, "id": "hand-run"}
    del world.control.data["decisions_pending", decision["id"]]
    del world.control.data[BUCKET_ACTIONS, action["id"]]
    second = FakeAssessor(world)
    second.launches = dict(first.launches)
    settle(owners_for(world, second), 2)
    [again] = actions(world).values()
    assert again["state"] == do.UNKNOWN and again["reason_code"] == "assessment_execution_unbound"
    assert second.starts == []
