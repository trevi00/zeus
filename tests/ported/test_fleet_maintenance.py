"""Ported PR-3 suite `tests/test_fleet_maintenance.py` (e6e15f00, `feat/host-delivery-maintain-pr3`, under Codex review G1-06) run against the target.

Every assertion is PR-3's, unchanged. Adaptations, all import, construction and patch-target: `Fleet` is the `m7_coordination` facade over the split Fleet objects (the maintenance methods route to `FleetMaintenance`), `BUCKET_MAINTENANCE` is `coordination.application.fleet.state`'s, the domain modules are coordination's, `digest` is the kernel's and `MemoryStore` is storage's.

PR-3 docstring follows.

The one-job maintenance canary permit over MemoryStore (INV-FLEET-001 maintenance amendment,
INV-HOST-DELIVERY-MAINTENANCE-001).

Owner action rows are LABELLED fixtures written directly into the control store exactly as
`OwnerActions._advance_canary` produces them (`new_action` then `moved(..., REQUESTED, job_id=...)`
over the real domain functions); canary jobs are enqueued through the real `Fleet.enqueue`. No
launcher, store, host, model or provider outside this process is reached.
"""
import json
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from m7_coordination import Fleet
from test_fleet import GOAL, config, manifest

from codex_harness.coordination.application.fleet.state import BUCKET_MAINTENANCE
from codex_harness.coordination.domain.fleet import FleetRefused, new_job
from codex_harness.coordination.domain.fleet_maintenance import (
    PERMIT_SCHEMA,
    PERMIT_VIEW_FIELDS,
    canary_binding_of,
    check_owner_action,
    deadline_passed,
    permit_digest,
    permit_view,
    validate_permit,
    validate_proof,
)
from codex_harness.coordination.domain.operation import manifest_digest
from codex_harness.coordination.domain.owner_actions import (
    COMPLETED,
    DELIVERY_CANARY,
    INTENDED,
    REQUESTED,
    UNKNOWN,
    action_id,
    canary_job_id,
    moved,
    new_action,
)
from codex_harness.kernel.ids import digest
from codex_harness.storage.adapters.memory_store import MemoryStore

SENTINEL = "SENTINEL-maintenance-value-never-emitted"
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
MID = "active_generation_1:" + "a" * 64
OTHER_MID = "active_generation_1:" + "c" * 64
EVIDENCE = "sha256:" + "b" * 64
BINDING = {"plan_id": "plan-maintenance", "plan_sha256": "1" * 64, "target_id": "managed-fleet",
           "descriptor_sha256": "d" * 64, "instance_id": "e" * 32}
POLICY_ROW = {"id": "owner-policy", "policy_sha256": "f" * 64}
UNIT = "9" * 64
CANARY_PATHS = ["canary/probe.md"]


class Clock:
    """A LABELLED fixed Fleet clock that only moves when a test advances it."""

    def __init__(self, at=NOW):
        self.at = at

    def __call__(self) -> str:
        return self.at.isoformat()

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


def permit_for(binding=None, *, mid=MID, window=600, **overrides) -> dict:
    """The permit HostDelivery builds for an armed generation (spec §3.2)."""
    binding = dict(binding or BINDING)
    identity = action_id(DELIVERY_CANARY, binding)
    return {"schema": PERMIT_SCHEMA, "maintenance_id": mid, "evidence_ref": EVIDENCE, **binding,
            "action_id": identity, "job_id": canary_job_id(identity),
            "deadline": (NOW + timedelta(seconds=window)).isoformat(), **overrides}


def proof_for(permit: dict, **overrides) -> dict:
    """The proof HostDelivery pins from the acknowledged ARMED lane generation."""
    return {"maintenance_id": permit["maintenance_id"], "permit_sha256": digest(permit), "generation_state": "armed",
            "acknowledged": True, "deadline": permit["deadline"], "instance_id": permit["instance_id"],
            "descriptor_sha256": permit["descriptor_sha256"], **overrides}


def put_action(store, permit: dict, state: str = REQUESTED, **overrides) -> dict:
    """LABELLED owner action row: what `OwnerActions._advance_canary` writes before it enqueues the job."""
    row = new_action(DELIVERY_CANARY, canary_binding_of(permit), POLICY_ROW, {"plan_action_id": "p" * 64},
                     NOW.isoformat())
    if state != INTENDED:
        row = moved(row, REQUESTED, NOW.isoformat(), "canary_requested", job_id=canary_job_id(row["id"]))
    if state not in {INTENDED, REQUESTED}:
        row = moved(row, state, NOW.isoformat(), "canary_" + state)
    row.update(overrides)
    with store.transaction() as tx:
        tx.put("owner_actions", row["id"], row)
    return row


