"""Approved backlog plans, durable intents, portfolio linkage and Fleet admission (INV-FLEET-BACKLOG-001).

Every loader, launcher, portfolio outage and injected failure here is a labelled fixture: no git,
no provider, no model call and no real PostgreSQL is reached from this module except in the one
explicitly integration-gated test at the end, which skips without `HARNESS_INTEGRATION=1`.

The store used almost everywhere is `SerialStore`: a MemoryStore that REFUSES a transaction opened
while another one is already open. The real `PostgresStore.transaction` connects and takes
`pg_advisory_xact_lock` per transaction, so a nested call would block until `lock_timeout`; this
fixture turns that latent deadlock into an immediate failure in every test below - including the
`Portfolio.bind` and `Fleet.enqueue` calls, which open their own transactions.
"""
import hashlib
import json
import logging
import threading
from contextlib import contextmanager
from copy import deepcopy

import pytest

from codex_harness.adapters.observation_spool import MemorySpool
from codex_harness.adapters.portfolio import packaged_definitions
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import BUCKET_JOBS, Fleet, FleetRunner
from codex_harness.application.fleet_backlog import BUCKET_INTENTS, BUCKET_PLANS, FleetBacklog
from codex_harness.application.observations import MemoryDirectory, Observer
from codex_harness.application.portfolio import BUCKET_BINDINGS, Portfolio
from codex_harness.domain.fleet import binding, repository_identity
from codex_harness.domain.fleet_backlog import (
    MAX_ATTEMPTS,
    MAX_DEFERRALS,
    PLAN_SCHEMA,
    BacklogRefused,
    expected_binding,
    new_intent,
    validate_plan,
)
from codex_harness.domain.observation import new_process_run_id
from codex_harness.domain.operation import validate_manifest

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
PLAN_REVISION = "c" * 40
ITEM_REVISION = "d" * 40
PLAN_PATH = "docs/zeus/backlog.json"
ACCEPTED = {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0,
            "calls": {"reserved": 2, "settled": 2}}
FAILED = {"status": "failed", "reason_code": "child_refused", "exit_code": 1}
NOW = "2026-09-22T00:00:00+00:00"


class SerialStore:
    """MemoryStore with the real control-plane contract made observable: opening a transaction
    inside another one is the nested case that deadlocks on the PostgreSQL advisory lock."""

    def __init__(self):
        self.inner, self.depth, self.transactions = MemoryStore(), 0, 0

    @property
    def data(self):
        return self.inner.data

    @contextmanager
    def transaction(self):
        if self.depth:
            raise AssertionError("a nested store transaction deadlocks the PG advisory lock")
        self.depth, self.transactions = self.depth + 1, self.transactions + 1
        try:
            with self.inner.transaction() as tx:
                yield tx
        finally:
            self.depth -= 1


def config(tmp_path, *, shared_repository=False, **overrides):
    """Two lanes. `shared_repository` puts both lanes on ONE repository, which the fleet grammar
    allows and which makes `lane` the only field that separates two otherwise identical jobs."""
    second = "repo-a" if shared_repository else "repo-b"
    lanes = [{"id": "a", "team": "alpha", "repository": str(tmp_path / "repo-a"), "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": str(tmp_path / "rt-a")},
             {"id": "b", "team": "beta", "repository": str(tmp_path / second), "schema": "lane_b",
              "redis_namespace": "fleet-b", "runtime": str(tmp_path / "rt-b")}]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
            "budget": {"per_host": 4, "total": 8}, "lanes": lanes, **overrides}


def manifest(op_id, paths):
    return validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + op_id, "rationale": CANARY},
        "plan": {"objective": CANARY, "acceptance_criteria": ["ok"], "allowed_paths": paths},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}},
        packaged_policy())


GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}


def item(item_id, *, lane="a", priority=10, dependencies=(), project="research-improvement",
         criterion="verified-loop", revision=ITEM_REVISION, sha256=None):
    return {"id": item_id, "project_id": project, "criterion_id": criterion, "lane": lane,
            "manifest_path": "docs/zeus/manifests/" + item_id + ".json",
            "manifest_revision": revision,
            "manifest_sha256": sha256 or hashlib.sha256(item_id.encode()).hexdigest(),
            "priority": priority, "dependencies": list(dependencies)}


def plan(tmp_path, items, *, enabled=True, plan_id="plan-1", lane="a"):
    return {"schema": PLAN_SCHEMA, "plan_id": plan_id,
            "repository": repository_identity(str(tmp_path / ("repo-" + lane))),
            "enabled": enabled, "items": items}


def pin(revision=PLAN_REVISION, path=PLAN_PATH, sha256="e" * 64):
    return {"revision": revision, "path": path, "sha256": sha256}


def lane_identity(tmp_path, lane, shared_repository=False):
    directory = "repo-a" if lane == "a" or shared_repository else "repo-b"
    return repository_identity(str(tmp_path / directory))


def work(item_id, repository):
    """The manifest, goal binding and lane repository identity a real git-backed loader returns."""
    return {"manifest": manifest("op-" + item_id, ["docs/" + item_id + ".md"]), "goal": dict(GOAL),
            "repository": repository}


def loader_for(tmp_path, refusals=None, outages=None, overrides=None, shared_repository=False):
    """A labelled fixture standing in for the adapter's git-backed loader; it reads nothing."""
    def load(item_document):
        item_id = item_document["id"]
        if refusals and item_id in refusals:
            raise BacklogRefused(refusals[item_id], "items[].manifest_sha256")
        if outages and item_id in outages:
            raise RuntimeError("injected git outage (fixture)")
        if overrides and item_id in overrides:
            return overrides[item_id]
        return work(item_id, lane_identity(tmp_path, item_document["lane"], shared_repository))
    return load


def backlog(tmp_path, items, *, store=None, portfolio=True, observer=None, shared_repository=False,
            **plan_overrides):
    store = SerialStore() if store is None else store
    fleet = Fleet(store)
    fleet.register(config(tmp_path, shared_repository=shared_repository))
    owner = Portfolio(store, packaged_definitions()) if portfolio is True else portfolio
    coordinator = FleetBacklog(store, fleet, portfolio=owner, observer=observer)
    coordinator.register(plan(tmp_path, items, **plan_overrides), pin())
    return coordinator, fleet, store


