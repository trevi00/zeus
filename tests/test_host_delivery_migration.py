"""The lane half of an evaluator migration of a rejected, merged delivery (INV-HOST-DELIVERY-MIGRATION-001).

What is real: the `Releases` owner (including `request_evaluator_migration`), the `ReleaseQueue`, the
`HostDelivery` owner and its store transactions (the in-memory `SerialStore`, which refuses a nested
transaction, and an isolated PostgreSQL schema when `HARNESS_INTEGRATION=1`; without it that parameter
SKIPS and is not evidence). What is a labelled crafted write: the ONE halted H1-like intent (the shape
`_verify` records for an executed failed check after the source had already merged), written through
the real queue API plus one intent put. No production service, database, provider or model is touched.
"""
import threading
from copy import deepcopy

import pytest
from test_host_delivery import SerialStore, build, pin, plan_document, targets_document

from codex_harness.application.host_delivery import (
    BUCKET_INTENTS,
    BUCKET_MIGRATIONS,
    BUCKET_PLANS,
    HostDelivery,
)
from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.releases import Releases
from codex_harness.domain.host_delivery import (
    BLOCKED,
    MERGED,
    VERIFYING,
    WITHDRAWN,
    DeliveryRefused,
    migration_request_id,
    new_intent,
    plan_digest,
    validate_plan,
)
from codex_harness.domain.model import digest


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def store(request):
    if request.param == "memory":
        return SerialStore()
    return request.getfixturevalue("isolated_pgstore")


def rejected_merged(tmp_path, store, **fields):
    """A reviewed release REJECTED by an executed failed check after its candidate merged: the H1 shape."""
    system = build(tmp_path, store=store, verified=False)
    release, plan, delivery = system["release"], system["plan"], system["delivery"]
    queue = ReleaseQueue(store)
    queue.enqueue(release["id"], "host delivery plan " + plan["plan_id"])
    claim = queue.claim(now=delivery._now(), eligible=lambda row: row["id"] == release["id"])
    Releases(store, system["org"]).verify(release["id"], release["candidate"]["revision"], release["policy_hash"],
                                          {"tests": {"passed": False, "evidence": "fixture-failed-check"}})
    queue.finish(claim, {"status": "blocked", "reason": "release_rejected"}, delivery._now())
    now = system["clock"]()
    halted = {**new_intent(validate_plan(plan), plan_digest(validate_plan(plan)), now),
              "stage": BLOCKED, "previous_stage": VERIFYING, "outcome": "blocked", "reason_code": "release_rejected",
              "after_verification": MERGED, "attempts": 1, "head": release["candidate"]["revision"],
              "pr_number": 7, "pr_url": "https://example.invalid/pr/7",
              "merged_revision": release["candidate"]["revision"],
              "verification": {"attempts": [{"attempt_id": "a" * 32, "cleanup": {"state": "confirmed"}}]},
              "updated_at": now, **fields}
    with store.transaction() as tx:
        tx.put(BUCKET_INTENTS, plan["plan_id"], halted)
    system["halted"] = halted
    system["request"] = request_for(system)
    return system


def request_for(system, **overrides):
    release, plan = system["release"], system["plan"]
    approval = {"source_release_id": release["id"], "base": release["candidate"]["base"],
                "evaluator_revision": "1" * 40, "evaluator_tree": "2" * 40, "patch_sha256": "3" * 64,
                "paths": ["tests/test_fixture.py"], "evidence": "sha256:" + "4" * 64, "approved_by": "conductor"}
    body = {"old_plan_id": plan["plan_id"], "old_plan_sha256": plan_digest(validate_plan(plan)),
            "source_release_id": release["id"], "source_policy_hash": release["policy_hash"],
            "candidate_revision": release["candidate"]["revision"], "target_id": plan["target_id"],
            "actor": "conductor", "approval": approval, **overrides}
    return {**body, "migration_id": migration_request_id(body)}


