"""The typed one-job `forward_candidate` permit over MemoryStore (G1-04c; G1-03 ruling (g), AMD-1 D.2/D.6;
INV-FLEET-001 maintenance amendment).

Expected results come from the task spec's acceptance rules (closed kind set, the `docs/cutover/` non-shipped
prefix, the issuance gate, the unchanged Fleet control row and blockers), never from the implementation. The
backlog plan is registered through the real `FleetBacklog.register`; jobs through the real `Fleet.enqueue`.
No executor, launcher, store, host, model or provider outside this process is reached, so neither executor
transport can be called."""
import json
from copy import deepcopy

import pytest
from test_fleet import BASE, GOAL, config, manifest
from test_fleet_maintenance import (
    BUCKET_MAINTENANCE,
    MID,
    NOW,
    OTHER_MID,
    UNIT,
    Clock,
    admit,
    enqueue_canary,
    granted,
    owner_paused_fleet,
    permit_for,
    proof_for,
    put_action,
    put_row,
    refused,
    row_of,
    snapshot,
)

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import Fleet
from codex_harness.application.fleet_backlog import FleetBacklog
from codex_harness.domain.fleet import new_job, repository_identity
from codex_harness.domain.fleet_backlog import PLAN_SCHEMA
from codex_harness.domain.fleet_maintenance import (
    NON_SHIPPED_PREFIXES,
    permit_digest,
    validate_permit,
)
from codex_harness.domain.model import digest
from codex_harness.domain.operation import manifest_digest

FWD_MID = "active_generation_1:" + "f" * 64
PATHS = ["docs/cutover/FORWARD-001.md"]
ITEM_ID = "forward-001"


def forward_manifest(op_id="op-forward-001", paths=PATHS):
    return manifest(op_id, list(paths))


def forward_permit(shipped=None, mid=FWD_MID, **overrides) -> dict:
    shipped = shipped or manifest_digest(forward_manifest())
    return {"schema": "urn:zeus:fleet-maintenance-permit:1", "kind": "forward_candidate", "maintenance_id": mid,
            "evidence_ref": "sha256:" + "b" * 64, "backlog_item_id": ITEM_ID, "manifest_sha256": shipped,
            "lane": "a", "base_revision": BASE, "allowed_paths": list(PATHS),
            "deadline": "2026-09-29T12:10:00+00:00", "issuer": "owner", "approver": "conductor", **overrides}


def forward_proof(permit: dict, **overrides) -> dict:
    return {"maintenance_id": permit["maintenance_id"], "permit_sha256": digest(permit), "acknowledged": True,
            "deadline": permit["deadline"], **overrides}


def register_item(f: Fleet, tmp_path, *, item_id=ITEM_ID, lane="a", sha256=None):
    """The owner registers a backlog plan (a Git-pinned owner document) through the real registry."""
    item = {"id": item_id, "project_id": "research-improvement", "criterion_id": "verified-loop", "lane": lane,
            "manifest_path": "docs/cutover/manifests/" + item_id + ".json", "manifest_revision": "c" * 40,
            "manifest_sha256": sha256 or manifest_digest(forward_manifest()), "priority": 10, "dependencies": []}
    plan = {"schema": PLAN_SCHEMA, "plan_id": "plan-forward", "repository": repository_identity(
        str(tmp_path / ("repo-" + lane))), "enabled": True, "items": [item]}
    FleetBacklog(f.store, f).register(plan, {"revision": "c" * 40, "path": "docs/cutover/backlog.json",
                                              "sha256": "e" * 64})


def forward_fleet(tmp_path, clock=None, **overrides):
    """Owner-paused Fleet, the registered item, the granted forward permit and its queued job."""
    f = owner_paused_fleet(tmp_path, clock, **overrides)
    register_item(f, tmp_path)
    permit = forward_permit()
    f.grant_maintenance_canary(permit)
    job = f.enqueue("a", forward_manifest(), GOAL, [])["job"]
    return f, permit, job


def admit_forward(f: Fleet, permit: dict, **overrides) -> dict:
    kwargs = {"permit_sha256": digest(permit), "proof": forward_proof(permit), "budget_exhausted": False, **overrides}
    return f.admit_maintenance_canary(permit["maintenance_id"], **kwargs)


def control_bytes(store) -> str:
    return json.dumps(row_of(store, "fleet_control", "admission"), sort_keys=True)