def enqueue_canary(f: Fleet, permit: dict, lane: str = "a", dependencies=()) -> dict:
    return f.enqueue(lane, manifest(permit["job_id"], CANARY_PATHS), GOAL, list(dependencies))["job"]


def owner_paused_fleet(tmp_path, clock=None, **overrides) -> Fleet:
    f = Fleet(MemoryStore(), clock=clock or Clock())
    f.register(config(tmp_path, **overrides))
    f.pause()
    return f


def granted(tmp_path, clock=None, permit=None, **overrides):
    """An owner-paused Fleet with a granted permit, its REQUESTED owner action and its queued canary."""
    f = owner_paused_fleet(tmp_path, clock, **overrides)
    permit = permit or permit_for()
    f.grant_maintenance_canary(permit)
    put_action(f.store, permit)
    enqueue_canary(f, permit)
    return f, permit


def admit(f: Fleet, permit: dict, **overrides) -> dict:
    kwargs = {"permit_sha256": digest(permit), "proof": proof_for(permit), "budget_exhausted": False, **overrides}
    return f.admit_maintenance_canary(permit["maintenance_id"], **kwargs)


def snapshot(store) -> dict:
    return deepcopy(store.data)


def row_of(store, bucket: str, key: str):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def put_row(store, bucket: str, key: str, body: dict) -> None:
    """LABELLED direct store write standing in for another owner's committed state."""
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def refused(call, code: str, field: str | None = None) -> FleetRefused:
    with pytest.raises(FleetRefused) as info:
        call()
    assert (info.value.reason_code, info.value.field) == (code, field)
    assert SENTINEL not in str(info.value)
    return info.value


# ---- the permit grammar -------------------------------------------------------------------------------
@pytest.mark.parametrize("mutate, field", [
    (lambda p: p.pop("deadline"), "permit"),
    (lambda p: p.update(token=SENTINEL), "permit"),
    (lambda p: p.update(schema="urn:zeus:fleet-maintenance-permit:2"), "schema"),
    (lambda p: p.update(maintenance_id="active_generation_1:" + "A" * 64), "maintenance_id"),
    (lambda p: p.update(maintenance_id="active_generation_2:" + "a" * 64), "maintenance_id"),
    (lambda p: p.update(evidence_ref="b" * 64), "evidence_ref"),
    (lambda p: p.update(evidence_ref=SENTINEL), "evidence_ref"),
    (lambda p: p.update(plan_id="bad plan " + SENTINEL), "plan_id"),
    (lambda p: p.update(plan_sha256="1" * 63), "plan_sha256"),
    (lambda p: p.update(target_id=""), "target_id"),
    (lambda p: p.update(descriptor_sha256="D" * 64), "descriptor_sha256"),
    (lambda p: p.update(instance_id="e" * 31), "instance_id"),
    (lambda p: p.update(instance_id=None), "instance_id"),
    (lambda p: p.update(action_id="7" * 64), "action_id"),
    (lambda p: p.update(job_id="op-unrelated"), "job_id"),
    (lambda p: p.update(job_id=canary_job_id("7" * 64)), "job_id"),
    (lambda p: p.update(deadline="2026-09-29T12:10:00"), "deadline"),
    (lambda p: p.update(deadline=1790000000), "deadline"),
    (lambda p: p.update(deadline=SENTINEL * 3), "deadline"),
])
def test_permit_grammar_is_exact(mutate, field):
    permit = permit_for()
    assert validate_permit(permit) == permit and permit_digest(permit) == digest(permit)
    bad = deepcopy(permit)
    mutate(bad)
    refused(lambda: validate_permit(bad), "maintenance_invalid", field)
    refused(lambda: validate_permit([permit]), "maintenance_invalid", "permit")
    # The action id is the owner action identity of exactly this binding, so the job id is too.
    assert permit["job_id"] == canary_job_id(action_id(DELIVERY_CANARY, BINDING))
    # A proof that is not the acknowledged armed generation of this exact permit is refused.
    assert validate_proof(proof_for(permit), permit, digest(permit)) == proof_for(permit)
    refused(lambda: validate_proof({**proof_for(permit), "acknowledged": 1}, permit, digest(permit)),
            "maintenance_admission_refused", "proof")
    assert deadline_passed(permit["deadline"], (NOW + timedelta(seconds=600)).isoformat())
    assert not deadline_passed(permit["deadline"], (NOW + timedelta(seconds=599)).isoformat())


