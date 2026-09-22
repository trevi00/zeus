"""Approved backlog plans, durable intents and Fleet admission (INV-FLEET-BACKLOG-001).

Every loader, launcher and injected outage here is a labelled fixture: no git, no provider, no
model call and no real PostgreSQL is reached from this module except in the one explicitly
integration-gated test at the end, which skips without `HARNESS_INTEGRATION=1`.

The store used almost everywhere is `SerialStore`: a MemoryStore that REFUSES a transaction opened
while another one is already open. The real `PostgresStore.transaction` connects and takes
`pg_advisory_xact_lock` per transaction, so a nested call would block until `lock_timeout`; this
fixture turns that latent deadlock into an immediate failure in every test below.
"""
import hashlib
import json
import logging
import threading
from contextlib import contextmanager
from copy import deepcopy

import pytest

from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import BUCKET_JOBS, Fleet, FleetRunner
from codex_harness.application.fleet_backlog import BUCKET_INTENTS, BUCKET_PLANS, FleetBacklog
from codex_harness.domain.fleet import repository_identity
from codex_harness.domain.fleet_backlog import (
    MAX_ATTEMPTS,
    PLAN_SCHEMA,
    BacklogRefused,
    validate_plan,
)
from codex_harness.domain.operation import validate_manifest

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
PLAN_REVISION = "c" * 40
ITEM_REVISION = "d" * 40
PLAN_PATH = "docs/zeus/backlog.json"
ACCEPTED = {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0,
            "calls": {"reserved": 2, "settled": 2}}
FAILED = {"status": "failed", "reason_code": "child_refused", "exit_code": 1}


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