def settle(fleet, job_id, outcome):
    """Run the existing admission and finalization for one job; no runner, no process."""
    decision = fleet.admit_one()
    assert decision["job"]["id"] == job_id, decision
    return fleet.finalize(job_id, decision["job"]["owner_token"], outcome)


def observer_for(store):
    return Observer(store, MemorySpool(new_process_run_id()), component="unit", directory=MemoryDirectory())


def intent_of(store, item_id, plan_id="plan-1"):
    return store.data[BUCKET_INTENTS, plan_id + ":" + item_id]


# ----- plan grammar -------------------------------------------------------------------------
def test_plan_validation_refuses_unknown_fields_duplicates_cycles_and_foreign_pins(tmp_path):
    good = plan(tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])])
    canonical = validate_plan(good)
    assert canonical["items"][0] == dict(sorted(good["items"][0].items()))
    assert canonical["plan_id"] == "plan-1" and canonical["enabled"] is True
    bad = [
        ({"schema": "urn:zeus:fleet-backlog:2"}, "plan_schema"),
        ({"version": 1}, "plan_fields"),
        ({"plan_id": "bad id"}, "plan_invalid"),
        ({"repository": "/abs/repo-a"}, "plan_invalid"),
        ({"enabled": "yes"}, "plan_invalid"),
        ({"items": []}, "plan_invalid"),
        ({"items": [item("one"), item("one")]}, "plan_duplicate"),
        ({"items": [item("one", dependencies=["one"])]}, "dependency_self"),
        ({"items": [item("one", dependencies=["absent"])]}, "dependency_unknown"),
        ({"items": [item("one", dependencies=["two"]), item("two", dependencies=["one"])]}, "dependency_cycle"),
        ({"items": [{**item("one"), "manifest_path": "../outside/x.json"}]}, "item_invalid"),
        ({"items": [{**item("one"), "manifest_path": "docs/x.md"}]}, "item_invalid"),
        ({"items": [{**item("one"), "manifest_revision": "short"}]}, "item_invalid"),
        ({"items": [{**item("one"), "manifest_sha256": "z" * 64}]}, "item_invalid"),
        ({"items": [{**item("one"), "priority": True}]}, "item_invalid"),
        ({"items": [{**item("one"), "priority": -1}]}, "item_invalid"),
        ({"items": [{**item("one"), "lane": "bad lane"}]}, "item_invalid"),
        # An executable-looking extra key is refused exactly like any other unknown field.
        ({"items": [{**item("one"), "command": "rm -rf /"}]}, "plan_fields"),
    ]
    for overrides, code in bad:
        with pytest.raises(BacklogRefused, match=code) as info:
            validate_plan({**good, **overrides})
        assert CANARY not in str(info.value) and str(tmp_path) not in str(info.value)
    assert validate_plan(plan(tmp_path, [item("one")], enabled=False))["enabled"] is False


# ----- normal successor ---------------------------------------------------------------------
def test_a_valid_plan_admits_one_eligible_item_into_the_existing_fleet_exactly_once(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])])
    load = loader_for(tmp_path)
    first = coordinator.tick("plan-1", load)
    assert first["outcome"] == "enqueued" and first["item_id"] == "one" and first["job_id"] == "op-one"
    assert first["cached"] is False and first["job_status"] == "queued" and first["lane"] == "a"
    assert first["linked"] is True and first["link_state"] == "linked"
    assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"]
    # The existing portfolio owner recorded the goal binding of the admitted job; the backlog wrote
    # no acceptance and no criterion verdict of its own.
    assert store.data[BUCKET_BINDINGS, "op-one"]["criterion_id"] == "verified-loop"
    assert store.data[BUCKET_BINDINGS, "op-one"]["recorded_by"] == "owner"
    # The successor is not invented while its dependency is still running.
    waiting = coordinator.tick("plan-1", load)
    assert waiting["outcome"] == "blocked" and waiting["blocked"] == {"two": "dependency_waiting"}
    assert store.data[BUCKET_JOBS, "op-one"]["status"] == "queued"
    settle(fleet, "op-one", ACCEPTED)
    # The next item is selected without any manual enqueue and carries the predeclared dependency.
    second = coordinator.tick("plan-1", load)
    assert second["outcome"] == "enqueued" and second["item_id"] == "two" and second["job_id"] == "op-two"
    assert store.data[BUCKET_JOBS, "op-two"]["dependencies"] == ["op-one"]
    assert coordinator.tick("plan-1", load)["outcome"] == "backlog_exhausted"
    assert sorted(k[1] for k in store.data if k[0] == BUCKET_INTENTS) == ["plan-1:one", "plan-1:two"]
    assert CANARY not in json.dumps(second) and str(tmp_path) not in json.dumps(second)


def test_the_recorded_identity_is_the_complete_binding_of_the_authoritative_job_row(tmp_path):
    """R1: the deciding check that the recorded expectation and `domain.fleet.binding` agree field
    for field - lane, repository, manifest digest, dependencies and every bound goal field."""
    coordinator, fleet, store = backlog(tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])])
    coordinator.tick("plan-1", loader_for(tmp_path))
    settle(fleet, "op-one", ACCEPTED)
    coordinator.tick("plan-1", loader_for(tmp_path))
    for item_id, job_id in (("one", "op-one"), ("two", "op-two")):
        recorded = intent_of(store, item_id)["job_binding"]
        assert recorded == binding(store.data[BUCKET_JOBS, job_id])
        assert set(recorded) == {"lane", "manifest_sha256", "repository", "dependencies", "goal"}
    assert intent_of(store, "two")["job_binding"]["dependencies"] == ["op-one"]
    # The projection Fleet returns to a caller does NOT carry the repository, so it is never the
    # thing compared: the intent holds the whole identity.
    assert "repository" not in fleet.status()["jobs"][0]