# ---- grant --------------------------------------------------------------------------------------------
def test_grant_requires_owner_pause_and_replays_only_the_whole_binding(tmp_path):
    permit = permit_for()
    refused(lambda: Fleet(MemoryStore()).grant_maintenance_canary(permit), "unregistered")
    running = Fleet(MemoryStore(), clock=Clock())
    running.register(config(tmp_path))
    before = snapshot(running.store)
    refused(lambda: running.grant_maintenance_canary(permit), "maintenance_pause_required", "fleet")
    # A managed runtime's activation hold is a pause, but not the OWNER's pause.
    running.activation_gate("managed-fleet", "d" * 64)
    held = snapshot(running.store)
    refused(lambda: running.grant_maintenance_canary(permit), "maintenance_pause_required", "fleet")
    assert snapshot(running.store) == held and before != held

    clock = Clock()
    f = owner_paused_fleet(tmp_path, clock)
    jobs_and_control = {k: v for k, v in snapshot(f.store).items() if k[0] != BUCKET_MAINTENANCE}
    first = f.grant_maintenance_canary(permit)
    assert first == {"granted": True, "cached": False, "maintenance_id": MID, "permit_sha256": digest(permit),
                     "state": "granted"}
    assert {k: v for k, v in snapshot(f.store).items() if k[0] != BUCKET_MAINTENANCE} == jobs_and_control, \
        "a grant writes only its permit row"
    after_grant = snapshot(f.store)
    assert f.grant_maintenance_canary(deepcopy(permit)) == {**first, "cached": True}
    for changed in (permit_for(evidence_ref="sha256:" + "4" * 64), permit_for(window=900),
                    permit_for({**BINDING, "instance_id": "5" * 32})):
        refused(lambda changed=changed: f.grant_maintenance_canary(changed), "maintenance_conflict", "permit")
    refused(lambda: f.grant_maintenance_canary(permit_for(mid=OTHER_MID)), "maintenance_conflict", "maintenance_id")
    assert snapshot(f.store) == after_grant, "no refusal writes"

    # The deadline is the one immutable arm deadline: a grant at or after it is refused.
    late = owner_paused_fleet(tmp_path, Clock(NOW + timedelta(seconds=600)))
    refused(lambda: late.grant_maintenance_canary(permit), "maintenance_expired", "deadline")
    assert late.maintenance_permit(MID) is None

    # Once the first permit is closed (and its canary settled), another maintenance may be granted.
    f.close_maintenance_canary(permit, "maintenance_cancelled")
    assert f.grant_maintenance_canary(permit)["cached"] is True, "a closed permit still replays"
    assert f.grant_maintenance_canary(permit_for(mid=OTHER_MID))["cached"] is False


# ---- admission ----------------------------------------------------------------------------------------
def test_admission_admits_exactly_the_owned_canary_while_owner_paused(tmp_path):
    clock = Clock()
    f = owner_paused_fleet(tmp_path, clock)
    older = f.enqueue("b", manifest("op-older", ["docs/older.md"]), GOAL, [])["job"]  # oldest queued job
    permit = permit_for()
    f.grant_maintenance_canary(permit)
    put_action(f.store, permit)
    enqueue_canary(f, permit)
    control = row_of(f.store, "fleet_control", "admission")
    unrelated = row_of(f.store, "fleet_jobs", older["id"])

    result = admit(f, permit)
    job = result["job"]
    assert result["admitted"] is True and result["maintenance_id"] == MID
    assert job["id"] == permit["job_id"] and job["status"] == "dispatching" and job["owner_token"]
    assert job["dispatched_at"] == clock() and job["reason_code"] is None
    assert row_of(f.store, "fleet_jobs", job["id"]) == job, "the claim is durable before any process exists"
    assert row_of(f.store, "fleet_jobs", older["id"]) == unrelated, "other queued jobs are not read-modified"
    assert row_of(f.store, "fleet_control", "admission") == control, "the owner pause is untouched"
    row = row_of(f.store, BUCKET_MAINTENANCE, MID)
    assert row["state"] == "admitted" and row["admitted_at"] == clock()
    assert (row["lane"], row["manifest_sha256"], row["owner_token"]) == ("a", job["manifest_sha256"],
                                                                         job["owner_token"])
    assert row["lane_ack"] == {"proof_sha256": digest(proof_for(permit)), "at": clock()}
    assert [h["state"] for h in row["history"]] == ["granted", "admitted"]

    # A job enqueued concurrently and the ordinary dispatcher and conductor stay closed.
    f.enqueue("b", manifest("op-later", ["docs/later.md"]), GOAL, [])
    ordinary = f.admit_one()
    assert ordinary["job"] is None and ordinary["paused"] is True
    assert {j["id"]: j["status"] for j in f.status()["jobs"]} == {
        "op-older": "queued", "op-later": "queued", permit["job_id"]: "dispatching"}
    refused(lambda: f.reserve_unit(UNIT, "conductor", "b", "intent-x"), "paused")
    assert f.status()["paused"] is True