def test_a_paused_forward_candidate_admits_only_its_exact_job_and_never_writes_the_control_row(tmp_path):
    f, permit, job = forward_fleet(tmp_path)
    other = f.enqueue("b", manifest("op-unrelated", ["docs/unrelated.md"]), GOAL, [])["job"]
    before_control = control_bytes(f.store)
    other_before = deepcopy(row_of(f.store, "fleet_jobs", other["id"]))
    admitted = admit_forward(f, permit)
    assert admitted["admitted"] is True and admitted["job"]["id"] == job["id"]
    claimed = row_of(f.store, "fleet_jobs", job["id"])
    assert claimed["status"] == "dispatching" and claimed["owner_token"]
    assert row_of(f.store, "fleet_jobs", other["id"]) == other_before, "an unrelated queued job stays untouched"
    assert row_of(f.store, "fleet_jobs", other["id"])["status"] == "queued"
    assert control_bytes(f.store) == before_control, "paused and updated_at never move"
    assert row_of(f.store, BUCKET_MAINTENANCE, FWD_MID)["state"] == "admitted"
    refused(lambda: admit_forward(f, permit), "maintenance_already_used", "state")
    assert f.maintenance_permit(FWD_MID)["job_id"] == job["id"]


def test_an_unrelated_job_enqueued_concurrently_stays_queued(tmp_path):
    f, permit, job = forward_fleet(tmp_path)
    f.enqueue("b", manifest("op-late", ["docs/late.md"]), GOAL, [])
    admit_forward(f, permit)
    statuses = {key: body["status"] for (bucket, key), body in f.store.data.items() if bucket == "fleet_jobs"}
    assert statuses == {job["id"]: "dispatching", "op-late": "queued"}


def test_a_job_that_is_not_the_exact_bound_candidate_is_refused(tmp_path):
    # Not yet enqueued, a foreign lane, another base revision, a path outside the permit, an already-claimed one.
    f = owner_paused_fleet(tmp_path)
    register_item(f, tmp_path)
    permit = forward_permit()
    f.grant_maintenance_canary(permit)
    refused(lambda: admit_forward(f, permit), "maintenance_admission_refused", "job")
    for change in ({"lane": "b"}, {"goal": {**GOAL, "base_revision": "d" * 40}}, {"status": "failed"}):
        crafted, permit, _ = forward_fleet(tmp_path)
        row = row_of(crafted.store, "fleet_jobs", "op-forward-001")
        put_row(crafted.store, "fleet_jobs", "op-forward-001", {**row, **{**change, **(
            {"goal": {**row["goal"], "base_revision": "d" * 40}} if "goal" in change else {})}})
        before = snapshot(crafted.store)
        refused(lambda crafted=crafted: admit_forward(crafted, permit), "maintenance_admission_refused", "job")
        assert snapshot(crafted.store) == before


def test_every_other_blocker_still_refuses(tmp_path):
    f, permit, job = forward_fleet(tmp_path)
    before = snapshot(f.store)
    refused(lambda: admit_forward(f, permit, budget_exhausted=True), "maintenance_admission_refused",
            "budget_exhausted")
    assert snapshot(f.store) == before

    # LABELLED crafted row: enqueue itself refuses a stale manifest and a budget grant refuses a non-idle fleet.
    stale = owner_paused_fleet(tmp_path)
    register_item(stale, tmp_path)
    permit = forward_permit()
    stale.grant_maintenance_canary(permit)
    stale.authorize_budget(8, 16, 8)
    old = forward_manifest()
    put_row(stale.store, "fleet_jobs", old["id"], new_job(old, manifest_digest(old), config(tmp_path)["lanes"][0],
                                                          GOAL, [], NOW.isoformat()))
    before = snapshot(stale.store)
    refused(lambda: admit_forward(stale, permit), "maintenance_admission_refused", "budget_stale")
    assert snapshot(stale.store) == before

    dep = owner_paused_fleet(tmp_path)
    register_item(dep, tmp_path)
    permit = forward_permit()
    dep.grant_maintenance_canary(permit)
    prerequisite = dep.enqueue("b", manifest("op-dep", ["docs/dep.md"]), GOAL, [])["job"]
    put_row(dep.store, "fleet_jobs", "op-dep", {**row_of(dep.store, "fleet_jobs", "op-dep"), "status": "failed"})
    dep.enqueue("a", forward_manifest(), GOAL, [prerequisite["id"]])
    before = snapshot(dep.store)
    refused(lambda: admit_forward(dep, permit), "maintenance_admission_refused", "dependency_failed")
    assert snapshot(dep.store) == before

    busy, permit, job = forward_fleet(tmp_path)
    other = busy.enqueue("b", manifest("op-busy", ["docs/busy.md"]), GOAL, [])["job"]
    put_row(busy.store, "fleet_jobs", other["id"], {**row_of(busy.store, "fleet_jobs", other["id"]),
                                                      "status": "dispatching", "owner_token": "t"})
    before = snapshot(busy.store)
    refused(lambda: admit_forward(busy, permit), "maintenance_debt_unsettled", "fleet")
    assert snapshot(busy.store) == before

    unit = Fleet(MemoryStore(), clock=Clock())
    unit.register(config(tmp_path))
    unit.reserve_unit(UNIT, "conductor", "b", "intent-held")
    unit.pause()
    register_item(unit, tmp_path)
    permit = forward_permit()
    unit.grant_maintenance_canary(permit)
    unit.enqueue("a", forward_manifest(), GOAL, [])
    before = snapshot(unit.store)
    refused(lambda: admit_forward(unit, permit), "maintenance_debt_unsettled", "fleet")
    assert snapshot(unit.store) == before

    for control in ({"paused": False}, {"paused": True, "activation_hold": {"target_id": "managed-fleet"}}):
        paused, permit, job = forward_fleet(tmp_path)
        row = row_of(paused.store, "fleet_control", "admission")
        put_row(paused.store, "fleet_control", "admission", {**row, **control})
        before = snapshot(paused.store)
        refused(lambda paused=paused, permit=permit: admit_forward(paused, permit), "maintenance_pause_required",
                "fleet")
        assert snapshot(paused.store) == before


