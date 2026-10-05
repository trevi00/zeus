"""S11 unit CT-7: behavioural tests for contracts that no passing, row-named target test cited (DESIGN-s11 §5 R-L9, §5.4 G2).

Each test names its contract ID in its own docstring (the R-L9 citation), drives the owner through its public API and
takes its expected results from the contract text in docs/contracts.md, not from the implementation. The fixtures are
labelled synthetic data; no provider, network, PostgreSQL or Redis is touched. VERIFY-001 and RECOVERY-001 are cited
in the docstrings of two existing ported tests that already assert their stated rules (see the S11 CT-7 report).
"""

import json
from copy import deepcopy

import pytest

from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.delivery.application.host_delivery.migration import DeliveryMigration
from codex_harness.delivery.application.host_delivery.state import BUCKET_INTENTS, BUCKET_PLANS
from codex_harness.delivery.domain.host_delivery import DeliveryRefused, migration_request_id
from codex_harness.observation.adapters.collectors import ReadOnlyStore, lane_session_facts
from codex_harness.storage.adapters.memory_store import MemoryStore

CANARY = "CANARY-lane-text-must-never-reach-the-snapshot"
BASE, EVALUATOR, MERGED = "b" * 40, "1" * 40, "c" * 40


def rejected_merged_source(store):
    """LABELLED crafted records: the exact rejected, merged, host-untouched source of an evaluator migration (a
    `blocked` intent with `release_rejected` whose candidate merged), and the prepared control request for it."""
    plan = {"plan_id": "plan-old", "release_id": "release-1", "target_id": "target-1", "policy_hash": "d" * 64,
            "revision": MERGED}
    intent = {"id": "plan-old", "plan_id": "plan-old", "release_id": "release-1", "target_id": "target-1",
              "stage": "blocked", "reason_code": "release_rejected", "merged_revision": MERGED}
    with store.transaction() as tx:
        tx.put(BUCKET_PLANS, "plan-old", {"id": "plan-old", "plan": plan, "plan_sha256": "a" * 64})
        tx.put(BUCKET_INTENTS, "plan-old", intent)
    approval = {"source_release_id": "release-1", "base": BASE, "evaluator_revision": EVALUATOR,
                "evaluator_tree": "2" * 40, "patch_sha256": "3" * 64, "paths": ["tests/test_fixture.py"],
                "evidence": "sha256:" + "4" * 64, "approved_by": "conductor"}
    body = {"old_plan_id": "plan-old", "old_plan_sha256": "a" * 64, "source_release_id": "release-1",
            "source_policy_hash": "d" * 64, "candidate_revision": MERGED, "target_id": "target-1",
            "actor": "conductor", "approval": approval}
    return {**body, "migration_id": migration_request_id(body)}, intent


@pytest.mark.parametrize("case, code", [("no_resolver", "migration_pin_unavailable"),
                                        ("unreadable", "migration_pin_unavailable"),
                                        ("tree", "migration_pin_mismatch"),
                                        ("patch", "migration_pin_mismatch"),
                                        ("not_a_direct_child", "migration_pin_mismatch")])
def test_s11_contract_host_delivery_migration_pin_is_rederived_before_any_write(case, code):
    """INV-HOST-DELIVERY-MIGRATION-001: "Before any write, `stage_migration` re-derives the approved E pin through the
    lane's own repository resolver outside the transaction: no resolver or an unreadable E is
    `migration_pin_unavailable`, any difference from the approval is `migration_pin_mismatch`; both leave the source
    release, the old intent and the target untouched."

    The lane half is `DeliveryMigration.stage_migration`. The resolver is asked for the approval's own E revision and
    base; each refusal leaves every bucket of the store byte-identical (the old intent included, and no migration
    record reserves the target)."""
    store = MemoryStore()
    request, intent = rejected_merged_source(store)
    calls = []

    def resolver(revision, base):  # LABELLED fixture port: what the lane's repository would derive for E
        calls.append((revision, base))
        if case == "unreadable":
            raise OSError("fixture: repository unreadable")
        pin = {"evaluator_revision": revision, "parent": base, "base": base, "evaluator_tree": "2" * 40,
               "paths": ["tests/test_fixture.py"], "patch_sha256": "3" * 64}
        return {**pin, **{"tree": {"evaluator_tree": "0" * 40}, "patch": {"patch_sha256": "0" * 64},
                          "not_a_direct_child": {"parent": "7" * 40}}.get(case, {})}

    migration = DeliveryMigration(store, evaluator_pins=None if case == "no_resolver" else resolver)
    before = deepcopy(store.data)
    with pytest.raises(DeliveryRefused) as refused:
        migration.stage_migration(request)
    assert refused.value.reason_code == code
    assert calls == ([] if case == "no_resolver" else [(EVALUATOR, BASE)])
    assert store.data == before
    with store.transaction() as tx:
        assert tx.get(BUCKET_INTENTS, "plan-old") == intent and tx.scan("host_delivery_migrations") == []