def config(tmp_path, **overrides):
    lanes = [{"id": "a", "team": "alpha", "repository": str(tmp_path / "repo-a"), "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": str(tmp_path / "rt-a")},
             {"id": "b", "team": "beta", "repository": str(tmp_path / "repo-b"), "schema": "lane_b",
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


def work(item_id):
    """The manifest and goal binding a real git-backed loader would return for one plan item."""
    return {"manifest": manifest("op-" + item_id, ["docs/" + item_id + ".md"]), "goal": dict(GOAL)}


def loader_for(refusals=None, outages=None, overrides=None):
    """A labelled fixture standing in for the adapter's git-backed loader; it reads nothing."""
    def load(item_document):
        item_id = item_document["id"]
        if refusals and item_id in refusals:
            raise BacklogRefused(refusals[item_id], "items[].manifest_sha256")
        if outages and item_id in outages:
            raise RuntimeError("injected git outage (fixture)")
        if overrides and item_id in overrides:
            return overrides[item_id]
        return work(item_id)
    return load


def backlog(tmp_path, items, *, store=None, **plan_overrides):
    store = SerialStore() if store is None else store
    fleet = Fleet(store)
    fleet.register(config(tmp_path))
    coordinator = FleetBacklog(store, fleet)
    coordinator.register(plan(tmp_path, items, **plan_overrides), pin())
    return coordinator, fleet, store


def settle(fleet, job_id, outcome):
    """Run the existing admission and finalization for one job; no runner, no process."""
    decision = fleet.admit_one()
    assert decision["job"]["id"] == job_id, decision
    return fleet.finalize(job_id, decision["job"]["owner_token"], outcome)


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
    load = loader_for()
    first = coordinator.tick("plan-1", load)
    assert first["outcome"] == "enqueued" and first["item_id"] == "one" and first["job_id"] == "op-one"
    assert first["cached"] is False and first["job_status"] == "queued" and first["lane"] == "a"
    assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"]
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


def test_an_exhausted_backlog_is_idle_and_writes_nothing_on_a_repeated_poll(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one")])
    coordinator.tick("plan-1", loader_for())
    before = deepcopy(store.data)
    for _ in range(3):
        assert coordinator.tick("plan-1", loader_for())["outcome"] == "backlog_exhausted"
    assert store.data == before, "an idle poll is not an event and moves no timestamp"


# ----- one durable identity -------------------------------------------------------------------
def test_a_lost_response_and_a_restart_keep_exactly_one_durable_identity(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one")])
    load = loader_for()
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
    resumed = FleetBacklog(store, Fleet(store)).tick("plan-1", load)
    assert resumed["outcome"] == "enqueued" and resumed["job_id"] == "op-one" and resumed["cached"] is False
    assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"]

    # Restart before the pinned input was ever read: the open intent is resumed, not duplicated.
    store.data[intent_key] = {**settled, "state": "selected", "job_id": None,
                              "job_manifest_sha256": None, "goal_sha256": None, "base_revision": None}
    again = FleetBacklog(store, Fleet(store)).tick("plan-1", load)
    assert again["outcome"] == "enqueued" and again["cached"] is True, "the identical enqueue is idempotent"
    assert [job["id"] for job in fleet.status()["jobs"]] == ["op-one"]
    assert store.data[intent_key]["state"] == "enqueued"


def test_an_equal_job_id_with_another_binding_is_a_conflict_not_a_successful_enqueue(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one"), item("other", priority=20)])
    # A job already exists under the same operation id with a different frozen manifest.
    fleet.enqueue("b", manifest("op-one", ["docs/elsewhere.md"]), GOAL, [])
    before = deepcopy(store.data[BUCKET_JOBS, "op-one"])
    conflict = coordinator.tick("plan-1", loader_for())
    assert conflict["outcome"] == "conflict" and conflict["reason_code"] == "binding_conflict"
    assert conflict["item_id"] == "one" and conflict["item_state"] == "conflict"
    assert store.data[BUCKET_JOBS, "op-one"] == before, "the already queued job is never edited"
    assert store.data[BUCKET_INTENTS, "plan-1:one"]["state"] == "conflict"
    # The conflict is reported and an unrelated eligible item keeps moving.
    moved = coordinator.tick("plan-1", loader_for())
    assert moved["outcome"] == "enqueued" and moved["item_id"] == "other"
    assert moved["blocked"] == {"one": "binding_conflict"}


def test_a_job_row_carrying_another_goal_settles_the_open_intent_as_a_conflict(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one")])
    coordinator.tick("plan-1", loader_for())
    intent_key = (BUCKET_INTENTS, "plan-1:one")
    store.data[intent_key] = {**store.data[intent_key], "state": "intended", "goal_sha256": "f" * 64}
    result = coordinator.tick("plan-1", loader_for())
    assert result["outcome"] == "blocked" and result["blocked"] == {"one": "job_binding_conflict"}
    assert store.data[intent_key]["state"] == "conflict"


def test_concurrent_ticks_cannot_double_enqueue_one_item(tmp_path):
    store = MemoryStore()   # threads race through the store's own lock, as a real service would
    coordinator, fleet, _ = backlog(tmp_path, [item("one")], store=store)
    results, barrier = [], threading.Barrier(4)

    def tick():
        barrier.wait()
        results.append(FleetBacklog(store, Fleet(store)).tick("plan-1", loader_for()))

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


# ----- pauses, stale pins, dependencies and unavailable inputs ---------------------------------
def test_a_paused_plan_and_a_paused_fleet_are_distinct_recorded_outcomes(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one")], enabled=False)
    paused = coordinator.tick("plan-1", loader_for())
    assert paused["outcome"] == "plan_paused" and paused["next_action"] == "enable_plan"
    assert not [k for k in store.data if k[0] == BUCKET_INTENTS]
    coordinator.register(plan(tmp_path, [item("one")]), pin(sha256="1" * 64))
    fleet.pause()
    halted = coordinator.tick("plan-1", loader_for())
    assert halted["outcome"] == "fleet_paused" and halted["next_action"] == "resume_fleet"
    assert not [k for k in store.data if k[0] == BUCKET_JOBS]
    fleet.resume()
    assert coordinator.tick("plan-1", loader_for())["outcome"] == "enqueued"


def test_an_unregistered_plan_is_refused_without_side_effects(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one")])
    before = deepcopy(store.data)
    missing = coordinator.tick("plan-other", loader_for())
    assert missing["outcome"] == "plan_unregistered" and missing["next_action"] == "register_plan"
    assert store.data == before
    unknown = coordinator.status("plan-other")
    assert unknown["registered"] is False and unknown["plans"] == [] and unknown["outcome"] == "plan_unregistered"


def test_a_changed_pin_on_an_admitted_item_refuses_the_registration_without_side_effects(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one"), item("later", priority=90)])
    coordinator.tick("plan-1", loader_for())
    before = deepcopy(store.data)
    moved = plan(tmp_path, [item("one", revision="9" * 40), item("later", priority=90)])
    with pytest.raises(BacklogRefused, match="item_pin_changed"):
        coordinator.register(moved, pin(revision="9" * 40))
    with pytest.raises(BacklogRefused, match="item_removed"):
        coordinator.register(plan(tmp_path, [item("later", priority=90)]), pin(revision="9" * 40))
    with pytest.raises(BacklogRefused, match="repository_conflict"):
        coordinator.register({**plan(tmp_path, [item("one"), item("later", priority=90)]),
                              "repository": "7" * 64}, pin(revision="9" * 40))
    assert store.data == before, "a refused registration writes nothing"
    # Appending an item and flipping `enabled` remain owner decisions expressed in Git.
    grown = coordinator.register(plan(tmp_path, [item("one"), item("later", priority=90), item("new", priority=95)]),
                                 pin(revision="9" * 40))
    assert grown["cached"] is False and grown["items"] == 3
    assert coordinator.register(plan(tmp_path, [item("one"), item("later", priority=90), item("new", priority=95)]),
                                pin(revision="9" * 40))["cached"] is True


def test_a_stale_pin_recorded_on_an_intent_refuses_that_item_at_selection(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one"), item("other", priority=20)])
    coordinator.tick("plan-1", loader_for())
    key = (BUCKET_INTENTS, "plan-1:one")
    store.data[key] = {**store.data[key], "manifest_revision": "8" * 40}
    result = coordinator.tick("plan-1", loader_for())
    assert result["outcome"] == "enqueued" and result["item_id"] == "other"
    assert result["blocked"] == {"one": "pin_changed"}
    [view] = [i for i in coordinator.status("plan-1")["plans"][0]["items"] if i["item_id"] == "one"]
    assert view["state"] == "conflict" and view["reason_code"] == "pin_changed"
    assert view["next_action"] == "owner_review"


def test_a_failed_dependency_blocks_only_its_dependents(tmp_path):
    items = [item("one"), item("two", priority=20, dependencies=["one"]),
             item("independent", lane="b", priority=30)]
    coordinator, fleet, _ = backlog(tmp_path, items)
    load = loader_for()
    assert coordinator.tick("plan-1", load)["item_id"] == "one"
    settle(fleet, "op-one", FAILED)
    moved = coordinator.tick("plan-1", load)
    assert moved["outcome"] == "enqueued" and moved["item_id"] == "independent"
    assert moved["blocked"] == {"two": "dependency_failed"}
    blocked = coordinator.tick("plan-1", load)
    assert blocked["outcome"] == "blocked" and blocked["blocked"] == {"two": "dependency_failed"}
    assert sorted(job["id"] for job in fleet.status()["jobs"]) == ["op-independent", "op-one"]


def test_an_unavailable_input_is_never_an_empty_success_and_is_not_counted_as_an_attempt(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one")])
    for _ in range(3):
        outage = coordinator.tick("plan-1", loader_for(outages={"one"}))
        assert outage["outcome"] == "unavailable" and outage["reason_code"] == "input_unavailable"
        assert outage["error_type"] == "RuntimeError" and outage["job_id"] is None
    assert store.data[BUCKET_INTENTS, "plan-1:one"]["attempts"] == 0, "an outage is not an attempt"
    assert not [k for k in store.data if k[0] == BUCKET_JOBS]
    recovered = coordinator.tick("plan-1", loader_for())
    assert recovered["outcome"] == "enqueued" and recovered["job_id"] == "op-one"


def test_two_definite_refusals_block_the_item_and_never_retry_forever(tmp_path):
    coordinator, _, store = backlog(tmp_path, [item("one"), item("other", priority=20)])
    refusals = {"one": "manifest_pin_mismatch"}
    first = coordinator.tick("plan-1", loader_for(refusals=refusals))
    assert first["outcome"] == "refused" and first["reason_code"] == "manifest_pin_mismatch"
    assert first["attempts"] == 1 and first["item_state"] == "selected"
    second = coordinator.tick("plan-1", loader_for(refusals=refusals))
    assert second["outcome"] == "refused" and second["attempts"] == MAX_ATTEMPTS
    assert second["item_state"] == "blocked"
    assert store.data[BUCKET_INTENTS, "plan-1:one"]["state"] == "blocked"
    moved = coordinator.tick("plan-1", loader_for(refusals=refusals))
    assert moved["outcome"] == "enqueued" and moved["item_id"] == "other"
    assert moved["blocked"] == {"one": "manifest_pin_mismatch"}
    # The owner's route out is a NEW approved item id, so the blocked item and its reason survive
    # as history and no admitted pin is ever rewritten.
    corrected = plan(tmp_path, [item("one"), item("other", priority=20), item("one-fixed", priority=30)])
    coordinator.register(corrected, pin(revision="9" * 40))
    admitted = coordinator.tick("plan-1", loader_for(refusals=refusals))
    assert admitted["outcome"] == "enqueued" and admitted["item_id"] == "one-fixed"
    assert store.data[BUCKET_INTENTS, "plan-1:one"]["state"] == "blocked"
    assert store.data[BUCKET_INTENTS, "plan-1:one"]["reason_code"] == "manifest_pin_mismatch"


def test_a_fleet_refusal_of_the_enqueue_is_recorded_and_corrupts_no_queued_job(tmp_path):
    coordinator, fleet, store = backlog(tmp_path, [item("one", lane="zzz")])
    result = coordinator.tick("plan-1", loader_for())
    assert result["outcome"] == "refused" and result["reason_code"] == "enqueue_lane_unknown"
    assert not [k for k in store.data if k[0] == BUCKET_JOBS]
    assert store.data[BUCKET_INTENTS, "plan-1:one"]["attempts"] == 1


# ----- status, logging and the opt-in runner ---------------------------------------------------
def test_status_separates_accepted_implementation_from_release_and_deployment(tmp_path):
    coordinator, fleet, _ = backlog(tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])])
    coordinator.tick("plan-1", loader_for())
    settle(fleet, "op-one", ACCEPTED)
    coordinator.tick("plan-1", loader_for())
    projection = coordinator.status("plan-1")
    [view] = projection["plans"]
    assert view["schema"] == "urn:zeus:fleet-backlog-status:1" and view["plan_id"] == "plan-1"
    assert view["pin"] == pin() and view["enabled"] is True and view["fleet_paused"] is False
    assert view["outcome"] == "backlog_exhausted" and view["next_action"] == "idle"
    states = {i["item_id"]: (i["state"], i["job_status"], i["next_action"]) for i in view["items"]}
    assert states["one"] == ("enqueued", "accepted", "owner_release_decision")
    assert states["two"] == ("enqueued", "queued", "await_fleet")
    assert view["counts"]["accepted"] == 1 and view["counts"]["enqueued"] == 2
    # An accepted item claims an accepted lane operation and nothing further: no merge, release or
    # deployment field exists here, and the authority label says so in the projection itself.
    assert set(view["items"][0]) == {"item_id", "project_id", "criterion_id", "lane", "priority", "pin",
                                     "dependencies", "job_id", "job_status", "reason_code", "attempts",
                                     "state", "next_action"}
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
        coordinator.tick("plan-1", loader_for())
        for _ in range(MAX_ATTEMPTS):
            coordinator.tick("plan-1", loader_for(refusals={"two": "manifest_refused"}))
        coordinator.tick("plan-1", loader_for())   # idle: nothing more is written
    records = [r for r in caplog.records if r.name == "zeus.fleet.backlog"]
    messages = [r.getMessage() for r in records]
    assert len(messages) == 1 + MAX_ATTEMPTS, "transitions only; an idle poll logs nothing"
    assert "plan=plan-1" in messages[0] and "item=one" in messages[0] and "job=op-one" in messages[0]
    assert "reason=manifest_refused" in messages[1] and "state=blocked" in messages[-1]
    assert records[0].levelno == logging.INFO and records[-1].levelno == logging.WARNING
    text = "\n".join(messages)
    assert CANARY not in text and str(tmp_path) not in text and "docs/GOAL.md" not in text


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
    assert default["backlog"] == {"state": "disabled", "outcome": None, "error_type": None}
    assert launcher.launched == [], "without the opt-in the runner invents no successor"

    ticks = []

    def ticker():
        result = coordinator.tick("plan-1", loader_for())
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
    assert summary["backlog"] == {"state": "ok", "outcome": "backlog_exhausted", "error_type": None}
    assert summary["reconciliation"] == {"state": "disabled", "error_type": None}


def test_a_backlog_outage_is_reported_and_never_blocks_unrelated_admission(tmp_path, caplog):
    coordinator, fleet, _ = backlog(tmp_path, [item("one")])
    fleet.enqueue("b", manifest("op-manual", ["docs/manual.md"]), GOAL, [])
    launcher = FakeLauncher({"op-manual": ACCEPTED})

    def broken():
        raise RuntimeError("injected backlog outage (fixture)")

    with caplog.at_level(logging.INFO, logger="zeus.fleet.runner"):
        summary = FleetRunner(fleet, launcher, sleep=lambda _: None, interval=0, backlog=broken).run(once=True)
    assert summary["backlog"] == {"state": "unavailable", "outcome": None, "error_type": "RuntimeError"}
    assert summary["admitted"] == ["op-manual"] and launcher.launched == ["op-manual"]
    messages = [r.getMessage() for r in caplog.records if r.name == "zeus.fleet.runner"]
    assert messages == ["approved backlog unavailable; fleet admission continues"]
    assert "injected" not in "\n".join(messages) and "RuntimeError" not in "\n".join(messages)
    # A stopping runner closes admission and never selects new work.
    stopping = FleetRunner(fleet, launcher, sleep=lambda _: None, interval=0,
                           backlog=lambda: coordinator.tick("plan-1", loader_for()))
    stopping.stop()
    assert stopping.run(once=False)["backlog"]["state"] == "disabled"
    assert not [job for job in fleet.status()["jobs"] if job["id"] == "op-one"]


def test_no_store_transaction_is_ever_opened_inside_another_one(tmp_path):
    """The discriminating check for the real PG advisory lock: `SerialStore` refuses nesting, so a
    complete register/tick/status/admit cycle passing here could not have deadlocked on it."""
    coordinator, fleet, store = backlog(tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])])
    coordinator.tick("plan-1", loader_for())
    settle(fleet, "op-one", ACCEPTED)
    coordinator.tick("plan-1", loader_for())
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
    coordinator = FleetBacklog(store, fleet)
    coordinator.register(plan(tmp_path, [item("one"), item("two", priority=20, dependencies=["one"])]), pin())
    first = coordinator.tick("plan-1", loader_for())
    assert first["outcome"] == "enqueued" and first["job_id"] == "op-one"
    assert coordinator.tick("plan-1", loader_for())["outcome"] == "blocked"
    settle(fleet, "op-one", ACCEPTED)
    second = coordinator.tick("plan-1", loader_for())
    assert second["outcome"] == "enqueued" and second["job_id"] == "op-two"
    assert coordinator.tick("plan-1", loader_for())["outcome"] == "backlog_exhausted"
    [view] = coordinator.status("plan-1")["plans"]
    assert {i["item_id"]: i["job_status"] for i in view["items"]} == {"one": "accepted", "two": "queued"}
    with store.transaction() as tx:
        assert len(tx.scan(BUCKET_PLANS)) == 1 and len(tx.scan(BUCKET_INTENTS)) == 2