@pytest.mark.parametrize("case", ["missing", "intended", "completed", "unknown", "binding", "binding_sha256",
                                  "job_id", "kind"])
def test_admission_never_trusts_a_caller_job_or_a_moved_action(tmp_path, case):
    f = owner_paused_fleet(tmp_path)
    permit = permit_for()
    f.grant_maintenance_canary(permit)
    if case != "missing":
        state = {"intended": INTENDED, "completed": COMPLETED, "unknown": UNKNOWN}.get(case, REQUESTED)
        overrides = {"binding": {**BINDING, "instance_id": "5" * 32}} if case == "binding" else \
            {"binding_sha256": "0" * 64} if case == "binding_sha256" else \
            {"job_id": "canary-" + "0" * 24} if case == "job_id" else \
            {"kind": "delivery_plan"} if case == "kind" else {}
        put_action(f.store, permit, state, **overrides)
    enqueue_canary(f, permit)
    before = snapshot(f.store)
    refused(lambda: admit(f, permit), "maintenance_admission_refused", "action")
    assert snapshot(f.store) == before


def test_admission_refuses_a_job_that_is_not_the_exact_queued_canary(tmp_path):
    f = owner_paused_fleet(tmp_path)
    permit = permit_for()
    f.grant_maintenance_canary(permit)
    put_action(f.store, permit)
    before = snapshot(f.store)
    refused(lambda: admit(f, permit), "maintenance_admission_refused", "job")  # owner-actions has not queued it
    assert snapshot(f.store) == before
    job = enqueue_canary(f, permit)
    for status in ("failed", "accepted", "dispatching", "unknown"):
        # LABELLED: the canary already left `queued` (a previous claim or outcome).
        put_row(f.store, "fleet_jobs", job["id"], {**row_of(f.store, "fleet_jobs", job["id"]), "status": status})
        state = snapshot(f.store)
        refused(lambda: admit(f, permit), "maintenance_admission_refused", "job")
        assert snapshot(f.store) == state
    # The caller never names a job: a permit naming any job but the action's canary is not a permit.
    foreign = f.enqueue("b", manifest("op-foreign", ["docs/f.md"]), GOAL, [])["job"]
    refused(lambda: f.grant_maintenance_canary({**permit_for(mid=OTHER_MID), "job_id": foreign["id"]}),
            "maintenance_invalid", "job_id")
    with pytest.raises(TypeError):
        f.admit_maintenance_canary(MID, permit_sha256=digest(permit), proof=proof_for(permit),
                                   budget_exhausted=False, job_id=foreign["id"])


@pytest.mark.parametrize("proof_change", [
    {"acknowledged": False}, {"acknowledged": "true"}, {"generation_state": "started"},
    {"generation_state": "requested"}, {"deadline": (NOW + timedelta(seconds=601)).isoformat()},
    {"instance_id": "5" * 32}, {"descriptor_sha256": "6" * 64}, {"maintenance_id": OTHER_MID},
    {"permit_sha256": "0" * 64}, {"extra": SENTINEL}, None,
])
def test_an_orphan_or_unacknowledged_grant_cannot_launch(tmp_path, proof_change):
    f, permit = granted(tmp_path)
    before = snapshot(f.store)
    proof = None if proof_change is None else {**proof_for(permit), **proof_change}
    refused(lambda: admit(f, permit, proof=proof), "maintenance_admission_refused", "proof")
    assert snapshot(f.store) == before
    refused(lambda: admit(f, permit, permit_sha256="0" * 64), "maintenance_conflict", "permit")
    refused(lambda: f.admit_maintenance_canary(OTHER_MID, permit_sha256=digest(permit), proof=proof_for(permit),
                                               budget_exhausted=False), "maintenance_admission_refused", "permit")
    refused(lambda: f.admit_maintenance_canary(SENTINEL, permit_sha256=digest(permit), proof=proof_for(permit),
                                               budget_exhausted=False), "maintenance_admission_refused", "permit")
    assert snapshot(f.store) == before
    assert admit(f, permit)["job"]["status"] == "dispatching", "the exact acknowledged proof admits"