def test_an_exhausted_backlog_is_idle_and_writes_nothing_on_a_repeated_poll(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one")])
    coordinator.tick("plan-1", loader_for(tmp_path))
    before = deepcopy(store.data)
    for _ in range(3):
        assert coordinator.tick("plan-1", loader_for(tmp_path))["outcome"] == "backlog_exhausted"
    assert store.data == before, "an idle poll is not an event and moves no timestamp"


# ----- one durable identity -------------------------------------------------------------------
def test_a_lost_response_and_a_restart_keep_exactly_one_durable_identity(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one")])
    load = loader_for(tmp_path)
    assert coordinator.tick("plan-1", load)["job_id"] == "op-one"
    intent_key = (BUCKET_INTENTS, "plan-1:one")
    settled = deepcopy(store.data[intent_key])
    assert settled["state"] == "enqueued" and settled["job_id"] == "op-one"

    # Response loss: the job exists, the confirmation never arrived.
    store.data[intent_key] = {**settled, "state": "intended", "enqueued_at": None}
    replay = coordinator.tick("plan-1", load)
    assert replay["outcome"] == "backlog_exhausted", "the already created job reconciles, nothing new is picked"
    assert store.data[intent_key]["state"] == "enqueued"
    assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"]

    # Restart after the intent was written and before the enqueue reached Fleet.
    store.data[intent_key] = {**settled, "state": "intended", "enqueued_at": None}
    del store.data[BUCKET_JOBS, "op-one"]
    del store.data[BUCKET_BINDINGS, "op-one"]
    resumed = FleetBacklog(store, Fleet(store), portfolio=Portfolio(store, packaged_definitions())).tick("plan-1", load)
    assert resumed["outcome"] == "enqueued" and resumed["job_id"] == "op-one" and resumed["cached"] is False
    assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"]

    # Restart before the pinned input was ever read: the open intent is resumed, not duplicated.
    store.data[intent_key] = {**settled, "state": "selected", "job_id": None, "job_binding": None,
                              "job_manifest_sha256": None, "goal_sha256": None, "base_revision": None,
                              "link_state": "pending"}
    again = FleetBacklog(store, Fleet(store), portfolio=Portfolio(store, packaged_definitions())).tick("plan-1", load)
    assert again["outcome"] == "enqueued" and again["cached"] is True, "the identical enqueue is idempotent"
    assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"]
    assert store.data[intent_key]["state"] == "enqueued" and store.data[intent_key]["link_state"] == "linked"


def test_an_equal_job_id_with_another_binding_is_a_conflict_not_a_successful_enqueue(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one"), item("other", priority=20)])
    # A job already exists under the same operation id with a different frozen manifest.
    fleet.enqueue("b", manifest("op-one", ["docs/elsewhere.md"]), GOAL, [])
    before = deepcopy(store.data[BUCKET_JOBS, "op-one"])
    conflict = coordinator.tick("plan-1", loader_for(tmp_path))
    assert conflict["outcome"] == "conflict" and conflict["reason_code"] == "binding_conflict"
    assert conflict["item_id"] == "one" and conflict["item_state"] == "conflict"
    assert store.data[BUCKET_JOBS, "op-one"] == before, "the already queued job is never edited"
    assert intent_of(store, "one")["state"] == "conflict"
    # The conflict is reported and an unrelated eligible item keeps moving.
    moved = coordinator.tick("plan-1", loader_for(tmp_path))
    assert moved["outcome"] == "enqueued" and moved["item_id"] == "other"
    assert moved["blocked"] == {"one": "binding_conflict"}


def test_a_crash_before_the_enqueue_cannot_adopt_a_foreign_job_or_unlock_a_successor(tmp_path):
    """R1: a restart between `intended` and the enqueue meets an ACCEPTED job carrying the same id.

    Lane, repository and the predeclared dependencies are part of the recorded identity, so each of
    these foreign rows is a conflict. A comparison limited to the manifest digest and the goal
    would have adopted every one of them and unlocked the dependent item.
    """
    same_manifest = manifest("op-one", ["docs/one.md"])
    foreign = [("another lane and repository", "b", same_manifest, [], False),
               ("another repository alone", "b", same_manifest, [], True),
               ("another frozen manifest", "a", manifest("op-one", ["docs/elsewhere.md"]), [], False)]
    for label, lane, document, dependencies, shared in foreign:
        coordinator, fleet, store = backlog(
            tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])], shared_repository=shared)
        fleet.enqueue(lane, document, GOAL, dependencies)
        settle(fleet, "op-one", ACCEPTED)
        intended = {**new_intent("plan-1", item("one"), NOW), "state": "intended", "job_id": "op-one",
                    "job_manifest_sha256": "0" * 64,
                    "job_binding": expected_binding("a", lane_identity(tmp_path, "a"),
                                                    "0" * 64, [], GOAL)}
        store.data[BUCKET_INTENTS, "plan-1:one"] = intended
        result = coordinator.tick("plan-1", loader_for(tmp_path, shared_repository=shared))
        assert result["outcome"] == "blocked", label
        assert result["blocked"] == {"one": "job_binding_conflict", "two": "dependency_conflict"}, label
        assert intent_of(store, "one")["state"] == "conflict", label
        assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"], label
        assert "plan-1:two" not in {k[1] for k in store.data if k[0] == BUCKET_INTENTS}, label


def test_an_intent_without_a_complete_recorded_binding_reconciles_nothing(tmp_path):
    """R1: a partial identity is not evidence. An intent that names a job id but no binding can
    neither claim that job nor be silently completed."""
    coordinator, fleet, store = backlog(tmp_path, [item("one")])
    fleet.enqueue("a", manifest("op-one", ["docs/one.md"]), GOAL, [])
    store.data[BUCKET_INTENTS, "plan-1:one"] = {**new_intent("plan-1", item("one"), NOW),
                                                "state": "intended", "job_id": "op-one",
                                                "job_binding": None}
    result = coordinator.tick("plan-1", loader_for(tmp_path))
    assert result["outcome"] == "blocked" and result["blocked"] == {"one": "job_binding_conflict"}
    assert intent_of(store, "one")["state"] == "conflict"