def test_an_unacknowledged_or_foreign_proof_cannot_admit(tmp_path):
    f, permit, job = forward_fleet(tmp_path)
    before = snapshot(f.store)
    for proof in (forward_proof(permit, acknowledged=False), forward_proof(permit, permit_sha256="0" * 64),
                  forward_proof(permit, deadline="2026-09-29T12:11:00+00:00"), {}, None):
        refused(lambda proof=proof: admit_forward(f, permit, proof=proof), "maintenance_admission_refused", "proof")
    assert snapshot(f.store) == before


@pytest.mark.parametrize("path", ["src/x.py", "uv.lock", "docs/other.md", "../x", "/abs", "docs/cutover/../../uv.lock",
                                  "docs/cutover/*.md", "docs/cutover/", "docs/cutover", "docs/cutoverX/a.md",
                                  "docs\\cutover\\a.md", "./docs/cutover/a.md", "docs/cutover//a.md", ""])
def test_a_path_outside_the_non_shipped_prefix_is_refused_before_any_write(tmp_path, path):
    assert NON_SHIPPED_PREFIXES == ("docs/cutover/",)
    f = owner_paused_fleet(tmp_path)
    register_item(f, tmp_path)
    before = snapshot(f.store)
    for paths in ([path], PATHS + [path]):
        refused(lambda paths=paths: f.grant_maintenance_canary(forward_permit(allowed_paths=paths)),
                "path_not_non_shipped", "allowed_paths")
    assert snapshot(f.store) == before


@pytest.mark.parametrize("change, field", [
    ({"allowed_paths": []}, "allowed_paths"), ({"allowed_paths": "docs/cutover/a.md"}, "allowed_paths"),
    ({"allowed_paths": PATHS + PATHS}, "allowed_paths"),
    ({"base_revision": "a" * 39}, "base_revision"), ({"base_revision": "A" * 40}, "base_revision"),
    ({"manifest_sha256": "1" * 63}, "manifest_sha256"), ({"lane": ""}, "lane"),
    ({"backlog_item_id": ""}, "backlog_item_id"), ({"issuer": ""}, "issuer"), ({"approver": "owner"}, "approver"),
    ({"deadline": "2026-09-29T12:10:00"}, "deadline"), ({"extra": "x"}, "permit"),
    ({"evidence_ref": "b" * 64}, "evidence_ref"), ({"schema": "urn:zeus:fleet-maintenance-permit:2"}, "schema")])
def test_forward_permit_grammar_is_exact(tmp_path, change, field):
    f = owner_paused_fleet(tmp_path)
    register_item(f, tmp_path)
    before = snapshot(f.store)
    refused(lambda: f.grant_maintenance_canary(forward_permit(**change)), "maintenance_invalid", field)
    assert snapshot(f.store) == before