def put(store, bucket, record):
    with store.transaction() as tx:
        tx.put(bucket, record["id"], record)


def test_s11_contract_lane_sessions_rows_are_per_lane_and_a_failed_lane_is_unavailable_by_type_only():
    """INV-LANE-SESSIONS-001: "One row per lane task or decision, under its lane, so equal ids in two lanes stay
    distinct" (agent, status, phase, generation, attempt, `lease_until`), read from each REGISTERED lane's own store;
    "A lane whose read fails is `unavailable` with its error TYPE only, never an empty ok lane"; an unregistered Fleet
    is `registered: false` with no lane; nothing is written and no prompt, objective or raw error is emitted."""
    control, lane_a, lane_b = MemoryStore(), MemoryStore(), MemoryStore()
    FleetRegistry(control).register({
        "schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2, "budget": {"per_host": 4, "total": 8},
        "lanes": [{"id": lane, "team": team, "repository": f"/fixture/{CANARY}-repo-{lane}", "schema": "lane_" + lane,
                   "redis_namespace": "fleet-" + lane, "runtime": f"/fixture/{CANARY}-rt-{lane}"}
                  for lane, team in (("a", "alpha"), ("b", "beta"), ("c", "gamma"))]})
    put(lane_a, "tasks", {"id": "task-1", "agent": "implementer", "status": "succeeded", "phase": "implement",
                          "generation": 2, "attempt": 1, "lease_until": "2026-09-27T20:40:00+00:00",
                          "created_at": "2026-09-27T20:00:00+00:00", "error": CANARY,
                          "message": {"what": {"details": {"plan": {"objective": CANARY}}}}})
    put(lane_a, "decisions_pending", {"id": "dec-1", "actor": "lead", "status": "succeeded", "phase": "lead_review",
                                      "attempt": 1, "created_at": "2026-09-27T20:21:00+00:00"})
    put(lane_b, "tasks", {"id": "task-1", "agent": "reviewer", "status": "running", "generation": 1, "attempt": 3,
                          "lease_until": "2026-09-27T21:00:00+00:00", "created_at": "2026-09-27T20:50:00+00:00"})
    stores = {"a": lane_a, "b": lane_b}

    def resolve(lane):  # an INJECTED outage for lane `c` only
        if lane["id"] == "c":
            raise RuntimeError("injected outage " + CANARY)
        return ReadOnlyStore(stores[lane["id"]])

    def everything():
        return {name: deepcopy(store.data) for name, store in {"control": control, "a": lane_a, "b": lane_b}.items()}

    before = everything()
    facts = lane_session_facts(control, resolve, registered=lambda store: FleetRegistry(store).registered())
    assert everything() == before  # read-only: no store changed
    assert facts["registered"] is True
    ok_a, ok_b, down = facts["lanes"]
    assert [(lane["lane"], lane["status"]) for lane in (ok_a, ok_b)] == [("a", "ok"), ("b", "ok")]
    rows_a = {r["id"]: r for r in ok_a["executions"]}
    assert set(rows_a) == {"task-1", "dec-1"}
    assert [r["id"] for r in ok_b["executions"]] == ["task-1"]  # the equal id is a distinct row under its own lane
    task_a, task_b = rows_a["task-1"], ok_b["executions"][0]
    assert (task_a["agent"], task_a["status"], task_a["phase"], task_a["generation"], task_a["attempt"]) == (
        "implementer", "succeeded", "implement", 2, 1)
    assert task_a["lease_until"] == "2026-09-27T20:40:00+00:00"
    assert (task_b["agent"], task_b["status"], task_b["generation"], task_b["attempt"]) == ("reviewer", "running", 1, 3)
    assert task_b["lease_until"] == "2026-09-27T21:00:00+00:00"
    assert (down["lane"], down["status"], down["error"]) == ("c", "unavailable", "RuntimeError")
    assert "executions" not in down  # never an empty ok lane
    assert facts["coverage"]["lanes_registered"] == 3 and facts["coverage"]["lanes_observed"] == 2
    assert facts["coverage"]["lanes_unavailable"] == 1 and facts["coverage"]["uninstrumented"]
    assert CANARY not in json.dumps(facts)
    empty = lane_session_facts(MemoryStore(), resolve, registered=lambda store: FleetRegistry(store).registered())
    assert (empty["registered"], empty["lanes"], empty["coverage"]["lanes_registered"]) == (False, [], 0)