def test_a_job_row_carrying_another_goal_settles_the_open_intent_as_a_conflict(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one")])
    coordinator.tick("plan-1", loader_for(tmp_path))
    intent_key = (BUCKET_INTENTS, "plan-1:one")
    recorded = deepcopy(store.data[intent_key]["job_binding"])
    recorded["goal"]["sha256"] = "f" * 64
    store.data[intent_key] = {**store.data[intent_key], "state": "intended", "job_binding": recorded}
    result = coordinator.tick("plan-1", loader_for(tmp_path))
    assert result["outcome"] == "blocked" and result["blocked"] == {"one": "job_binding_conflict"}
    assert store.data[intent_key]["state"] == "conflict"


def test_concurrent_ticks_cannot_double_enqueue_one_item(tmp_path):
    store = MemoryStore()   # threads race through the store's own lock, as a real service would
    coordinator, fleet, _ = backlog(tmp_path, [item("one")], store=store)
    results, barrier = [], threading.Barrier(4)

    def tick():
        barrier.wait()
        results.append(FleetBacklog(store, Fleet(store), portfolio=Portfolio(store, packaged_definitions()))
                       .tick("plan-1", loader_for(tmp_path)))

    threads = [threading.Thread(target=tick) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    admitted = [r for r in results if r["outcome"] == "enqueued"]
    assert len(results) == 4 and admitted, "every tick reports a recorded outcome"
    assert {r["job_id"] for r in admitted} == {"op-one"}
    assert sum(1 for r in admitted if r["cached"] is False) == 1, "exactly one tick created the job"
    assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"]
    assert len([k for k in store.data if k[0] == BUCKET_INTENTS]) == 1
    assert len([k for k in store.data if k[0] == BUCKET_BINDINGS]) == 1


# ----- the frozen scope of a selected item -----------------------------------------------------
def test_a_registration_that_moves_a_selected_item_is_refused_without_side_effects(tmp_path):
    """R2: pin, lane, project, criterion and dependency identities are frozen once an intent
    exists - for the open intent of a selected item and for an admitted one alike."""
    coordinator, fleet, store = backlog(tmp_path, [item("one"), item("later", priority=90)])
    coordinator.tick("plan-1", loader_for(tmp_path))
    before = deepcopy(store.data)
    moves = [(item("one", revision="9" * 40), "item_pin_changed"),
             (item("one", lane="b"), "item_pin_changed"),
             (item("one", project="local-assets"), "item_scope_changed"),
             (item("one", criterion="absorbed-assets"), "item_scope_changed"),
             (item("one", dependencies=["later"]), "item_scope_changed")]
    for moved, code in moves:
        with pytest.raises(BacklogRefused, match=code):
            coordinator.register(plan(tmp_path, [moved, item("later", priority=90)]), pin(revision="9" * 40))
    with pytest.raises(BacklogRefused, match="item_removed"):
        coordinator.register(plan(tmp_path, [item("later", priority=90)]), pin(revision="9" * 40))
    with pytest.raises(BacklogRefused, match="repository_conflict"):
        coordinator.register({**plan(tmp_path, [item("one"), item("later", priority=90)]),
                              "repository": "7" * 64}, pin(revision="9" * 40))
    assert store.data == before, "a refused registration writes nothing"
    # Appending an item and flipping `enabled` remain owner decisions expressed in Git, and they
    # keep working while an item is admitted.
    grown = coordinator.register(plan(tmp_path, [item("one"), item("later", priority=90), item("new", priority=95)]),
                                 pin(revision="9" * 40))
    assert grown["cached"] is False and grown["items"] == 3
    paused = coordinator.register(plan(tmp_path, [item("one"), item("later", priority=90)], enabled=False),
                                  pin(revision="8" * 40))
    assert paused["enabled"] is False
    assert coordinator.tick("plan-1", loader_for(tmp_path))["outcome"] == "plan_paused"


def test_the_frozen_scope_also_holds_for_an_item_whose_job_was_already_accepted(tmp_path):
    """R2 for an ADMITTED intent: the criterion the work was selected under cannot be swapped
    after its job exists."""
    coordinator, fleet, store = backlog(tmp_path, [item("one")])
    coordinator.tick("plan-1", loader_for(tmp_path))
    settle(fleet, "op-one", ACCEPTED)
    before = deepcopy(store.data)
    with pytest.raises(BacklogRefused, match="item_scope_changed"):
        coordinator.register(plan(tmp_path, [item("one", criterion="absorbed-assets")]), pin(revision="9" * 40))
    assert store.data == before


def test_a_stale_pin_recorded_on_an_intent_refuses_that_item_at_selection(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one"), item("other", priority=20)])
    coordinator.tick("plan-1", loader_for(tmp_path))
    key = (BUCKET_INTENTS, "plan-1:one")
    store.data[key] = {**store.data[key], "manifest_revision": "8" * 40}
    result = coordinator.tick("plan-1", loader_for(tmp_path))
    assert result["outcome"] == "enqueued" and result["item_id"] == "other"
    assert result["blocked"] == {"one": "pin_changed"}
    [view] = [i for i in coordinator.status("plan-1")["plans"][0]["items"] if i["item_id"] == "one"]
    assert view["state"] == "conflict" and view["reason_code"] == "pin_changed"
    assert view["next_action"] == "owner_review"


# ----- pauses, dependencies and unavailable inputs ----------------------------------------------
def test_a_paused_plan_and_a_paused_fleet_are_distinct_recorded_outcomes(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one")], enabled=False)
    paused = coordinator.tick("plan-1", loader_for(tmp_path))
    assert paused["outcome"] == "plan_paused" and paused["next_action"] == "enable_plan"
    assert not [k for k in store.data if k[0] == BUCKET_INTENTS]
    coordinator.register(plan(tmp_path, [item("one")]), pin(sha256="1" * 64))
    fleet.pause()
    halted = coordinator.tick("plan-1", loader_for(tmp_path))
    assert halted["outcome"] == "fleet_paused" and halted["next_action"] == "resume_fleet"
    assert not [k for k in store.data if k[0] == BUCKET_JOBS]
    fleet.resume()
    assert coordinator.tick("plan-1", loader_for(tmp_path))["outcome"] == "enqueued"


def test_an_unregistered_plan_is_refused_without_side_effects(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one")])
    before = deepcopy(store.data)
    missing = coordinator.tick("plan-other", loader_for(tmp_path))
    assert missing["outcome"] == "plan_unregistered" and missing["next_action"] == "register_plan"
    assert store.data == before
    unknown = coordinator.status("plan-other")
    assert unknown["registered"] is False and unknown["plans"] == [] and unknown["outcome"] == "plan_unregistered"


def test_a_failed_dependency_blocks_only_its_dependents(tmp_path):
    items = [item("one"), item("two", priority=20, dependencies=["one"]),
             item("independent", lane="b", priority=30)]
    coordinator, fleet, _ = backlog(tmp_path, items)
    load = loader_for(tmp_path)
    assert coordinator.tick("plan-1", load)["item_id"] == "one"
    settle(fleet, "op-one", FAILED)
    moved = coordinator.tick("plan-1", load)
    assert moved["outcome"] == "enqueued" and moved["item_id"] == "independent"
    assert moved["blocked"] == {"two": "dependency_failed"}
    blocked = coordinator.tick("plan-1", load)
    assert blocked["outcome"] == "blocked" and blocked["blocked"] == {"two": "dependency_failed"}
    assert sorted(job["id"] for job in fleet.status()["jobs"]) == ["op-independent", "op-one"]


def test_a_repeatedly_unavailable_item_is_deferred_and_never_starves_an_eligible_one(tmp_path):
    """R3: the outage is not an attempt, the intent is kept and reconciled rather than discarded,
    an independent item keeps being admitted, and the bounded wait counts down durably."""
    items = [item("one"), item("independent", lane="b", priority=20)]
    coordinator, fleet, store = backlog(tmp_path, items)
    outage = loader_for(tmp_path, outages={"one"})
    first = coordinator.tick("plan-1", outage)
    assert first["outcome"] == "unavailable" and first["reason_code"] == "input_unavailable"
    assert first["error_type"] == "RuntimeError" and first["job_id"] is None and first["deferrals"] == 1
    assert intent_of(store, "one")["attempts"] == 0, "an outage is not an attempt"
    assert intent_of(store, "one")["defer_ticks"] == 1 and intent_of(store, "one")["state"] == "selected"
    # The deferred item steps aside: the independent project is admitted on the very next tick.
    moved = coordinator.tick("plan-1", outage)
    assert moved["outcome"] == "enqueued" and moved["item_id"] == "independent"
    assert moved["blocked"] == {"one": "deferred_input_unavailable"}
    assert intent_of(store, "one")["defer_ticks"] == 0, "the bounded wait counted down durably"
    # The still-unavailable item is retried once its wait expired, and it is still not an attempt.
    again = coordinator.tick("plan-1", outage)
    assert again["outcome"] == "unavailable" and again["deferrals"] == 2
    assert intent_of(store, "one")["attempts"] == 0
    assert not [k for k in store.data if k[0] == BUCKET_JOBS and k[1] == "op-one"]
    # A restart keeps the deferred intent observable and recoverable; nothing is admitted twice.
    resumed = FleetBacklog(store, Fleet(store), portfolio=Portfolio(store, packaged_definitions()))
    for _ in range(2):
        resumed.tick("plan-1", outage)
    recovered = resumed.tick("plan-1", loader_for(tmp_path))
    assert recovered["outcome"] == "enqueued" and recovered["job_id"] == "op-one"
    assert sorted(job["id"] for job in fleet.status()["jobs"]) == ["op-independent", "op-one"]
    assert intent_of(store, "one")["deferrals"] == 0 and intent_of(store, "one")["defer_ticks"] == 0


def test_a_permanently_unavailable_item_stops_being_retried_and_is_handed_to_the_owner(tmp_path):
    """R3: the deferral is bounded. The item ends blocked with its last failure preserved, its
    dependents stay blocked, and an unrelated item keeps moving."""
    items = [item("one"), item("two", priority=20, dependencies=["one"]),
             item("independent", lane="b", priority=30)]
    coordinator, fleet, store = backlog(tmp_path, items)
    outage = loader_for(tmp_path, outages={"one"})
    outcomes = [coordinator.tick("plan-1", outage)["outcome"] for _ in range(30)]
    assert outcomes.count("unavailable") == MAX_DEFERRALS, "a bounded number of retries, never forever"
    row = intent_of(store, "one")
    assert row["state"] == "blocked" and row["reason_code"] == "input_unavailable"
    assert row["error_type"] == "RuntimeError" and row["deferrals"] == MAX_DEFERRALS
    assert "op-independent" in [job["id"] for job in fleet.status()["jobs"]]
    last = coordinator.tick("plan-1", outage)
    assert last["outcome"] == "blocked"
    assert last["blocked"] == {"one": "input_unavailable", "two": "dependency_blocked"}
    [view] = [i for i in coordinator.status("plan-1")["plans"][0]["items"] if i["item_id"] == "one"]
    assert view["state"] == "blocked" and view["next_action"] == "owner_review"


def test_two_definite_refusals_block_the_item_and_never_retry_forever(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one"), item("other", priority=20)])
    refusals = {"one": "manifest_pin_mismatch"}
    first = coordinator.tick("plan-1", loader_for(tmp_path, refusals=refusals))
    assert first["outcome"] == "refused" and first["reason_code"] == "manifest_pin_mismatch"
    assert first["attempts"] == 1 and first["item_state"] == "selected"
    second = coordinator.tick("plan-1", loader_for(tmp_path, refusals=refusals))
    assert second["outcome"] == "refused" and second["attempts"] == MAX_ATTEMPTS
    assert second["item_state"] == "blocked"
    assert intent_of(store, "one")["state"] == "blocked"
    moved = coordinator.tick("plan-1", loader_for(tmp_path, refusals=refusals))
    assert moved["outcome"] == "enqueued" and moved["item_id"] == "other"
    assert moved["blocked"] == {"one": "manifest_pin_mismatch"}
    # The owner's route out is a NEW approved item id, so the blocked item and its reason survive
    # as history and no admitted pin is ever rewritten.
    corrected = plan(tmp_path, [item("one"), item("other", priority=20), item("one-fixed", priority=30)])
    coordinator.register(corrected, pin(revision="9" * 40))
    admitted = coordinator.tick("plan-1", loader_for(tmp_path, refusals=refusals))
    assert admitted["outcome"] == "enqueued" and admitted["item_id"] == "one-fixed"
    assert intent_of(store, "one")["state"] == "blocked"
    assert intent_of(store, "one")["reason_code"] == "manifest_pin_mismatch"


def test_a_fleet_refusal_of_the_enqueue_is_recorded_and_corrupts_no_queued_job(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one", lane="zzz")])
    result = coordinator.tick("plan-1", loader_for(tmp_path))
    assert result["outcome"] == "refused" and result["reason_code"] == "enqueue_lane_unknown"
    assert not [k for k in store.data if k[0] == BUCKET_JOBS]
    assert intent_of(store, "one")["attempts"] == 1


# ----- the portfolio linkage of an admitted job -------------------------------------------------
def test_a_binding_outage_leaves_a_durable_pending_linkage_that_resumes_and_unlocks_nothing(tmp_path):
    """The job exists, its goal binding does not yet: that is unfinished work. It is never reported
    as linked, it never unlocks a dependent item, and it is completed by a later tick."""
    class BrokenPortfolio(Portfolio):
        def bind(self, job_id, project_id, criterion_id):
            raise RuntimeError("injected portfolio outage (fixture)")

    items = [item("one"), item("two", priority=20, dependencies=["one"])]
    coordinator, fleet, store = backlog(tmp_path, items, portfolio=BrokenPortfolio(SerialStore(), packaged_definitions()))
    outage = coordinator.tick("plan-1", loader_for(tmp_path))
    assert outage["outcome"] == "unavailable" and outage["reason_code"] == "binding_unavailable"
    assert outage["error_type"] == "RuntimeError" and outage["job_id"] == "op-one"
    assert outage["linked"] is False and outage["link_state"] == "pending"
    assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"], "the job was admitted exactly once"
    assert not [k for k in store.data if k[0] == BUCKET_BINDINGS]
    settle(fleet, "op-one", ACCEPTED)
    # An accepted job whose binding is missing does NOT satisfy the dependency of its successor.
    blocked = coordinator.tick("plan-1", loader_for(tmp_path))
    assert blocked["blocked"]["two"] == "dependency_unlinked"
    [view] = [i for i in coordinator.status("plan-1")["plans"][0]["items"] if i["item_id"] == "one"]
    assert view["state"] == "enqueued" and view["job_status"] == "accepted"
    assert view["link_state"] == "pending" and view["next_action"] == "complete_binding"
    assert coordinator.status("plan-1")["plans"][0]["counts"]["unlinked"] == 1
    # A working binding owner completes the pending linkage without admitting anything twice.
    healthy = FleetBacklog(store, Fleet(store), portfolio=Portfolio(store, packaged_definitions()))
    linked = healthy.tick("plan-1", loader_for(tmp_path))
    assert linked["outcome"] == "enqueued" and linked["item_id"] == "one" and linked["linked"] is True
    assert store.data[BUCKET_BINDINGS, "op-one"]["criterion_id"] == "verified-loop"
    assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"]
    successor = healthy.tick("plan-1", loader_for(tmp_path))
    assert successor["outcome"] == "enqueued" and successor["item_id"] == "two"


def test_an_existing_different_binding_is_a_conflict_and_is_never_rewritten(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one"), item("other", lane="b", priority=20)])
    # The owner already bound this job id to another criterion (fixture row written directly).
    existing = {"id": "op-one", "job_id": "op-one", "project_id": "research-improvement",
                "criterion_id": "primary-source-decision", "recorded_by": "owner", "created_at": NOW}
    store.data[BUCKET_BINDINGS, "op-one"] = dict(existing)
    result = coordinator.tick("plan-1", loader_for(tmp_path))
    assert result["outcome"] == "conflict" and result["reason_code"] == "portfolio_binding_conflict"
    assert result["linked"] is False and result["link_state"] == "conflict"
    assert store.data[BUCKET_BINDINGS, "op-one"] == existing, "another owner's binding is never rewritten"
    [view] = [i for i in coordinator.status("plan-1")["plans"][0]["items"] if i["item_id"] == "one"]
    assert view["link_state"] == "conflict" and view["next_action"] == "owner_review"
    # The conflicted item is reported and an unrelated item keeps moving.
    moved = coordinator.tick("plan-1", loader_for(tmp_path))
    assert moved["outcome"] == "enqueued" and moved["item_id"] == "other"
    assert moved["blocked"] == {"one": "portfolio_binding_conflict"}


def test_without_a_binding_owner_no_tick_reports_a_linked_success(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one")], portfolio=None)
    result = coordinator.tick("plan-1", loader_for(tmp_path))
    assert result["outcome"] == "unavailable" and result["reason_code"] == "binding_owner_absent"
    assert result["linked"] is False and result["job_id"] == "op-one"
    assert not [k for k in store.data if k[0] == BUCKET_BINDINGS]


# ----- status, logging, observation and the opt-in runner ---------------------------------------
def test_status_separates_accepted_implementation_from_release_and_deployment(tmp_path):
    coordinator, fleet, _ = backlog(tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])])
    coordinator.tick("plan-1", loader_for(tmp_path))
    settle(fleet, "op-one", ACCEPTED)
    coordinator.tick("plan-1", loader_for(tmp_path))
    projection = coordinator.status("plan-1")
    [view] = projection["plans"]
    assert view["schema"] == "urn:zeus:fleet-backlog-status:1" and view["plan_id"] == "plan-1"
    assert view["pin"] == pin() and view["enabled"] is True and view["fleet_paused"] is False
    assert view["outcome"] == "backlog_exhausted" and view["next_action"] == "idle"
    states = {i["item_id"]: (i["state"], i["job_status"], i["next_action"]) for i in view["items"]}
    assert states["one"] == ("enqueued", "accepted", "owner_release_decision")
    assert states["two"] == ("enqueued", "queued", "await_fleet")
    assert view["counts"]["accepted"] == 1 and view["counts"]["enqueued"] == 2
    assert view["counts"]["unlinked"] == 0
    # An accepted item claims an accepted lane operation and nothing further: no merge, release or
    # deployment field exists here, and the authority label says so in the projection itself.
    assert set(view["items"][0]) == {"item_id", "project_id", "criterion_id", "lane", "priority", "pin",
                                     "dependencies", "job_id", "job_status", "reason_code", "attempts",
                                     "deferrals", "link_state", "link_reason", "state", "next_action"}
    assert "never a review verdict, a merge, a release or a deployment" in view["authority"]
    text = json.dumps([{k: v for k, v in i.items()} for i in view["items"]])
    assert "merge" not in text and "deployed" not in text, "no item claims delivery"
    text = json.dumps(projection)
    assert CANARY not in text and str(tmp_path) not in text and "lane_a" not in text
    # Every registered plan is readable without naming one.
    assert [p["plan_id"] for p in coordinator.status()["plans"]] == ["plan-1"]


def test_transitions_are_logged_with_identities_only_and_never_carry_goal_or_manifest_text(tmp_path, caplog):
    coordinator, _, _ = backlog(tmp_path, [item("one"), item("two", priority=20)])
    with caplog.at_level(logging.INFO, logger="zeus.fleet.backlog"):
        coordinator.tick("plan-1", loader_for(tmp_path))
        for _ in range(MAX_ATTEMPTS):
            coordinator.tick("plan-1", loader_for(tmp_path, refusals={"two": "manifest_refused"}))
        coordinator.tick("plan-1", loader_for(tmp_path))   # idle: nothing more is written
    records = [r for r in caplog.records if r.name == "zeus.fleet.backlog"]
    messages = [r.getMessage() for r in records]
    assert len(messages) == 2 + MAX_ATTEMPTS, "admission, its linkage and the refusals only"
    assert "plan=plan-1" in messages[0] and "item=one" in messages[0] and "job=op-one" in messages[0]
    assert "criterion=verified-loop" in messages[1]
    assert "reason=manifest_refused" in messages[2] and "state=blocked" in messages[-1]
    assert records[0].levelno == logging.INFO and records[-1].levelno == logging.WARNING
    text = "\n".join(messages)
    assert CANARY not in text and str(tmp_path) not in text and "docs/GOAL.md" not in text


def test_the_fixed_structured_transitions_reach_the_existing_observation_port(tmp_path):
    """Configuration and log lines are not the evidence here: these are the events the existing
    observer actually collected, with identifiers, fixed codes and counts only."""
    store = SerialStore()
    observer = observer_for(store)
    items = [item("one"), item("outage", lane="b", priority=20), item("bad", priority=30)]
    coordinator, _, _ = backlog(tmp_path, items, store=store, observer=observer)
    failing = loader_for(tmp_path, outages={"outage"}, refusals={"bad": "manifest_refused"})
    healthy = loader_for(tmp_path)
    assert coordinator.tick("plan-1", healthy)["item_id"] == "one"          # admitted
    assert coordinator.tick("plan-1", failing)["outcome"] == "unavailable"  # `outage` unavailable
    assert coordinator.tick("plan-1", failing)["item_id"] == "bad"          # `bad` refused once
    assert coordinator.tick("plan-1", failing)["outcome"] == "unavailable"  # `outage` again: silent
    assert coordinator.tick("plan-1", healthy)["item_id"] == "bad"          # admitted
    assert coordinator.tick("plan-1", healthy)["outcome"] == "blocked"      # deferred wait: silent
    assert coordinator.tick("plan-1", healthy)["item_id"] == "outage"       # admitted and recovered
    assert coordinator.tick("plan-1", healthy)["outcome"] == "backlog_exhausted"   # idle: silent
    records = observer.spool.records()
    kinds = [record["event_type"] for record in records]
    assert kinds.count("development.backlog_item_admitted") == 3
    assert kinds.count("operations.backlog_unavailable") == 1, "a run of outages is one transition"
    assert kinds.count("operations.backlog_item_refused") == 1
    assert kinds.count("operations.backlog_recovered") == 1
    admitted = [r for r in records if r["event_type"] == "development.backlog_item_admitted"][0]
    assert admitted["category"] == "development" and admitted["outcome"] == "succeeded"
    assert admitted["attributes"] == {"plan_id": "plan-1", "item_id": "one", "lane": "a",
                                      "job_id": "op-one", "cached": False, "linked": True}
    [unavailable] = [r for r in records if r["event_type"] == "operations.backlog_unavailable"]
    assert unavailable["outcome"] == "unknown" and unavailable["reason_code"] == "input_unavailable"
    assert unavailable["attributes"] == {"plan_id": "plan-1", "item_id": "outage", "lane": "b",
                                         "error_type": "RuntimeError", "deferrals": 1, "exhausted": False}
    [refused] = [r for r in records if r["event_type"] == "operations.backlog_item_refused"]
    assert refused["outcome"] == "blocked" and refused["reason_code"] == "manifest_refused"
    assert refused["attributes"]["item_state"] == "selected" and refused["attributes"]["attempts"] == 1
    [recovered] = [r for r in records if r["event_type"] == "operations.backlog_recovered"]
    assert recovered["attributes"] == {"plan_id": "plan-1", "item_id": "outage", "lane": "b", "deferrals": 2}
    text = json.dumps(records)
    assert CANARY not in text and str(tmp_path) not in text and "docs/GOAL.md" not in text
    assert "injected" not in text and "lane_a" not in text
    assert observer.counters["refused"] == 0, "every emitted event passed the registry allow-list"


class FakeLauncher:
    """Fixture launcher: records what was asked to run, never spawns a process."""

    def __init__(self, outcomes):
        self.outcomes, self.launched = outcomes, []

    def budget_exhausted(self, budget):
        return False

    def launch(self, job):
        self.launched.append(job["id"])
        return {"job_id": job["id"]}

    def wait(self, handles, seconds):
        return list(handles)

    def outcome(self, handle, job):
        return deepcopy(self.outcomes[handle["job_id"]])


def test_the_runner_backlog_is_disabled_by_default_and_opt_in_continues_successors(tmp_path):
    coordinator, fleet, _ = backlog(tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])])
    launcher = FakeLauncher({"op-one": ACCEPTED, "op-two": ACCEPTED})
    default = FleetRunner(fleet, launcher, sleep=lambda _: None, interval=0).run(once=True)
    assert default["backlog"] == {"state": "disabled", "outcome": None, "reason_code": None,
                                  "error_type": None}
    assert launcher.launched == [], "without the opt-in the runner invents no successor"

    ticks = []

    def ticker():
        result = coordinator.tick("plan-1", loader_for(tmp_path))
        ticks.append(result["outcome"])
        return result

    runner = FleetRunner(fleet, launcher, sleep=lambda _: None, interval=0, backlog=ticker)
    summary = runner.run(once=True)
    # One configured loop admitted, dispatched and finalized both items, and selected the second
    # one itself: no external tick command ran between the transitions.
    assert summary["admitted"] == ["op-one", "op-two"] and launcher.launched == ["op-one", "op-two"]
    assert [entry["status"] for entry in summary["finalized"]] == ["accepted", "accepted"]
    assert ticks.count("enqueued") == 2 and ticks[0] == "enqueued" and ticks[-1] == "backlog_exhausted"
    assert "blocked" not in ticks[2:], "a satisfied dependency stops blocking within the same loop"
    assert summary["backlog"] == {"state": "ok", "outcome": "backlog_exhausted", "reason_code": None,
                                  "error_type": None}
    assert summary["reconciliation"] == {"state": "disabled", "error_type": None}


def test_a_backlog_outage_is_reported_and_never_blocks_unrelated_admission(tmp_path, caplog):
    coordinator, fleet, _ = backlog(tmp_path, [item("one")])
    fleet.enqueue("b", manifest("op-manual", ["docs/manual.md"]), GOAL, [])
    launcher = FakeLauncher({"op-manual": ACCEPTED})

    def broken():
        raise RuntimeError("injected backlog outage (fixture)")

    with caplog.at_level(logging.INFO, logger="zeus.fleet.runner"):
        summary = FleetRunner(fleet, launcher, sleep=lambda _: None, interval=0, backlog=broken).run(once=True)
    assert summary["backlog"] == {"state": "unavailable", "outcome": None, "reason_code": None,
                                  "error_type": "RuntimeError"}
    assert summary["admitted"] == ["op-manual"] and launcher.launched == ["op-manual"]
    messages = [r.getMessage() for r in caplog.records if r.name == "zeus.fleet.runner"]
    assert messages == ["approved backlog unavailable; fleet admission continues"]
    assert "injected" not in "\n".join(messages) and "RuntimeError" not in "\n".join(messages)
    # A stopping runner closes admission and never selects new work.
    stopping = FleetRunner(fleet, launcher, sleep=lambda _: None, interval=0,
                           backlog=lambda: coordinator.tick("plan-1", loader_for(tmp_path)))
    stopping.stop()
    assert stopping.run(once=False)["backlog"]["state"] == "disabled"
    assert not [job for job in fleet.status()["jobs"] if job["id"] == "op-one"]


def test_a_returned_failure_is_a_failed_tick_not_an_ok_one(tmp_path, caplog):
    """R4: the adapter RETURNS `unavailable` and `refused` far more often than it raises. A
    returned failure keeps its reason and exception type, logs one transition, does not repeat
    itself and never stops unrelated admission."""
    fleet = Fleet(SerialStore())
    fleet.register(config(tmp_path))
    fleet.enqueue("b", manifest("op-manual", ["docs/manual.md"]), GOAL, [])
    launcher = FakeLauncher({"op-manual": ACCEPTED})
    answer = {"outcome": "unavailable", "reason_code": "input_unavailable", "error_type": "OSError"}
    runner = FleetRunner(fleet, launcher, sleep=lambda _: None, interval=0, backlog=lambda: dict(answer))
    with caplog.at_level(logging.INFO, logger="zeus.fleet.runner"):
        first = runner.run(once=True)
        assert first["backlog"] == {"state": "unavailable", "outcome": "unavailable",
                                    "reason_code": "input_unavailable", "error_type": "OSError"}
        assert first["admitted"] == ["op-manual"], "unrelated admission keeps running"
        assert runner.run(once=True)["backlog"]["state"] == "unavailable"
        answer = {"outcome": "refused", "reason_code": "manifest_refused", "error_type": None}
        refused = runner.run(once=True)
        assert refused["backlog"] == {"state": "refused", "outcome": "refused",
                                      "reason_code": "manifest_refused", "error_type": None}
        answer = {"outcome": "backlog_exhausted", "reason_code": None, "error_type": None}
        healthy = runner.run(once=True)
        assert healthy["backlog"] == {"state": "ok", "outcome": "backlog_exhausted",
                                      "reason_code": None, "error_type": None}
    messages = [r.getMessage() for r in caplog.records if r.name == "zeus.fleet.runner"]
    assert messages == ["approved backlog unavailable; fleet admission continues",
                        "approved backlog refused; fleet admission continues reason=manifest_refused",
                        "approved backlog recovered"], "one line per transition, none in between"
    assert "OSError" not in "\n".join(messages)


def test_no_store_transaction_is_ever_opened_inside_another_one(tmp_path):
    """The discriminating check for the real PG advisory lock: `SerialStore` refuses nesting, so a
    complete register/tick/link/status/admit cycle passing here could not have deadlocked on it."""
    coordinator, fleet, store = backlog(tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])])
    coordinator.tick("plan-1", loader_for(tmp_path))
    settle(fleet, "op-one", ACCEPTED)
    coordinator.tick("plan-1", loader_for(tmp_path))
    coordinator.status("plan-1")
    coordinator.status()
    assert store.depth == 0 and store.transactions > 6