@pytest.mark.parametrize("kind", ["maintenance_candidate", "", "FORWARD_CANDIDATE", None, 5, ["forward_candidate"]])
def test_an_unknown_kind_is_refused_before_any_write(tmp_path, kind):
    f = owner_paused_fleet(tmp_path)
    register_item(f, tmp_path)
    before = snapshot(f.store)
    refused(lambda: f.grant_maintenance_canary(forward_permit(kind=kind)), "maintenance_invalid", "kind")
    refused(lambda: f.grant_maintenance_canary({**permit_for(), "kind": kind}), "maintenance_invalid", "kind")
    assert snapshot(f.store) == before


def test_the_backlog_item_must_be_owner_registered_under_the_bound_lane_and_digest(tmp_path):
    permit = forward_permit()
    bare = owner_paused_fleet(tmp_path)
    before = snapshot(bare.store)
    refused(lambda: bare.grant_maintenance_canary(permit), "maintenance_invalid", "backlog_item")
    assert snapshot(bare.store) == before
    for kwargs in ({"item_id": "forward-other"}, {"lane": "b"}, {"sha256": "9" * 64}):
        wrong = owner_paused_fleet(tmp_path)
        register_item(wrong, tmp_path, **kwargs)
        refused(lambda wrong=wrong: wrong.grant_maintenance_canary(permit), "maintenance_invalid", "backlog_item")
    # A registration that vanished between grant and admission (never in a real store): still refused.
    f, permit, job = forward_fleet(tmp_path)
    for key in [key for key in f.store.data if key[0] == "fleet_backlog_plans"]:
        del f.store.data[key]
    refused(lambda: admit_forward(f, permit), "maintenance_admission_refused", "backlog_item")


def test_issuance_is_refused_while_a_maintenance_generation_is_open_and_allowed_after_it_binds(tmp_path):
    clock = Clock()
    f = owner_paused_fleet(tmp_path, clock)
    register_item(f, tmp_path)
    canary = permit_for()
    f.grant_maintenance_canary(canary)  # an armed generation: its permit is granted and open
    put_action(f.store, canary)
    enqueue_canary(f, canary)
    before = snapshot(f.store)
    refused(lambda: f.grant_maintenance_canary(forward_permit()), "maintenance_open", "maintenance")
    assert snapshot(f.store) == before, "the gate never touches maintenance state"
    job = admit(f, canary)["job"]  # admitted but unsettled is still open
    refused(lambda: f.grant_maintenance_canary(forward_permit()), "maintenance_open", "maintenance")
    f.finalize(job["id"], job["owner_token"], {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0})
    f.close_maintenance_canary(canary, "maintenance_settled")  # bound and settled
    assert f.grant_maintenance_canary(forward_permit())["granted"] is True
    assert row_of(f.store, BUCKET_MAINTENANCE, MID)["state"] == "closed"

    failed = owner_paused_fleet(tmp_path, Clock())
    register_item(failed, tmp_path)
    failed.grant_maintenance_canary(canary)
    put_action(failed.store, canary)
    enqueue_canary(failed, canary)
    failed.close_maintenance_canary(canary, "maintenance_cancelled")  # a failed generation
    assert failed.grant_maintenance_canary(forward_permit())["granted"] is True


def test_a_maintenance_canary_cannot_be_granted_beside_an_open_forward_permit_and_replay_is_cached(tmp_path):
    f, permit, job = forward_fleet(tmp_path)
    assert f.grant_maintenance_canary(permit) == {"granted": True, "cached": True, "maintenance_id": FWD_MID,
                                                   "permit_sha256": digest(permit), "state": "granted"}
    refused(lambda: f.grant_maintenance_canary(forward_permit(mid=OTHER_MID)), "maintenance_conflict",
            "maintenance_id")
    refused(lambda: f.grant_maintenance_canary(permit_for()), "maintenance_conflict", "maintenance_id")
    refused(lambda: f.grant_maintenance_canary(forward_permit(base_revision="e" * 40)), "maintenance_conflict",
            "permit")


def test_grant_requires_the_owner_pause_and_a_fresh_deadline(tmp_path):
    clock = Clock()
    f = owner_paused_fleet(tmp_path, clock)
    register_item(f, tmp_path)
    clock.advance(601)
    refused(lambda: f.grant_maintenance_canary(forward_permit()), "maintenance_expired", "deadline")
    running = Fleet(MemoryStore(), clock=Clock())
    running.register(config(tmp_path))
    register_item(running, tmp_path)
    refused(lambda: running.grant_maintenance_canary(forward_permit()), "maintenance_pause_required", "fleet")