def successor_plan(system, staged, **overrides):
    with system["store"].transaction() as tx:
        successor = tx.get("releases", staged["successor_release_id"])
    return plan_document(successor, plan_id="delivery-plan-migrated", **overrides)


def ack_for(staged_request, registered, **overrides):
    return {"control_action_id": "action-1", "plan_id": registered["plan_id"],
            "plan_sha256": registered["plan_sha256"], "request_sha256": digest(staged_request),
            "canary_request_id": "canary-1", "lineage_sha256": "5" * 64, **overrides}


def snapshot(store):
    with store.transaction() as tx:
        return {bucket: sorted(tx.scan(bucket), key=lambda row: str(row.get("id")))
                for bucket in (BUCKET_INTENTS, BUCKET_PLANS, BUCKET_MIGRATIONS, "release_queue", "releases",
                               "deployment_locks")}


def row(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def refused(code, call, *args):
    with pytest.raises(DeliveryRefused) as caught:
        call(*args)
    assert caught.value.reason_code == code
    return caught.value


def test_stage_register_finalize_then_tick_runs_only_after_the_acknowledgement(tmp_path, store):
    system = rejected_merged(tmp_path, store)
    delivery, request, plan = system["delivery"], system["request"], system["plan"]
    source_before = row(store, "releases", system["release"]["id"])
    staged = delivery.stage_migration(request)
    assert staged["state"] == "staged" and staged["cached"] is False
    # The source release, its failed checks and the old attempts are unchanged; only the truthful
    # terminalization of the old intent is written, with the original halt copied.
    assert row(store, "releases", system["release"]["id"]) == source_before
    old = row(store, BUCKET_INTENTS, plan["plan_id"])
    assert old["stage"] == WITHDRAWN and old["reason_code"] == "release_rejected_superseded"
    assert old["main_effect"] == "merged" and old["previous_stage"] == BLOCKED
    assert old["verification"] == system["halted"]["verification"]
    written = {"stage", "previous_stage", "outcome", "reason_code", "error_type", "stage_deadline", "main_effect",
               "supersession", "updated_at"}
    assert {k: v for k, v in old.items() if k not in written} == {
        k: v for k, v in system["halted"].items() if k not in written}
    assert old["supersession"] == {"migration_id": request["migration_id"],
                                   "successor_release_id": staged["successor_release_id"],
                                   "original_halt": {k: system["halted"].get(k) for k in (
                                       "stage", "previous_stage", "reason_code", "outcome", "attempts",
                                       "error_type", "updated_at")}}
    record = row(store, BUCKET_MIGRATIONS, plan["plan_id"])
    assert set(record) == {"id", "migration_id", "request", "request_sha256", "state", "successor_release_id",
                           "source_release_id", "target_id", "plan_id", "plan_sha256", "ack", "at"}
    successor = row(store, "releases", staged["successor_release_id"])
    assert successor["status"] == "reviewed" and successor["checks"] == {}
    # Nothing runnable exists for the successor: no queue row, and a tick does nothing.
    assert row(store, "release_queue", staged["successor_release_id"]) is None
    assert delivery.tick()["plan_id"] is None

    document = successor_plan(system, staged)
    registered = delivery.register_migration_plan(document, pin(), request["migration_id"])
    assert registered["state"] == "registered" and registered["plan_id"] == "delivery-plan-migrated"
    held = row(store, BUCKET_INTENTS, "delivery-plan-migrated")
    assert held["stage"] == VERIFYING and held["after_verification"] == MERGED
    assert held["held"] == "migration_unacknowledged"
    assert held["merged_revision"] == system["halted"]["merged_revision"]
    assert held["migration"] == {"migration_id": request["migration_id"], "predecessor_plan_id": plan["plan_id"],
                                 "source_release_id": system["release"]["id"]}
    tick = delivery.tick()
    assert tick["plan_id"] is None and tick["blocked"]["delivery-plan-migrated"] == "migration_unacknowledged"
    assert tick["blocked"][plan["plan_id"]] == WITHDRAWN
    assert {view["plan_id"] for view in delivery.status()["deliveries"]} == {plan["plan_id"], "delivery-plan-migrated"}
    refused("withdraw_migration_held", delivery.withdraw, "delivery-plan-migrated", registered["plan_sha256"],
            "reviewed_base_moved", "sha256:" + "ab" * 32)
    # A restarted controller over the same durable store holds it too.
    restarted = HostDelivery(store, system["org"], github=system["github"], clock=system["clock"], enabled=True)
    assert restarted.tick()["blocked"]["delivery-plan-migrated"] == "migration_unacknowledged"
    assert row(store, "release_queue", staged["successor_release_id"]) is None

    ack = ack_for(request, registered)
    final = delivery.finalize_migration(request["migration_id"], ack)
    assert final["state"] == "active" and final["acknowledged"] is True
    assert row(store, BUCKET_INTENTS, "delivery-plan-migrated")["held"] is None
    assert row(store, "release_queue", staged["successor_release_id"])["status"] == "queued"
    after = restarted.tick()
    # Runnable now: the ordinary controller selects and claims it (no verifier port is wired here).
    assert after["plan_id"] == "delivery-plan-migrated" and after["stage"] == VERIFYING
    assert after["reason_code"] == "verifier_unavailable"


def test_every_step_replays_cached_and_refuses_a_conflicting_one(tmp_path, store):
    system = rejected_merged(tmp_path, store)
    delivery, request = system["delivery"], system["request"]
    staged = delivery.stage_migration(request)
    before = snapshot(store)
    assert delivery.stage_migration(deepcopy(request))["cached"] is True
    assert snapshot(store) == before
    other = request_for(system, approval={**request["approval"], "evaluator_revision": "6" * 40})
    refused("migration_conflict", delivery.stage_migration, other)

    document = successor_plan(system, staged)
    registered = delivery.register_migration_plan(document, pin(), request["migration_id"])
    before = snapshot(store)
    assert delivery.register_migration_plan(document, pin(), request["migration_id"])["cached"] is True
    assert snapshot(store) == before
    refused("migration_conflict", delivery.register_migration_plan,
            successor_plan(system, staged, ci_timeout=301), pin(), request["migration_id"])
    refused("migration_ack_mismatch", delivery.finalize_migration, request["migration_id"],
            ack_for(request, registered, plan_sha256="0" * 64))
    assert snapshot(store) == before

    ack = ack_for(request, registered)
    delivery.finalize_migration(request["migration_id"], ack)
    before = snapshot(store)
    assert delivery.finalize_migration(request["migration_id"], dict(ack))["cached"] is True
    assert snapshot(store) == before
    refused("migration_conflict", delivery.finalize_migration, request["migration_id"],
            ack_for(request, registered, canary_request_id="canary-2"))
    refused("migration_unknown", delivery.finalize_migration, "f" * 64, ack)
    assert snapshot(store) == before


@pytest.mark.parametrize("fields, code", [
    ({"reason_code": "release_not_verified"}, "migration_not_applicable"),
    ({"stage": VERIFYING}, "migration_not_applicable"),
    ({"descriptor_sha256": "d" * 64}, "migration_host_touched"),
    ({"merged_revision": None}, "migration_candidate_mismatch"),
    ({"verification": {"attempts": [{"attempt_id": "b" * 32, "cleanup": None}]}}, "migration_attempt_debt"),
])
def test_a_source_that_is_not_the_exact_rejected_merged_shape_is_refused_without_a_write(
        tmp_path, store, fields, code):
    system = rejected_merged(tmp_path, store, **fields)
    before = snapshot(store)
    refused(code, system["delivery"].stage_migration, system["request"])
    assert snapshot(store) == before


def test_a_stale_digest_wrong_candidate_or_forged_identity_is_refused_without_a_write(tmp_path, store):
    system = rejected_merged(tmp_path, store)
    delivery = system["delivery"]
    before = snapshot(store)
    refused("migration_plan_mismatch", delivery.stage_migration, request_for(system, old_plan_sha256="0" * 64))
    refused("migration_candidate_mismatch", delivery.stage_migration,
            request_for(system, candidate_revision="7" * 40))
    refused("migration_request_invalid", delivery.stage_migration,
            {**system["request"], "migration_id": "0" * 64})
    refused("migration_release_refused", delivery.stage_migration,
            request_for(system, approval={**system["request"]["approval"], "paths": ["src/x.py"]}))
    assert snapshot(store) == before


def test_a_live_controller_lease_or_running_queue_row_refuses_without_a_write(tmp_path, store):
    system = rejected_merged(tmp_path, store)
    delivery, release_id = system["delivery"], system["release"]["id"]
    with store.transaction() as tx:
        queued = tx.get("release_queue", release_id)
        tx.put("release_queue", release_id, {**queued, "status": "running"})
    before = snapshot(store)
    refused("migration_controller_running", delivery.stage_migration, system["request"])
    assert snapshot(store) == before
    with store.transaction() as tx:
        tx.put("release_queue", release_id, queued)
        tx.put("deployment_locks", "controller", {"owner": "other", "lease_until": "2999-01-01T00:00:00+00:00"})
    before = snapshot(store)
    refused("migration_controller_running", delivery.stage_migration, system["request"])
    assert snapshot(store) == before


def test_the_reserved_target_admits_no_other_plan_until_active_and_another_target_is_free(tmp_path, store):
    system = rejected_merged(tmp_path, store)
    delivery, request, org = system["delivery"], system["request"], system["org"]
    delivery.register_targets({**targets_document(tmp_path), "targets": [
        *targets_document(tmp_path)["targets"], *targets_document(tmp_path, target_id="other-service")["targets"]]})
    staged = delivery.stage_migration(request)
    competitor = Releases(store, org).propose({**system["release"]["candidate"], "revision": "8" * 40},
                                              {"checks": ["tests"], "evaluator": "fixture-incumbent-policy"})
    same = plan_document(competitor, plan_id="delivery-plan-h2")
    elsewhere = plan_document(competitor, plan_id="delivery-plan-other", target_id="other-service")
    refused("target_reserved_by_migration", delivery.register, same, pin())
    assert delivery.register(elsewhere, pin())["cached"] is False
    # A plan registered before the reservation is skipped by selection with the explicit reason.
    with store.transaction() as tx:
        tx.put(BUCKET_PLANS, "delivery-plan-h2", {"id": "delivery-plan-h2", "plan_id": "delivery-plan-h2",
                                                  "plan": validate_plan(same), "plan_sha256": plan_digest(
                                                      validate_plan(same)), "pin": pin(),
                                                  "target_id": "canary-service"})
    blocked = delivery.tick()["blocked"]
    assert blocked["delivery-plan-h2"] == "target_reserved_by_migration"
    assert "delivery-plan-other" not in blocked or blocked["delivery-plan-other"] != "target_reserved_by_migration"
    # Registered-but-held still reserves; after finalize the reservation lifts.
    registered = delivery.register_migration_plan(successor_plan(system, staged), pin(), request["migration_id"])
    assert delivery.tick()["blocked"]["delivery-plan-h2"] == "target_reserved_by_migration"
    delivery.finalize_migration(request["migration_id"], ack_for(request, registered))
    assert delivery.tick()["blocked"].get("delivery-plan-h2") != "target_reserved_by_migration"


def test_a_target_with_another_unfinished_plan_is_not_staged(tmp_path, store):
    system = rejected_merged(tmp_path, store)
    competitor = Releases(store, system["org"]).propose({**system["release"]["candidate"], "revision": "8" * 40},
                                                        {"checks": ["tests"], "evaluator": "fixture-incumbent-policy"})
    system["delivery"].register(plan_document(competitor, plan_id="delivery-plan-h2"), pin())
    before = snapshot(store)
    refused("migration_target_busy", system["delivery"].stage_migration, system["request"])
    assert snapshot(store) == before


def test_a_crash_between_steps_leaves_a_named_pending_handoff_never_a_free_target(tmp_path, store):
    system = rejected_merged(tmp_path, store)
    delivery, request = system["delivery"], system["request"]
    staged = delivery.stage_migration(request)
    restarted = HostDelivery(store, system["org"], github=system["github"], clock=system["clock"], enabled=True)
    assert row(store, BUCKET_MIGRATIONS, system["plan"]["plan_id"])["state"] == "staged"
    assert restarted.tick()["plan_id"] is None
    assert HostDelivery._reservation_in is not None
    with store.transaction() as tx:
        assert HostDelivery._reservation_in(tx, "canary-service")["state"] == "staged"
    # A plan other than the successor, or a register before staging, is refused.
    refused("migration_plan_mismatch", restarted.register_migration_plan,
            plan_document(system["release"], plan_id="delivery-plan-x"), pin(), request["migration_id"])
    refused("migration_not_registered", restarted.finalize_migration, request["migration_id"],
            {"control_action_id": "a", "plan_id": "b", "plan_sha256": "c", "request_sha256": "d",
             "canary_request_id": "e", "lineage_sha256": "f"})
    restarted.register_migration_plan(successor_plan(system, staged), pin(), request["migration_id"])
    again = HostDelivery(store, system["org"], github=system["github"], clock=system["clock"], enabled=True)
    assert row(store, BUCKET_MIGRATIONS, system["plan"]["plan_id"])["state"] == "registered"
    result = again.tick()
    assert result["plan_id"] is None and result["blocked"]["delivery-plan-migrated"] == "migration_unacknowledged"
    assert row(store, "release_queue", staged["successor_release_id"]) is None


@pytest.mark.integration
def test_concurrent_same_source_requests_stage_exactly_one_migration(tmp_path, isolated_pgstore):
    system = rejected_merged(tmp_path, isolated_pgstore)
    request = system["request"]
    other = request_for(system, approval={**request["approval"], "evaluator_revision": "6" * 40})
    results, gate = [], threading.Barrier(4)

    def run(candidate):
        gate.wait()
        try:
            results.append(system["delivery"].stage_migration(candidate))
        except DeliveryRefused as exc:
            results.append(exc.reason_code)

    threads = [threading.Thread(target=run, args=(r,)) for r in (request, request, other, other)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    fresh = [r for r in results if isinstance(r, dict) and not r["cached"]]
    assert len(results) == 4 and len(fresh) == 1
    assert all(isinstance(r, dict) or r == "migration_conflict" for r in results)
    with isolated_pgstore.transaction() as tx:
        assert len(tx.scan(BUCKET_MIGRATIONS)) == 1
        assert [r["id"] for r in tx.scan("releases")
                if r.get("reverify_of") == system["release"]["id"]] == [fresh[0]["successor_release_id"]]


@pytest.mark.integration
def test_a_competing_plan_and_the_migration_admit_exactly_one_owner_of_the_target(tmp_path, isolated_pgstore):
    system = rejected_merged(tmp_path, isolated_pgstore)
    competitor = Releases(isolated_pgstore, system["org"]).propose(
        {**system["release"]["candidate"], "revision": "8" * 40},
        {"checks": ["tests"], "evaluator": "fixture-incumbent-policy"})
    results, gate = {}, threading.Barrier(2)

    def attempt(name, call):
        gate.wait()
        try:
            results[name] = call()
        except DeliveryRefused as exc:
            results[name] = exc.reason_code

    threads = [threading.Thread(target=attempt, args=("stage", lambda: system["delivery"].stage_migration(
                   system["request"]))),
               threading.Thread(target=attempt, args=("h2", lambda: system["delivery"].register(
                   plan_document(competitor, plan_id="delivery-plan-h2"), pin())))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    if isinstance(results["stage"], dict):
        assert results["h2"] == "target_reserved_by_migration"
    else:
        assert results["stage"] == "migration_target_busy" and results["h2"]["registered"] is True