# ----- real PostgreSQL ------------------------------------------------------------------------
def test_a_plan_registers_and_admits_over_a_real_isolated_postgres_store(tmp_path, isolated_pgstore):
    """Integration only (`HARNESS_INTEGRATION=1`): the same cycle against the real store whose
    transaction takes `pg_advisory_xact_lock`. A nested transaction would block until
    `lock_timeout` instead of returning; the loader stays a fixture and no model runs."""
    store = isolated_pgstore
    fleet = Fleet(store)
    fleet.register(config(tmp_path))
    coordinator = FleetBacklog(store, fleet, portfolio=Portfolio(store, packaged_definitions()))
    coordinator.register(plan(tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])]), pin())
    first = coordinator.tick("plan-1", loader_for(tmp_path))
    assert first["outcome"] == "enqueued" and first["job_id"] == "op-one" and first["linked"] is True
    assert coordinator.tick("plan-1", loader_for(tmp_path))["outcome"] == "blocked"
    settle(fleet, "op-one", ACCEPTED)
    second = coordinator.tick("plan-1", loader_for(tmp_path))
    assert second["outcome"] == "enqueued" and second["job_id"] == "op-two"
    assert coordinator.tick("plan-1", loader_for(tmp_path))["outcome"] == "backlog_exhausted"
    [view] = coordinator.status("plan-1")["plans"]
    assert {i["item_id"]: i["job_status"] for i in view["items"]} == {"one": "accepted", "two": "queued"}
    with store.transaction() as tx:
        assert len(tx.scan(BUCKET_PLANS)) == 1 and len(tx.scan(BUCKET_INTENTS)) == 2
        assert len(tx.scan(BUCKET_BINDINGS)) == 2