def test_every_other_blocker_still_refuses(tmp_path):
    # The machine ledger.
    f, permit = granted(tmp_path)
    before = snapshot(f.store)
    refused(lambda: admit(f, permit, budget_exhausted=True), "maintenance_admission_refused", "budget_exhausted")
    assert snapshot(f.store) == before

    # A budget grant after the canary was frozen: the job carries stale ceilings (LABELLED crafted
    # row, because enqueue itself refuses a stale manifest and a grant refuses a non-idle fleet).
    stale = owner_paused_fleet(tmp_path)
    permit = permit_for()
    stale.grant_maintenance_canary(permit)
    put_action(stale.store, permit)
    stale.authorize_budget(8, 16, 8)
    old = manifest(permit["job_id"], CANARY_PATHS)
    lane = config(tmp_path)["lanes"][0]
    put_row(stale.store, "fleet_jobs", permit["job_id"],
            new_job(old, manifest_digest(old), lane, GOAL, [], NOW.isoformat()))
    before = snapshot(stale.store)
    refused(lambda: admit(stale, permit), "maintenance_admission_refused", "budget_stale")
    assert snapshot(stale.store) == before

    # A dependency that failed (LABELLED: a finished prerequisite recorded by its owner).
    dep = owner_paused_fleet(tmp_path)
    permit = permit_for()
    dep.grant_maintenance_canary(permit)
    put_action(dep.store, permit)
    prerequisite = dep.enqueue("b", manifest("op-dep", ["docs/dep.md"]), GOAL, [])["job"]
    put_row(dep.store, "fleet_jobs", "op-dep", {**row_of(dep.store, "fleet_jobs", "op-dep"), "status": "failed"})
    enqueue_canary(dep, permit, dependencies=[prerequisite["id"]])
    before = snapshot(dep.store)
    refused(lambda: admit(dep, permit), "maintenance_admission_refused", "dependency_failed")
    assert snapshot(dep.store) == before

    # Reserving work on the canary's lane or paths, or anywhere: debt first (capacity, lane_busy and
    # path_conflict all need a reserving job, so the debt refusal subsumes them).
    for lane_id, paths in (("a", ["docs/other.md"]), ("b", CANARY_PATHS), ("b", ["docs/elsewhere.md"])):
        busy, permit = granted(tmp_path)
        other = busy.enqueue(lane_id, manifest("op-busy", paths), GOAL, [])["job"]
        put_row(busy.store, "fleet_jobs", other["id"], {**row_of(busy.store, "fleet_jobs", other["id"]),
                                                          "status": "dispatching", "owner_token": "t"})
        before = snapshot(busy.store)
        refused(lambda busy=busy, permit=permit: admit(busy, permit), "maintenance_debt_unsettled", "fleet")
        assert snapshot(busy.store) == before

    # A held execution unit (a conductor reserved before the owner paused).
    unit = Fleet(MemoryStore(), clock=Clock())
    unit.register(config(tmp_path))
    unit.reserve_unit(UNIT, "conductor", "b", "intent-held")
    unit.pause()
    permit = permit_for()
    unit.grant_maintenance_canary(permit)
    put_action(unit.store, permit)
    enqueue_canary(unit, permit)
    before = snapshot(unit.store)
    refused(lambda: admit(unit, permit), "maintenance_debt_unsettled", "fleet")
    assert snapshot(unit.store) == before

    # The pause itself must still be the owner's (LABELLED crafted control rows).
    for control in ({"paused": False}, {"paused": True, "activation_hold": {"target_id": "managed-fleet"}}):
        paused, permit = granted(tmp_path)
        row = row_of(paused.store, "fleet_control", "admission")
        put_row(paused.store, "fleet_control", "admission", {**row, **control})
        before = snapshot(paused.store)
        refused(lambda paused=paused, permit=permit: admit(paused, permit), "maintenance_pause_required", "fleet")
        assert snapshot(paused.store) == before


