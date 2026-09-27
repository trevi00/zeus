"""The typed owner canary recovery (INV-OWNER-ACTIONS-001 x INV-HOST-DELIVERY-FIRST-ACTIVATION-001).

What is real: the `OwnerActions` coordinator (`recover_canary`, `_advance_canary`, `status`), the
domain policy, the organization and the stores (two SEPARATE in-memory stores, and two isolated
PostgreSQL schemas when `HARNESS_INTEGRATION=1`; without it that parameter SKIPS and is not evidence).

What is a LABELLED FIXTURE: the control rows (policy, completed plan action, the halted canary action,
the Fleet job and the paused admission row) are written in the exact shapes the real owners write them;
the lane rows (the delivery intent after the lane `first_activation_consumption_retry`, the target and the
release) are the shapes `HostDelivery.resume_consumption_retry` records; the target-file port
(`Files`) and the lane-run reader (`LaneRun`) stand in for the process target and the canary lane.
Nothing here dispatches a Fleet job, runs a worker or touches a production host. The real
two-controller end-to-end (HostDelivery + Fleet + process target) is NOT in this module.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest
from test_host_delivery import binds_a_runtime
from test_owner_actions_migration import (
    second_pgstore,  # noqa: F401  (the SECOND isolated PG schema)
)

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.owner_actions import BUCKET_ACTIONS, BUCKET_POLICIES, OwnerActions
from codex_harness.bootstrap import organization
from codex_harness.domain import owner_actions as do
from codex_harness.domain.host_delivery import (
    AWAITING_CONSUMPTION,
    RECOVERY_CONSUMPTION_RETRY,
    RECOVERY_FIRST_ACTIVATION,
)
from codex_harness.domain.model import digest

TARGET = "aibox-canary"
PLAN_ID = "plan-1"
PLAN_SHA = "1" * 64
DESCRIPTOR = "2" * 64
INSTANCE = "inst-1"
RELEASE = "release-1"
LANE_RETRY = "sha256:" + "e" * 64
T0 = datetime(2026, 9, 27, 4, 0, tzinfo=timezone.utc)
CONTROL_BUCKETS = (BUCKET_ACTIONS, BUCKET_POLICIES, "fleet_jobs", "fleet_control")
LANE_BUCKETS = ("host_delivery_intents", "host_delivery_targets", "releases")


class Clock:
    """LABELLED fixed clock: ISO strings, advanced only by the test."""

    def __init__(self, at=T0):
        self.at = at

    def __call__(self):
        return self.at.isoformat()


class Files:
    """LABELLED target-file port: the candidate's startup receipt and the plan's owner canary receipt."""

    def __init__(self, instance=INSTANCE):
        self.startup_receipt = {"instance_id": instance, "descriptor_sha256": DESCRIPTOR}
        self.receipts: dict = {}

    def startup(self, target):
        return self.startup_receipt

    def receipt(self, target, plan_id):
        return self.receipts.get(plan_id)

    def write_receipt(self, target, plan_id, document):
        self.receipts[plan_id] = document


class LaneRun:
    """LABELLED canary lane-run reader: the finished operation and its independent lead review."""

    def read(self, job):
        return {"operation": {"status": "accepted"}, "markers": [],
                "lead": {"id": "decision-1", "phase": "review_lead", "status": "succeeded",
                         "result": {"accepted": True, "execution_ref": "sha256:" + "c" * 64}}}


class Fleet:
    """LABELLED Fleet: records admissions; the recovery must never call it."""

    def __init__(self):
        self.calls = []

    def enqueue(self, lane, manifest, goal, dependencies):
        self.calls.append(manifest["id"])
        return {"job": {"id": manifest["id"]}, "cached": True}


class Delivery:
    """The lane `deliveries(lane)` port: only its store is read."""

    def __init__(self, store):
        self.store = store


def world(control, lane, *, author="worker:improvement-1"):
    """One halted canary: REQUESTED -> UNKNOWN `canary_delivery_moved`, its job queued under a paused
    Fleet, and the lane after its consumption retry of the SAME instance (LABELLED rows)."""
    clock = Clock()
    binding = {"plan_id": PLAN_ID, "plan_sha256": PLAN_SHA, "target_id": TARGET, "descriptor_sha256": DESCRIPTOR,
               "instance_id": INSTANCE}
    policy = {"enabled": True, "canary": {"lane": "a", "manifest": {"id": "template"}, "goal": {}}}
    policy_row = {"id": "owners-1", "policy": policy, "policy_sha256": "3" * 64, "pin": {"sha256": "4" * 64},
                  "registered_at": clock()}
    identity = do.action_id(do.DELIVERY_CANARY, binding)
    job_id = do.canary_job_id(identity)
    history = [{"state": do.INTENDED, "at": "2026-09-27T03:00:00+00:00", "reason_code": None},
               {"state": do.REQUESTED, "at": "2026-09-27T03:01:00+00:00", "reason_code": "canary_requested"},
               {"state": do.UNKNOWN, "at": "2026-09-27T03:20:00+00:00", "reason_code": "canary_delivery_moved"}]
    action = {"id": identity, "kind": do.DELIVERY_CANARY, "state": do.UNKNOWN, "binding": binding,
              "binding_sha256": digest(binding), "policy_id": "owners-1", "policy_sha256": "3" * 64,
              "subject": {"intent_id": "s" * 64, "lane": "a"}, "reason_code": "canary_delivery_moved",
              "created_at": "2026-09-27T03:00:00+00:00", "updated_at": "2026-09-27T03:20:00+00:00", "version": 3,
              "history": history, "job_id": job_id}
    plan_action = {"id": "p" * 64, "kind": do.DELIVERY_PLAN, "state": do.COMPLETED, "plan_id": PLAN_ID,
                   "plan_sha256": PLAN_SHA, "plan": {"plan_id": PLAN_ID, "target_id": TARGET, "release_id": RELEASE},
                   "subject": {"intent_id": "s" * 64, "lane": "a"}, "policy_id": "owners-1",
                   "created_at": "2026-09-27T02:00:00+00:00", "version": 4, "history": []}
    job = {"id": job_id, "operation_id": job_id, "lane": "a", "team": "improvement", "repository": "r",
           "status": "queued", "reason_code": "paused", "manifest": {"id": job_id}, "manifest_sha256": "5" * 64,
           "goal": {}, "dependencies": [], "owner_token": None, "exit_code": None,
           "calls": {"reserved": None, "settled": None}, "receipt": None, "error_type": None,
           "created_at": "2026-09-27T03:01:00+00:00", "updated_at": "2026-09-27T03:01:00+00:00",
           "dispatched_at": None, "finished_at": None}
    with control.transaction() as tx:
        tx.put(BUCKET_POLICIES, policy_row["id"], policy_row)
        tx.put(BUCKET_ACTIONS, plan_action["id"], plan_action)
        tx.put(BUCKET_ACTIONS, identity, action)
        tx.put("fleet_jobs", job_id, job)
        tx.put("fleet_control", "admission", {"paused": True, "updated_at": "2026-09-27T03:00:00+00:00"})
    intent = {"plan_id": PLAN_ID, "plan_sha256": PLAN_SHA, "target_id": TARGET, "stage": AWAITING_CONSUMPTION,
              "previous_stage": "blocked", "descriptor_sha256": DESCRIPTOR,
              "stage_deadline": (T0 + timedelta(seconds=3600)).isoformat(),
              "recoveries": [{"kind": RECOVERY_FIRST_ACTIVATION, "evidence_ref": "sha256:" + "f" * 64},
                             {"kind": RECOVERY_CONSUMPTION_RETRY, "evidence_ref": LANE_RETRY,
                              "observed": {"observed_instance_id": INSTANCE, "descriptor_sha256": DESCRIPTOR}}]}
    with lane.transaction() as tx:
        tx.put("host_delivery_intents", PLAN_ID, intent)
        tx.put("host_delivery_targets", TARGET, {"id": TARGET})
        tx.put("releases", RELEASE, {"id": RELEASE, "candidate": {"author": author}})
    files, fleet = Files(), Fleet()
    owner = OwnerActions(control, org=organization(), lanes=lambda lane_id: LaneRun(), fleet=fleet,
                         deliveries=lambda lane_id: Delivery(lane), targets=files, clock=clock)
    return {"owner": owner, "control": control, "lane": lane, "files": files, "fleet": fleet, "clock": clock,
            "action": action, "job": job, "policy_row": policy_row}


def document(w, **overrides):
    action = w["action"]
    body = {"schema": do.CANARY_RECOVERY_SCHEMA, "kind": do.CANARY_RECOVERY_KIND, "action_id": action["id"],
            "action_version": action["version"], "binding_sha256": action["binding_sha256"],
            "binding": dict(action["binding"]), "policy_id": action["policy_id"],
            "policy_sha256": action["policy_sha256"], "job_id": action["job_id"],
            "halt": {"state": action["state"], "reason_code": action["reason_code"],
                     "updated_at": action["updated_at"]},
            "lane_retry_evidence": LANE_RETRY, "margin_seconds": 600, "approved_by": "conductor"}
    body.update(overrides)
    return body, "sha256:" + digest(body)


def snapshot(w):
    out = {}
    for name, store, buckets in (("control", w["control"], CONTROL_BUCKETS), ("lane", w["lane"], LANE_BUCKETS)):
        with store.transaction() as tx:
            out[name] = {bucket: sorted((copy.deepcopy(r) for r in tx.scan(bucket)), key=repr) for bucket in buckets}
    out["receipts"] = copy.deepcopy(w["files"].receipts)
    out["fleet"] = list(w["fleet"].calls)
    return out


def row(w, bucket=BUCKET_ACTIONS, key=None, store="control"):
    with w[store].transaction() as tx:
        return tx.get(bucket, key or w["action"]["id"])


def put(w, bucket, key, value, store="control"):
    with w[store].transaction() as tx:
        tx.put(bucket, key, value)


def refused(w, code, body=None, evidence=None):
    if body is None:
        body, evidence = document(w)
    before = snapshot(w)
    with pytest.raises(do.OwnerActionRefused) as caught:
        w["owner"].recover_canary(body, evidence or "sha256:" + digest(body))
    assert caught.value.reason_code == code, caught.value.reason_code
    assert snapshot(w) == before, "a refusal writes nothing in either store"


@pytest.fixture(params=["memory", "postgres"])
def stores(request):
    if request.param == "memory":
        return MemoryStore(), MemoryStore()
    # The lane store is a SECOND isolated schema: two stores, never one transaction across them.
    return request.getfixturevalue("isolated_pgstore"), request.getfixturevalue("second_pgstore")


@pytest.fixture
def w(stores):
    return world(*stores)


# ----- domain ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [
    ("schema", "urn:zeus:other:1"), ("kind", "delivery_canary"), ("action_version", 0), ("action_version", "3"),
    ("binding", {"plan_id": "p"}), ("halt", {"state": "unknown", "reason_code": "canary_job_unknown", "updated_at": "t"}),
    ("lane_retry_evidence", "sha256:xyz"), ("margin_seconds", 599), ("approved_by", "Robert'); drop"),
    ("job_id", "")])
def test_the_document_grammar_is_exact(field, value):
    body, _ = document(world(MemoryStore(), MemoryStore()))
    assert do.validate_canary_recovery(body)["kind"] == do.CANARY_RECOVERY_KIND
    with pytest.raises(do.OwnerActionRefused) as caught:
        do.validate_canary_recovery({**body, field: value})
    assert caught.value.reason_code == "canary_recovery_invalid"
    with pytest.raises(do.OwnerActionRefused):
        do.validate_canary_recovery({**body, "extra": 1})


def test_the_global_transition_table_is_not_weakened():
    with pytest.raises(do.OwnerActionRefused):
        do.transition(do.DELIVERY_CANARY, do.UNKNOWN, do.REQUESTED)
    assert do.UNKNOWN in do.TERMINAL


# ----- the recovery ----------------------------------------------------------------------------------------
def test_the_recovery_returns_the_same_action_to_requested_with_the_same_queued_job_and_then_a_receipt(w):
    before = snapshot(w)
    body, evidence = document(w)
    receipt = w["owner"].recover_canary(body, evidence)
    assert receipt["cached"] is False and receipt["state"] == do.REQUESTED
    assert receipt["reason_code"] == "canary_recovered" and receipt["job_id"] == w["action"]["job_id"]
    after = row(w)
    assert after["version"] == 4 and after["history"][-1]["reason_code"] == "canary_recovered"
    [recovery] = after["recoveries"]
    assert recovery["kind"] == do.CANARY_RECOVERY_KIND and recovery["evidence_ref"] == evidence
    assert recovery["halted"] == {"state": do.UNKNOWN, "reason_code": "canary_delivery_moved",
                                  "updated_at": w["action"]["updated_at"], "version": 3}
    assert recovery["job_snapshot"]["status"] == "queued" and recovery["job_snapshot"]["calls"] == {
        "reserved": None, "settled": None}
    assert recovery["lane"] == {"retry_evidence": LANE_RETRY, "stage": AWAITING_CONSUMPTION,
                                "stage_deadline": (T0 + timedelta(seconds=3600)).isoformat(),
                                "instance_id": INSTANCE, "descriptor_sha256": DESCRIPTOR}
    # Never re-enqueued, the job and the paused Fleet untouched, the lane only read.
    after_snapshot = snapshot(w)
    assert w["fleet"].calls == [] and after_snapshot["lane"] == before["lane"]
    assert row(w, "fleet_jobs", w["job"]["id"]) == w["job"]
    assert row(w, "fleet_control", "admission")["paused"] is True
    # The status view exposes the recovery.
    [shown] = [a for a in w["owner"].status()["actions"] if a["id"] == w["action"]["id"]]
    assert shown["state"] == do.REQUESTED and shown["recoveries"][0]["evidence_ref"] == evidence
    # While still queued, the existing result path only waits.
    assert w["owner"]._advance_canary(w["policy_row"], {}, row(w)) is None and w["files"].receipts == {}
    # LABELLED unpause + dispatch + accepted lane result: the existing path writes the receipt.
    put(w, "fleet_jobs", w["job"]["id"], {**w["job"], "status": "accepted", "reason_code": None,
                                          "calls": {"reserved": 1, "settled": 1}})
    effect = w["owner"]._advance_canary(w["policy_row"], {}, row(w))
    assert effect["state"] == do.COMPLETED and effect["reason_code"] == "canary_accepted"
    written = w["files"].receipts[PLAN_ID]
    assert written["passed"] is True and written["instance_id"] == INSTANCE
    assert written["descriptor_sha256"] == DESCRIPTOR and written["evidence"]["job_id"] == w["job"]["id"]
    # The same evidence replays as cached at any later state.
    replay = w["owner"].recover_canary(body, evidence)
    assert replay["cached"] is True and replay["state"] == do.COMPLETED
    assert w["fleet"].calls == []


def test_a_lane_change_after_the_recovery_is_held_again_by_the_existing_result_gate(w):
    body, evidence = document(w)
    w["owner"].recover_canary(body, evidence)
    w["files"].startup_receipt = {"instance_id": "inst-replaced", "descriptor_sha256": DESCRIPTOR}
    put(w, "fleet_jobs", w["job"]["id"], {**w["job"], "status": "accepted", "reason_code": None})
    effect = w["owner"]._advance_canary(w["policy_row"], {}, row(w))
    assert effect["state"] == do.UNKNOWN and effect["reason_code"] == "canary_delivery_moved"
    assert w["files"].receipts == {} and w["fleet"].calls == []
    # The one recovery is spent: other evidence is a conflict, the same evidence is cached.
    other, other_ref = document(w, margin_seconds=900)
    refused(w, "canary_recovery_conflict", other, other_ref)
    assert w["owner"].recover_canary(body, evidence)["cached"] is True


def test_the_same_replay_is_cached_and_other_evidence_conflicts(w):
    body, evidence = document(w)
    first = w["owner"].recover_canary(body, evidence)
    before = snapshot(w)
    again = w["owner"].recover_canary(body, evidence)
    assert again["cached"] is True and again["version"] == first["version"] and snapshot(w) == before
    other, other_ref = document(w, margin_seconds=700)
    refused(w, "canary_recovery_conflict", other, other_ref)


# ----- negatives: each a named refusal with zero writes ------------------------------------------------------
@pytest.mark.parametrize("override,code", [
    ({"action_version": 2}, "canary_recovery_version_mismatch"),
    ({"binding": {"plan_id": PLAN_ID, "plan_sha256": PLAN_SHA, "target_id": TARGET, "descriptor_sha256": "9" * 64,
                  "instance_id": INSTANCE}}, "canary_recovery_binding_mismatch"),
    ({"binding_sha256": "9" * 64}, "canary_recovery_binding_mismatch"),
    ({"policy_sha256": "9" * 64}, "canary_recovery_policy_mismatch"),
    ({"job_id": "canary-other"}, "canary_recovery_job_mismatch"),
    ({"halt": {"state": "unknown", "reason_code": "canary_delivery_moved", "updated_at": "2026-09-27T03:21:00+00:00"}},
     "canary_recovery_halt_mismatch"),
    ({"lane_retry_evidence": "sha256:" + "d" * 64}, "canary_recovery_lane_not_retried"),
    ({"margin_seconds": 3601}, "canary_recovery_margin"),
    ({"approved_by": "lead:research"}, "canary_recovery_approver_invalid"),
    ({"approved_by": "nobody"}, "canary_recovery_approver_invalid")])
def test_a_document_that_does_not_name_the_stored_facts_writes_nothing(w, override, code):
    body, evidence = document(w, **override)
    refused(w, code, body, evidence)


def test_evidence_must_be_the_digest_of_the_document(w):
    body, _ = document(w)
    refused(w, "canary_recovery_evidence_mismatch", body, "sha256:" + "0" * 64)
    refused(w, "canary_recovery_evidence_invalid", body, "sha1:abc")


@pytest.mark.parametrize("change,code", [
    ({"status": "dispatching"}, "canary_recovery_job_dispatching"),
    ({"status": "running"}, "canary_recovery_job_running"),
    ({"status": "accepted"}, "canary_recovery_job_accepted"),
    ({"status": "failed"}, "canary_recovery_job_failed"),
    ({"calls": {"reserved": 1, "settled": None}}, "canary_recovery_job_calls"),
    ({"dispatched_at": "2026-09-27T03:30:00+00:00"}, "canary_recovery_job_started"),
    ({"owner_token": "tok"}, "canary_recovery_job_started"),
    ({"lane": "b"}, "canary_recovery_job_mismatch"),
    ({"reason_code": "budget_stale"}, "canary_recovery_job_reason")])
def test_a_started_moved_or_foreign_job_writes_nothing(w, change, code):
    put(w, "fleet_jobs", w["job"]["id"], {**w["job"], **change})
    refused(w, code)


def test_a_missing_job_or_a_running_fleet_writes_nothing(w):
    put(w, "fleet_control", "admission", {"paused": False})
    refused(w, "canary_recovery_fleet_not_paused")


def test_a_missing_job_writes_nothing(stores):
    """The action names a job id whose Fleet row was never committed (a lost admission)."""
    control, lane = stores
    w = world(control, lane)
    missing = {**w["action"], "id": "9" * 64, "job_id": do.canary_job_id("9" * 64)}
    put(w, BUCKET_ACTIONS, missing["id"], missing)
    w["action"] = missing
    body, evidence = document(w)
    refused(w, "canary_recovery_job_missing", body, evidence)


@pytest.mark.parametrize("state,reason,code", [
    (do.UNKNOWN, "canary_job_unknown", "canary_recovery_not_applicable"),
    (do.REQUESTED, "canary_requested", "canary_recovery_not_applicable"),
    (do.REFUSED, "canary_delivery_moved", "canary_recovery_not_applicable")])
def test_a_foreign_state_or_reason_writes_nothing(w, state, reason, code):
    put(w, BUCKET_ACTIONS, w["action"]["id"], {**w["action"], "state": state, "reason_code": reason})
    refused(w, code)


def test_an_unknown_that_never_came_from_requested_writes_nothing(w):
    history = [w["action"]["history"][0], w["action"]["history"][2]]
    put(w, BUCKET_ACTIONS, w["action"]["id"], {**w["action"], "history": history})
    refused(w, "canary_recovery_not_from_requested")


def test_a_changed_policy_row_writes_nothing(w):
    put(w, BUCKET_POLICIES, "owners-1", {**w["policy_row"], "policy_sha256": "8" * 64})
    refused(w, "canary_recovery_policy_mismatch")


@pytest.mark.parametrize("change,code", [
    ({"stage": "blocked"}, "canary_recovery_lane_not_awaiting"),
    ({"recoveries": [{"kind": RECOVERY_FIRST_ACTIVATION, "evidence_ref": "sha256:" + "f" * 64}]},
     "canary_recovery_lane_not_retried"),
    ({"recoveries": [{"kind": RECOVERY_CONSUMPTION_RETRY, "evidence_ref": LANE_RETRY,
                      "observed": {"observed_instance_id": "inst-2", "descriptor_sha256": DESCRIPTOR}}]},
     "canary_recovery_instance_mismatch"),
    ({"recoveries": [{"kind": RECOVERY_CONSUMPTION_RETRY, "evidence_ref": LANE_RETRY,
                      "observed": {"observed_instance_id": INSTANCE, "descriptor_sha256": "7" * 64}}]},
     "canary_recovery_descriptor_mismatch"),
    ({"descriptor_sha256": "7" * 64}, "canary_recovery_delivery_moved"),
    ({"stage_deadline": (T0 + timedelta(seconds=599)).isoformat()}, "canary_recovery_margin")])
def test_a_lane_that_was_not_retried_for_this_instance_writes_nothing(w, change, code):
    intent = row(w, "host_delivery_intents", PLAN_ID, store="lane")
    put(w, "host_delivery_intents", PLAN_ID, {**intent, **change}, store="lane")
    refused(w, code)


def test_a_replaced_instance_or_an_existing_receipt_writes_nothing(w):
    w["files"].startup_receipt = {"instance_id": "inst-replaced", "descriptor_sha256": DESCRIPTOR}
    refused(w, "canary_recovery_delivery_moved")
    w["files"].startup_receipt = {"instance_id": INSTANCE, "descriptor_sha256": DESCRIPTOR}
    w["files"].receipts[PLAN_ID] = {"passed": False}
    refused(w, "canary_recovery_receipt_exists")


def test_the_candidate_author_cannot_approve_its_own_recovery(stores):
    w = world(*stores, author="conductor")
    refused(w, "canary_recovery_approver_author")


def test_a_concurrent_move_between_preflight_and_write_is_refused(w):
    """The control transaction compare-and-swaps the action, the job and the Fleet row."""
    body, evidence = document(w)
    original = w["owner"]._recovery_lane

    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        put(w, "fleet_jobs", w["job"]["id"], {**w["job"], "updated_at": "2026-09-27T04:00:01+00:00"})
        return result

    w["owner"]._recovery_lane = racing
    with pytest.raises(do.OwnerActionRefused) as caught:
        w["owner"].recover_canary(body, evidence)
    assert caught.value.reason_code == "canary_recovery_job_changed"
    assert row(w)["state"] == do.UNKNOWN and "recoveries" not in row(w)


# ----- the REAL two-store chain: real OwnerActions + real HostDelivery + real Fleet, separate stores ---------
@binds_a_runtime
def test_the_real_owner_and_real_lane_recover_the_halted_canary_end_to_end(tmp_path, monkeypatch):
    """REAL: HostDelivery (first activation, pending-canary halt, consumption retry) on its OWN store with a
    real process target and the incumbent `owner_qualified_canary`; OwnerActions and the real Fleet on a
    SEPARATE control store. LABELLED: the GitHub/first-activation/verifier ports of the lane fixture, the
    plan-scoped canary request document and the completed plan action (`request_for`/`canary_owner`),
    and the canary operation's executor (`World.run_next`)."""
    from test_host_delivery import (
        PROFILE,
        await_receipt,
        build,
        drive,
        intent_of,
        register_historical,
        stop_target,
    )
    from test_host_delivery_consumption_retry import retry
    from test_host_delivery_first_activation import IMAGE_ID, CountingVerifier, FixedFacts
    from test_host_delivery_first_activation import document as binding_document
    from test_owner_delivery import canary_owner

    from codex_harness.adapters.host_delivery import owner_qualified_canary
    from codex_harness.adapters.owner_actions import TargetFiles
    from codex_harness.domain.host_delivery import (
        ACTIVE,
        BLOCKED,
        CANARY_FLEET,
        CANARY_REQUEST_SCHEMA,
        MERGED,
        UNCHANGED,
        plan_digest,
        validate_plan,
    )

    monkeypatch.setenv("ZEUS_WORKER_IMAGE", IMAGE_ID)
    system = build(tmp_path / "delivery", plan_overrides={"image": UNCHANGED, "profile": UNCHANGED,
                                                          "canary": CANARY_FLEET, "consumption_timeout": 900},
                   register_plan=False, canaries={CANARY_FLEET: owner_qualified_canary})
    try:
        register_historical(system)
        drive(system, until=MERGED, limit=8)
        assert system["delivery"].tick()["reason_code"] == "unchanged_without_predecessor"
        system["delivery"].first_activation = FixedFacts(profile=PROFILE)
        system["verifier"] = CountingVerifier()
        system["delivery"].verifier = system["verifier"]
        body, evidence = binding_document(system, profile_digest=PROFILE)
        system["delivery"].resume_first_activation(system["plan"]["plan_id"], body["plan_sha256"], body, evidence)
        system["binding_evidence"] = evidence
        plan = validate_plan(system["plan"])
        # LABELLED: the plan-scoped owner request `_register` files for exactly this plan.
        TargetFiles.write_request(system["target"], plan["plan_id"], {
            "schema": CANARY_REQUEST_SCHEMA, "action_id": "a" * 64, "plan_id": plan["plan_id"],
            "plan_sha256": plan_digest(plan), "target_id": plan["target_id"],
            "revision": plan["target_descriptor"]["revision"], "expected_descriptor": plan["expected_descriptor"],
            "requested_at": system["clock"]()})
        # 1. the delivery awaits consumption; the owner canary goes INTENDED -> REQUESTED, job queued, Fleet paused.
        results = drive(system, until=AWAITING_CONSUMPTION, limit=40)
        assert results[-1]["stage"] == AWAITING_CONSUMPTION, [(r["stage"], r["reason_code"]) for r in results]
        await_receipt(system["target"], intent_of(system)["descriptor_sha256"], timeout=30.0)
        world, owner = canary_owner(tmp_path, system)
        owner.clock = system["clock"]
        world.fleet.pause()
        owner.tick("owners-1")
        [canary] = _canaries(world)
        assert canary["state"] == do.REQUESTED and world.jobs()[canary["job_id"]]["status"] == "queued"
        # 2. the lane window expires -> blocked; the owner tick -> UNKNOWN canary_delivery_moved.
        system["clock"].advance(900)
        halted_results = drive(system, until=ACTIVE, limit=40)
        assert (halted_results[-1]["stage"], halted_results[-1]["reason_code"]) == (
            BLOCKED, "no_known_good_predecessor"), halted_results[-1]
        owner.tick("owners-1")
        [canary] = _canaries(world)
        assert (canary["state"], canary["reason_code"]) == (do.UNKNOWN, "canary_delivery_moved")
        # 3. the lane consumption retry -> awaiting_consumption.
        assert retry(system)["stage"] == AWAITING_CONSUMPTION
        lane_retry = intent_of(system)["recoveries"][-1]["evidence_ref"]
        # 4. the owner recovery -> REQUESTED, the SAME job still queued.
        job_before = world.jobs()[canary["job_id"]]
        recovery = {"schema": do.CANARY_RECOVERY_SCHEMA, "kind": do.CANARY_RECOVERY_KIND, "action_id": canary["id"],
                    "action_version": canary["version"], "binding_sha256": canary["binding_sha256"],
                    "binding": dict(canary["binding"]), "policy_id": canary["policy_id"],
                    "policy_sha256": canary["policy_sha256"], "job_id": canary["job_id"],
                    "halt": {"state": canary["state"], "reason_code": canary["reason_code"],
                             "updated_at": canary["updated_at"]},
                    "lane_retry_evidence": lane_retry, "margin_seconds": 600, "approved_by": "conductor"}
        receipt = owner.recover_canary(recovery, "sha256:" + digest(recovery))
        assert receipt["state"] == do.REQUESTED and receipt["job_id"] == canary["job_id"]
        assert world.jobs()[canary["job_id"]] == job_before and len(world.jobs()) == 1
        # 5. LABELLED unpause -> the job dispatches -> accepted -> the owner writes the receipt -> promoted.
        world.fleet.resume()
        job, outcome = world.run_next(verdict=True)
        assert job == canary["job_id"] and outcome["status"] == "accepted"
        owner.tick("owners-1")
        [canary] = _canaries(world)
        assert canary["state"] == do.COMPLETED
        written = TargetFiles.receipt(system["target"], plan["plan_id"])
        assert written["passed"] is True and written["instance_id"] == canary["binding"]["instance_id"]
        assert drive(system, until=ACTIVE, limit=40)[-1]["stage"] == ACTIVE
        assert owner.recover_canary(recovery, "sha256:" + digest(recovery))["cached"] is True
    finally:
        stop_target(system)