def test_expiry_fails_the_unadmitted_candidate_without_a_launch_and_response_loss_is_safe(tmp_path):
    clock = Clock()
    f, permit, job = forward_fleet(tmp_path, clock)
    other = f.enqueue("b", manifest("op-unrelated", ["docs/unrelated.md"]), GOAL, [])["job"]
    refused(lambda: f.close_maintenance_canary(permit, "maintenance_expired"), "maintenance_stale", "deadline")
    clock.advance(601)
    refused(lambda: admit_forward(f, permit), "maintenance_expired", "deadline")
    closed = f.close_maintenance_canary(permit, "maintenance_expired")
    assert closed == {"closed": True, "cached": False, "maintenance_id": FWD_MID,
                      "close_reason": "maintenance_expired", "job_status": "failed", "launched": False}
    failed = row_of(f.store, "fleet_jobs", job["id"])
    assert (failed["status"], failed["owner_token"], failed["dispatched_at"]) == ("failed", None, None)
    assert row_of(f.store, "fleet_jobs", other["id"])["status"] == "queued"
    assert f.close_maintenance_canary(permit, "maintenance_expired") == {**closed, "cached": True}
    refused(lambda: admit_forward(f, permit), "maintenance_already_used", "state")
    assert f.maintenance_readiness()["open_permits"] == []

    # The grant's response was lost and no row exists: the exact queued candidate still fails on close.
    lost_clock = Clock()
    lost = owner_paused_fleet(tmp_path, lost_clock)
    register_item(lost, tmp_path)
    lost.enqueue("a", forward_manifest(), GOAL, [])
    lost_clock.advance(601)
    assert lost.close_maintenance_canary(permit, "maintenance_expired")["job_status"] == "failed"
    # A stale candidate enqueued after the close is failed by the replay, so no resume sees it.
    late = owner_paused_fleet(tmp_path, Clock())
    register_item(late, tmp_path)
    late.grant_maintenance_canary(permit)
    late.close_maintenance_canary(permit, "maintenance_cancelled")
    late.enqueue("a", forward_manifest(), GOAL, [])
    assert late.maintenance_readiness()["open_permits"] == [FWD_MID]
    late.close_maintenance_canary(permit, "maintenance_cancelled")
    assert row_of(late.store, "fleet_jobs", "op-forward-001")["status"] == "failed"
    assert late.maintenance_readiness()["open_permits"] == []


def test_admitted_work_is_never_expired_and_a_foreign_lane_job_is_never_failed(tmp_path):
    clock = Clock()
    f, permit, job = forward_fleet(tmp_path, clock)
    claimed = admit_forward(f, permit)["job"]
    clock.advance(3600)
    for reason in ("maintenance_expired", "maintenance_cancelled", "maintenance_settled"):
        refused(lambda reason=reason: f.close_maintenance_canary(permit, reason),
                "maintenance_reconciliation_required", "job")
    f.finalize(claimed["id"], claimed["owner_token"], {"status": "accepted", "reason_code": "lead_accepted",
                                                        "exit_code": 0})
    closed = f.close_maintenance_canary(permit, "maintenance_settled")
    assert (closed["close_reason"], closed["job_status"], closed["launched"]) == ("maintenance_settled", "accepted",
                                                                                    True)
    foreign = owner_paused_fleet(tmp_path, Clock())
    register_item(foreign, tmp_path)
    foreign.grant_maintenance_canary(permit)
    foreign.enqueue("b", forward_manifest(), GOAL, [])
    refused(lambda: foreign.close_maintenance_canary(permit, "maintenance_cancelled"), "maintenance_conflict", "job")
    assert row_of(foreign.store, "fleet_jobs", "op-forward-001")["status"] == "queued"


def test_a_maintenance_permit_without_kind_validates_and_admits_exactly_as_before(tmp_path):
    permit = permit_for()
    assert "kind" not in permit and validate_permit(permit) == permit
    assert permit_digest(permit) == digest(permit), "the digest of an existing permit never moves"
    explicit = {**permit, "kind": "maintenance_canary"}
    assert validate_permit(explicit) == permit and permit_digest(explicit) == digest(permit)
    f, permit = granted(tmp_path)
    assert f.grant_maintenance_canary(explicit)["cached"] is True
    before = control_bytes(f.store)
    admitted = admit(f, permit)
    assert admitted["job"]["id"] == permit["job_id"] and admitted["job"]["status"] == "dispatching"
    assert control_bytes(f.store) == before
    assert "kind" not in f.maintenance_permit(MID) and f.maintenance_permit(MID)["job_id"] == permit["job_id"]
    assert proof_for(permit)["generation_state"] == "armed"