def test_second_admission_is_already_used_and_never_a_second_claim(tmp_path):
    f, permit = granted(tmp_path)
    first = admit(f, permit)
    after = snapshot(f.store)
    refused(lambda: admit(f, permit), "maintenance_already_used", "state")
    assert snapshot(f.store) == after
    assert row_of(f.store, "fleet_jobs", permit["job_id"])["owner_token"] == first["job"]["owner_token"]

    # Concurrent admissions over the serialized store: exactly one claim.
    race, permit = granted(tmp_path)
    barrier, results = threading.Barrier(4), []

    def contender():
        barrier.wait()
        try:
            results.append(("admitted", admit(race, permit)["job"]["owner_token"]))
        except FleetRefused as exc:
            results.append((exc.reason_code, exc.field))

    threads = [threading.Thread(target=contender) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    winners = [token for kind, token in results if kind == "admitted"]
    assert len(winners) == 1 and sorted(r for r in results if r[0] != "admitted") == [
        ("maintenance_already_used", "state")] * 3
    job = row_of(race.store, "fleet_jobs", permit["job_id"])
    assert job["status"] == "dispatching" and job["owner_token"] == winners[0]
    assert row_of(race.store, BUCKET_MAINTENANCE, MID)["owner_token"] == winners[0]


# ---- expiry, cancellation and settlement --------------------------------------------------------------
def test_expired_unadmitted_canary_fails_without_launch_and_closes(tmp_path):
    clock = Clock()
    f, permit = granted(tmp_path, clock)
    before = snapshot(f.store)
    refused(lambda: f.close_maintenance_canary(permit, "maintenance_expired"), "maintenance_stale", "deadline")
    refused(lambda: f.close_maintenance_canary(permit, "maintenance_retired"), "maintenance_invalid", "reason")
    refused(lambda: f.close_maintenance_canary(permit_for(window=900), "maintenance_cancelled"),
            "maintenance_conflict", "permit")
    assert snapshot(f.store) == before
    clock.advance(600)
    refused(lambda: admit(f, permit), "maintenance_expired", "deadline")
    closed = f.close_maintenance_canary(permit, "maintenance_expired")
    assert closed == {"closed": True, "cached": False, "maintenance_id": MID, "close_reason": "maintenance_expired",
                      "job_status": "failed", "launched": False}
    job = row_of(f.store, "fleet_jobs", permit["job_id"])
    assert (job["status"], job["reason_code"], job["owner_token"], job["dispatched_at"]) == (
        "failed", "maintenance_expired", None, None)
    assert job["maintenance"] == {"maintenance_id": MID, "launched": False, "reason": "maintenance_expired"}
    row = row_of(f.store, BUCKET_MAINTENANCE, MID)
    assert (row["state"], row["close_reason"], row["launched"], row["owner_token"]) == (
        "closed", "maintenance_expired", False, None)
    after = snapshot(f.store)
    assert f.close_maintenance_canary(permit, "maintenance_expired") == {**closed, "cached": True}
    assert f.close_maintenance_canary(permit, "maintenance_cancelled") == {**closed, "cached": True}, \
        "the recorded reason is kept"
    refused(lambda: admit(f, permit), "maintenance_already_used", "state")
    assert snapshot(f.store) == after
    assert f.reconciliation_required() == [] and f.maintenance_readiness()["open_permits"] == []

    # No permit row yet (the grant's response and commit were lost): the exact queued canary still fails.
    bare_clock = Clock()
    bare = owner_paused_fleet(tmp_path, bare_clock)
    put_action(bare.store, permit)
    enqueue_canary(bare, permit)
    bare_clock.advance(601)
    assert bare.close_maintenance_canary(permit, "maintenance_expired")["job_status"] == "failed"
    assert row_of(bare.store, BUCKET_MAINTENANCE, MID)["granted_at"] is None
    assert row_of(bare.store, "fleet_jobs", permit["job_id"])["reason_code"] == "maintenance_expired"

    # A queued job under the canary id that is not this permit's owner canary is never touched.
    for action in (None, {"binding": {**BINDING, "instance_id": "5" * 32}}, {"job_id": "canary-" + "0" * 24}):
        foreign_clock = Clock()
        foreign = owner_paused_fleet(tmp_path, foreign_clock)
        foreign.grant_maintenance_canary(permit)
        if action is not None:
            put_action(foreign.store, permit, **action)
        enqueue_canary(foreign, permit)
        foreign_clock.advance(601)
        before = snapshot(foreign.store)
        refused(lambda foreign=foreign: foreign.close_maintenance_canary(permit, "maintenance_expired"),
                "maintenance_conflict", "job")
        assert snapshot(foreign.store) == before

    # Cancellation needs no deadline and also fails the queued canary without a launch, even after
    # owner-actions moved its action to `unknown` (`canary_delivery_moved`).
    cancel, permit = granted(tmp_path)
    put_action(cancel.store, permit, UNKNOWN)
    result = cancel.close_maintenance_canary(permit, "maintenance_cancelled")
    assert (result["job_status"], result["launched"]) == ("failed", False)


def test_admitted_work_is_never_expired_only_settled(tmp_path):
    clock = Clock()
    f, permit = granted(tmp_path, clock)
    job = admit(f, permit)["job"]
    clock.advance(3600)
    before = snapshot(f.store)
    for reason in ("maintenance_expired", "maintenance_cancelled", "maintenance_settled"):
        refused(lambda reason=reason: f.close_maintenance_canary(permit, reason),
                "maintenance_reconciliation_required", "job")
    assert snapshot(f.store) == before
    # An uncertain outcome keeps its reservation: still reconciliation, never a settlement.
    f.finalize(job["id"], job["owner_token"], {"status": "unknown", "reason_code": "receipt_missing"})
    refused(lambda: f.close_maintenance_canary(permit, "maintenance_settled"),
            "maintenance_reconciliation_required", "job")
    refused(lambda: f.close_maintenance_canary(permit, "maintenance_expired"),
            "maintenance_reconciliation_required", "job")

    settled_clock = Clock()
    done, permit = granted(tmp_path, settled_clock)
    job = admit(done, permit)["job"]
    done.finalize(job["id"], job["owner_token"], {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0})
    settled_clock.advance(3600)
    closed = done.close_maintenance_canary(permit, "maintenance_settled")
    assert closed == {"closed": True, "cached": False, "maintenance_id": MID, "close_reason": "maintenance_settled",
                      "job_status": "accepted", "launched": True}
    assert done.close_maintenance_canary(permit, "maintenance_expired") == {**closed, "cached": True}
    assert row_of(done.store, "fleet_jobs", job["id"])["status"] == "accepted", "settlement never rewrites the job"

    # A granted but never admitted permit cannot be `settled`.
    unadmitted, permit = granted(tmp_path)
    refused(lambda: unadmitted.close_maintenance_canary(permit, "maintenance_settled"),
            "maintenance_reconciliation_required", "job")


def test_general_resume_and_activation_release_stay_closed_while_a_permit_is_open(tmp_path):
    f, permit = granted(tmp_path)
    f.enqueue("b", manifest("op-waiting", ["docs/w.md"]), GOAL, [])
    control = row_of(f.store, "fleet_control", "admission")
    refused(f.resume, "maintenance_debt_unsettled", "maintenance")
    assert row_of(f.store, "fleet_control", "admission") == control
    # A runtime activation hold release is a resume too (LABELLED crafted hold beside the permit).
    held = {**control, "activation_hold": {"target_id": "managed-fleet", "descriptor_sha256": "d" * 64}}
    put_row(f.store, "fleet_control", "admission", held)
    assert f.release_activation_hold("d" * 64) == {"released": False}
    assert row_of(f.store, "fleet_control", "admission") == held
    put_row(f.store, "fleet_control", "admission", control)
    assert f.pause()["paused"] is True, "pausing is always allowed"

    f.close_maintenance_canary(permit, "maintenance_cancelled")
    assert f.resume()["paused"] is False
    admitted = f.admit_one()
    assert admitted["job"]["id"] == "op-waiting", "unrelated work resumes normally"
    assert f.admit_one()["job"] is None, "the failed canary is never admitted by a later ordinary resume"
    assert row_of(f.store, "fleet_jobs", permit["job_id"])["status"] == "failed"

    # With the permit closed, a runtime's own hold is released as before.
    hold, permit = granted(tmp_path)
    hold.close_maintenance_canary(permit, "maintenance_cancelled")
    put_row(hold.store, "fleet_control", "admission",
            {**row_of(hold.store, "fleet_control", "admission"),
             "activation_hold": {"target_id": "managed-fleet", "descriptor_sha256": "d" * 64}})
    assert hold.release_activation_hold("d" * 64) == {"released": True}


def test_a_canary_queued_after_an_unlaunched_close_is_failed_on_replay_and_blocks_resume_until_then(tmp_path):
    f = owner_paused_fleet(tmp_path)
    permit = permit_for()
    f.grant_maintenance_canary(permit)
    put_action(f.store, permit)
    closed = f.close_maintenance_canary(permit, "maintenance_cancelled")
    assert (closed["job_status"], closed["launched"]) == (None, False)
    assert f.maintenance_readiness()["open_permits"] == []
    # Owner-actions enqueues the canary late (its tick ran between the close and the lane failure).
    enqueue_canary(f, permit)
    assert f.maintenance_readiness()["open_permits"] == [MID]
    refused(f.resume, "maintenance_debt_unsettled", "maintenance")
    refused(lambda: f.grant_maintenance_canary(permit_for(mid=OTHER_MID)), "maintenance_conflict", "maintenance_id")
    # Owner-actions may already have moved its action to `unknown`; the canary identity still matches.
    put_action(f.store, permit, UNKNOWN)
    replay = f.close_maintenance_canary(permit, "maintenance_cancelled")
    assert replay == {"closed": True, "cached": True, "maintenance_id": MID,
                      "close_reason": "maintenance_cancelled", "job_status": "failed", "launched": False}
    job = row_of(f.store, "fleet_jobs", permit["job_id"])
    assert (job["status"], job["reason_code"], job["maintenance"]["launched"]) == (
        "failed", "maintenance_cancelled", False)
    assert f.resume()["paused"] is False and f.admit_one()["job"] is None


# ---- read-only views ----------------------------------------------------------------------------------
def test_views_and_readiness_are_read_only_and_carry_no_owner_token(tmp_path):
    f, permit = granted(tmp_path)
    token = admit(f, permit)["job"]["owner_token"]
    before = snapshot(f.store)
    view = f.maintenance_permit(MID)
    readiness = f.maintenance_readiness()
    job = f.job(permit["job_id"])
    status = f.status()
    assert snapshot(f.store) == before, "reads write nothing"
    assert set(view) == set(PERMIT_VIEW_FIELDS) and view == permit_view(row_of(f.store, BUCKET_MAINTENANCE, MID))
    assert (view["state"], view["action_id"], view["job_id"], view["deadline"], view["lane"]) == (
        "admitted", permit["action_id"], permit["job_id"], permit["deadline"], "a")
    assert readiness == {"registered": True, "paused": True, "owner_paused": True, "activation_hold": False,
                         "reserving": [permit["job_id"]], "units_held": [], "open_permits": [MID]}
    assert job["status"] == "dispatching" and "owner_token" not in job and "manifest" not in job
    assert status["maintenance"] == [view]
    for output in (view, readiness, job, status):
        text = json.dumps(output)
        assert token not in text and "owner_token" not in text and "lane_ack" not in text
        assert "rationale" not in text and str(tmp_path) not in text
    assert f.maintenance_permit(OTHER_MID) is None and f.maintenance_permit(None) is None
    assert f.job("op-absent") is None and f.job(None) is None
    unregistered = Fleet(MemoryStore())
    assert unregistered.maintenance_readiness() == {
        "registered": False, "paused": False, "owner_paused": False, "activation_hold": False,
        "reserving": [], "units_held": [], "open_permits": []}
    assert unregistered.store.data == {}
    refused(lambda: check_owner_action(permit, None), "maintenance_admission_refused", "action")


def test_legacy_fleet_paths_are_unchanged_without_maintenance_rows(tmp_path):
    f = Fleet(MemoryStore(), clock=Clock())
    f.register(config(tmp_path))
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    status = f.status()
    assert set(status) == {"schema", "registered", "id", "paused", "max_parallel", "budget", "accounting_mode",
                           "lanes", "jobs", "truncated"}, "no maintenance key without a permit"
    f.pause()
    assert f.admit_one()["blocked"] == {"op-1": "paused"}
    assert f.resume()["paused"] is False
    gate = f.activation_gate("managed-fleet", "d" * 64)
    assert gate["settled"] is True and f.admit_one()["job"] is None
    assert f.release_activation_hold("d" * 64) == {"released": True}
    assert f.admit_one()["job"]["id"] == "op-1"
    assert f.maintenance_readiness()["open_permits"] == []
    assert not any(bucket == BUCKET_MAINTENANCE for bucket, _ in f.store.data), "no permit row appears"
    assert set(f.status()) == set(status)