def _canaries(world):
    with world.control.transaction() as tx:
        return [r for r in tx.scan(BUCKET_ACTIONS) if r["kind"] == do.DELIVERY_CANARY]


# ----- the thin CLI: `zeus owner-actions canary-recover --document FILE --evidence sha256:<digest>` ----------
def test_the_cli_drives_the_real_recovery_and_refuses_an_unreadable_document(tmp_path, monkeypatch, capsys):
    """The real `cli.owner_actions_command` -> `execute` -> `OwnerActions.recover_canary`. LABELLED: the Fleet
    registration read and the coordinator factory (it returns this module's real, labelled-port owner)."""
    import argparse
    import json
    from types import SimpleNamespace

    from codex_harness import cli
    from codex_harness.adapters import owner_actions as adapter

    w = world(MemoryStore(), MemoryStore())
    monkeypatch.setattr("codex_harness.application.fleet.Fleet.registered", lambda self: {"config": {"lanes": []}})
    monkeypatch.setattr("codex_harness.adapters.configuration.settings", lambda: {})
    monkeypatch.setattr(adapter, "coordinator", lambda svc, config, host: w["owner"])
    service = SimpleNamespace(store=w["control"], org=organization())

    def run(path, evidence):
        args = argparse.Namespace(owner_actions_command="canary-recover", document=str(path), evidence=evidence)
        code = 0
        try:
            cli.owner_actions_command(service, args)
        except SystemExit as exc:
            code = exc.code
        return code, json.loads(capsys.readouterr().out)

    code, out = run(tmp_path / "absent.json", "sha256:" + "0" * 64)
    assert code == 1 and out["reason_code"] == "canary_recovery_document_unreadable"
    body, evidence = document(w)
    path = tmp_path / "recovery.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    code, out = run(path, "sha256:" + "0" * 64)
    assert code == 1 and out["reason_code"] == "canary_recovery_evidence_mismatch" and row(w)["state"] == do.UNKNOWN
    code, out = run(path, evidence)
    assert (code or 0) == 0 and out["state"] == do.REQUESTED and out["cached"] is False
    code, out = run(path, evidence)
    assert (code or 0) == 0 and out["cached"] is True
    parser = argparse.ArgumentParser()
    adapter.add_parser(parser.add_subparsers(dest="command"))
    parsed = parser.parse_args(["owner-actions", "canary-recover", "--document", "f.json", "--evidence", evidence])
    assert (parsed.owner_actions_command, parsed.document, parsed.evidence) == ("canary-recover", "f.json", evidence)


def test_an_unreadable_existing_canary_receipt_is_unknown_never_absent(tmp_path):
    """A receipt file that exists but is not a JSON object must block the recovery (it is not proof of absence)."""
    from codex_harness.adapters.host_delivery import HostTargetBase, canary_receipt_file
    from codex_harness.adapters.owner_actions import TargetFiles

    target = {"target_id": "t", "kind": "process", "root": str(tmp_path / "root"), "state_dir": str(tmp_path / "state"),
              "service": "svc"}
    (tmp_path / "state").mkdir()
    assert TargetFiles.receipt(target, "own-" + "a" * 24) is None
    path = HostTargetBase.path(target, canary_receipt_file("own-" + "a" * 24))
    path.write_text("{not json", "utf-8")
    assert TargetFiles.receipt(target, "own-" + "a" * 24) == {"unreadable": True}
    path.write_text("[1, 2]", "utf-8")
    assert TargetFiles.receipt(target, "own-" + "a" * 24) == {"unreadable": True}
