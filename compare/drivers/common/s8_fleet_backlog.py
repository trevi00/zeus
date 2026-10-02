"""Shared S8 scenario steps (`coordination.fleet_backlog`): M7 `application/fleet_backlog.py` (`FleetBacklog`), characterized BEFORE pilot 97 moves
it into COORDINATION (DESIGN-s8 §16 V21), in the sequences of the M7 `tests/test_fleet_backlog.py` (31 tests).

- **a_surface**: the module surface (`__all__`, the two bucket names, `OBSERVED_OUTCOMES`, the logger), a default-built Fleet and `status()` over an
  empty store (the M7 callers use `FleetBacklog(store)`).
- **b_plan**: `validate_plan` refusals and the canonical form (M7 `test_plan_validation_*`), `register` (cached, repository conflict, the frozen scope
  of an item that already has a durable intent, appending an item and flipping `enabled`; M7 `test_a_registration_that_moves_*`, `test_the_frozen_scope_*`),
  `plan`.
- **c_tick**: select / resolve / enqueue / confirm / link over the real Fleet (M7 `test_a_valid_plan_admits_*`, `test_the_recorded_identity_*`,
  `test_an_exhausted_backlog_*`, `test_a_lost_response_*`, pauses, dependencies, `test_a_failed_dependency_*`, `test_a_stale_pin_*`).
- **d_conflict**: an equal job id under another binding, a crash before the enqueue meeting a foreign job, an intent without a recorded binding, a job
  row carrying another goal (M7 `test_an_equal_job_id_*`, `test_a_crash_before_the_enqueue_*`, `test_an_intent_without_*`, `test_a_job_row_carrying_*`).
- **e_deferral**: deferral and its bounded countdown, `MAX_DEFERRALS` exhaustion, two definite refusals (`MAX_ATTEMPTS`), a Fleet-refused enqueue.
- **f_link**: the portfolio linkage: pending after an outage, resumed, a binding conflict, a refused binding, no binding owner.
- **g_status_observe**: `status` (the M7 projection test), the logged transitions and the observer events, no nested store transaction.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. The Fleet is the REAL one (M7 `Fleet`; the target's FleetFacade over
FleetRegistry/AdmissionControl/FleetPause, `api.fleet_port` giving the object `FleetBacklog` receives). The store is a MemoryStore wrapped by
`SerialStore` (M7's: a transaction opened inside another is refused, as the PostgreSQL advisory lock would deadlock). LABELLED fakes: the `loader`
(reads nothing), the portfolio (`FakePortfolio`: records `bind` calls; the M7 tests use the real Portfolio, whose behaviour is the `intake.portfolio`
family's), the observer (`FakeObserver`: records `emit` calls; the M7 test reads a real Observer's spool). Scripted clocks and token sources.

Unreachable here, reported in `m7_tests`: the three `FleetRunner` tests (the runner family), the thread-race test (nondeterministic), the PostgreSQL
test (needs a database). For every refusal the digest of the whole store before and after is recorded (nothing written)."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import contextmanager
from copy import deepcopy

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
PLAN_REVISION = "c" * 40
ITEM_REVISION = "d" * 40
PLAN_PATH = "docs/zeus/backlog.json"
ROOT = "/zeus-rebuild-s8-fleet-backlog"
ACCEPTED = {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0, "calls": {"reserved": 2, "settled": 2}}
FAILED = {"status": "failed", "reason_code": "child_refused", "exit_code": 1}
NOW = "2026-09-22T00:00:00+00:00"
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}

M7_TESTS = {
    "covered": ["test_plan_validation_refuses_unknown_fields_duplicates_cycles_and_foreign_pins",
                "test_a_valid_plan_admits_one_eligible_item_into_the_existing_fleet_exactly_once",
                "test_the_recorded_identity_is_the_complete_binding_of_the_authoritative_job_row",
                "test_an_exhausted_backlog_is_idle_and_writes_nothing_on_a_repeated_poll",
                "test_a_lost_response_and_a_restart_keep_exactly_one_durable_identity",
                "test_an_equal_job_id_with_another_binding_is_a_conflict_not_a_successful_enqueue",
                "test_a_crash_before_the_enqueue_cannot_adopt_a_foreign_job_or_unlock_a_successor",
                "test_an_intent_without_a_complete_recorded_binding_reconciles_nothing",
                "test_a_job_row_carrying_another_goal_settles_the_open_intent_as_a_conflict",
                "test_a_registration_that_moves_a_selected_item_is_refused_without_side_effects",
                "test_the_frozen_scope_also_holds_for_an_item_whose_job_was_already_accepted",
                "test_a_stale_pin_recorded_on_an_intent_refuses_that_item_at_selection",
                "test_a_paused_plan_and_a_paused_fleet_are_distinct_recorded_outcomes",
                "test_an_unregistered_plan_is_refused_without_side_effects",
                "test_a_failed_dependency_blocks_only_its_dependents",
                "test_a_repeatedly_unavailable_item_is_deferred_and_never_starves_an_eligible_one",
                "test_a_permanently_unavailable_item_stops_being_retried_and_is_handed_to_the_owner",
                "test_two_definite_refusals_block_the_item_and_never_retry_forever",
                "test_a_fleet_refusal_of_the_enqueue_is_recorded_and_corrupts_no_queued_job",
                "test_a_binding_outage_leaves_a_durable_pending_linkage_that_resumes_and_unlocks_nothing",
                "test_an_existing_different_binding_is_a_conflict_and_is_never_rewritten",
                "test_without_a_binding_owner_no_tick_reports_a_linked_success",
                "test_status_separates_accepted_implementation_from_release_and_deployment",
                "test_transitions_are_logged_with_identities_only_and_never_carry_goal_or_manifest_text",
                "test_the_fixed_structured_transitions_reach_the_existing_observation_port",
                "test_no_store_transaction_is_ever_opened_inside_another_one"],
    "unreachable": {"test_concurrent_ticks_cannot_double_enqueue_one_item": "threads race the store lock; nondeterministic order",
                    "test_the_runner_backlog_is_disabled_by_default_and_opt_in_continues_successors": "FleetRunner family",
                    "test_a_backlog_outage_is_reported_and_never_blocks_unrelated_admission": "FleetRunner family",
                    "test_a_returned_failure_is_a_failed_tick_not_an_ok_one": "FleetRunner family",
                    "test_a_plan_registers_and_admits_over_a_real_isolated_postgres_store": "needs a real database"}}


# ---- scripted sources and the labelled doubles ---------------------------------------------------------------------------------
def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ticking(prefix="2026-09-18T00:00:00"):
    counter = iter(range(1, 100_000))
    return lambda: "%s.%06d+00:00" % (prefix, next(counter))


def tokens():
    counter = iter(range(1, 100_000))
    return lambda: "token-%04d" % next(counter)


class SerialStore:
    """MemoryStore with the real control-plane contract made observable (M7's fixture): opening a transaction inside another one is the nested case that
    deadlocks on the PostgreSQL advisory lock."""

    def __init__(self, inner):
        self.inner, self.depth, self.transactions = inner, 0, 0

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


def records(store):
    with store.transaction() as tx:
        rows = tx.records()
    return sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)


def store_digest(store) -> str:
    return canonical_digest(records(store))


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "field": getattr(exc, "field", None),
                "message": str(exc)[:160], "canary_or_root_in_message": CANARY in str(exc) or ROOT in str(exc)}
    return {"value": value}


def guarded(store, fn, *args, **kwargs):
    """A refusal with the digest of the whole store before and after (nothing written)."""
    before = store_digest(store)
    result = call(fn, *args, **kwargs)
    after = store_digest(store)
    return {**result, "store_unchanged": before == after, "store_digest_before": before, "store_digest_after": after}


class FakePortfolio:
    """LABELLED fake of the binding owner: records the `bind` calls; `mode` is `ok`, `outage`, `conflict` or `refused`."""

    def __init__(self, api, mode="ok", existing=None):
        self.api, self.mode, self.calls, self.bindings = api, mode, [], dict(existing or {})

    def bind(self, job_id, project_id, criterion_id):
        self.calls.append([job_id, project_id, criterion_id, self.mode])
        if self.mode == "outage":
            raise RuntimeError("injected portfolio outage (fixture)")
        if self.mode == "conflict":
            raise self.api.PortfolioRefused("binding_conflict")
        if self.mode == "refused":
            raise self.api.PortfolioRefused("criterion_unknown", "criterion_id")
        new = [project_id, criterion_id]
        cached = self.bindings.get(job_id) == new
        self.bindings[job_id] = new
        return {"bound": True, "cached": cached, "job_id": job_id}


class FakeObserver:
    """LABELLED fake of the observation port: records the `emit` calls."""

    def __init__(self):
        self.records = []

    def emit(self, event, outcome, severity=None, reason_code=None, attributes=None):
        self.records.append({"event": event, "outcome": outcome, "severity": severity, "reason_code": reason_code,
                             "attributes": deepcopy(attributes)})


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append([record.levelname, record.getMessage()])


# ---- builders -----------------------------------------------------------------------------------------------------------------
def config(shared=False, **overrides):
    second = "repo-a" if shared else "repo-b"
    lanes = [{"id": "a", "team": "alpha", "repository": ROOT + "/repo-a", "schema": "lane_a", "redis_namespace": "fleet-a",
              "runtime": ROOT + "/rt-a"},
             {"id": "b", "team": "beta", "repository": ROOT + "/" + second, "schema": "lane_b", "redis_namespace": "fleet-b",
              "runtime": ROOT + "/rt-b"}]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2, "budget": {"per_host": 4, "total": 8}, "lanes": lanes, **overrides}


def manifest(api, op_id, paths):
    return api.validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + op_id, "rationale": CANARY},
        "plan": {"objective": CANARY, "acceptance_criteria": ["ok"], "allowed_paths": paths},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}})


def item(item_id, *, lane="a", priority=10, dependencies=(), project="research-improvement", criterion="verified-loop", revision=ITEM_REVISION,
         sha256=None):
    return {"id": item_id, "project_id": project, "criterion_id": criterion, "lane": lane,
            "manifest_path": "docs/zeus/manifests/" + item_id + ".json", "manifest_revision": revision,
            "manifest_sha256": sha256 or hashlib.sha256(item_id.encode()).hexdigest(), "priority": priority,
            "dependencies": list(dependencies)}


def plan(api, items, *, enabled=True, plan_id="plan-1", lane="a"):
    return {"schema": api.PLAN_SCHEMA, "plan_id": plan_id, "repository": api.repository_identity(ROOT + "/repo-" + lane), "enabled": enabled,
            "items": items}


def pin(revision=PLAN_REVISION, path=PLAN_PATH, sha256="e" * 64):
    return {"revision": revision, "path": path, "sha256": sha256}


def lane_identity(api, lane, shared=False):
    return api.repository_identity(ROOT + "/" + ("repo-a" if lane == "a" or shared else "repo-b"))


def loader_for(api, refusals=None, outages=None, overrides=None, shared=False):
    """LABELLED fixture standing in for the adapter's git-backed loader; it reads nothing."""
    def load(item_document):
        item_id = item_document["id"]
        if refusals and item_id in refusals:
            raise api.BacklogRefused(refusals[item_id], "items[].manifest_sha256")
        if outages and item_id in outages:
            raise RuntimeError("injected git outage (fixture)")
        if overrides and item_id in overrides:
            return overrides[item_id]
        return {"manifest": manifest(api, "op-" + item_id, ["docs/" + item_id + ".md"]), "goal": dict(GOAL),
                "repository": lane_identity(api, item_document["lane"], shared)}
    return load


class World:
    """One store, its REAL Fleet, a backlog coordinator and its fakes."""

    def __init__(self, api, items, *, portfolio="ok", observer=None, shared=False, store=None, **plan_overrides):
        self.api = api
        self.store = SerialStore(api.MemoryStore()) if store is None else store
        self.fleet = api.Fleet(self.store, ticking(), tokens())
        self.fleet.register(config(shared))
        self.portfolio = FakePortfolio(api) if portfolio == "ok" else portfolio
        self.observer = observer
        self.coordinator = api.FleetBacklog(self.store, api.fleet_port(self.fleet), clock=ticking("2026-09-22T00:00:00"), portfolio=self.portfolio,
                                            observer=observer)
        self.coordinator.register(plan(api, items, **plan_overrides), pin())
        self.shared = shared

    def restart(self, portfolio=None, observer=None):
        """A second coordinator over the same store (a new process): its own Fleet objects, a fresh scripted clock."""
        fleet = self.api.Fleet(self.store, ticking(), tokens())
        return self.api.FleetBacklog(self.store, self.api.fleet_port(fleet), clock=ticking("2026-09-23T00:00:00"),
                                     portfolio=FakePortfolio(self.api) if portfolio is None else portfolio, observer=observer)

    def load(self, **kwargs):
        return loader_for(self.api, shared=self.shared, **kwargs)

    def tick(self, loader=None, plan_id="plan-1"):
        return self.coordinator.tick(plan_id, loader or self.load())

    def settle(self, job_id, outcome):
        """The existing admission and finalization for one job; no runner, no process."""
        decision = self.fleet.admit_one()
        if decision["job"]["id"] != job_id:
            raise RuntimeError("scenario error: admitted " + decision["job"]["id"])
        return self.fleet.finalize(job_id, decision["job"]["owner_token"], outcome)

    def intent(self, item_id, plan_id="plan-1"):
        return self.store.data.get((self.api.BUCKET_INTENTS, plan_id + ":" + item_id))

    def job_ids(self):
        return [job["id"] for job in self.fleet.status()["jobs"]]

    def bucket_keys(self, bucket):
        return sorted(k[1] for k in self.store.data if k[0] == bucket)


def item_view(world, plan_id, item_id):
    return [i for i in world.coordinator.status(plan_id)["plans"][0]["items"] if i["item_id"] == item_id]


# =====================================================================================================================
def a_surface(api) -> dict:
    out = {}
    out["all"] = list(api.ALL)
    out["buckets"] = [api.BUCKET_PLANS, api.BUCKET_INTENTS]
    out["observed_outcomes"] = sorted(api.OBSERVED_OUTCOMES)
    out["logger"] = api.LOGGER.name
    out["limits"] = {"MAX_ATTEMPTS": api.MAX_ATTEMPTS, "MAX_DEFERRALS": api.MAX_DEFERRALS}
    store = SerialStore(api.MemoryStore())
    default = api.FleetBacklog(store)
    out["default_fleet_is_built"] = isinstance(default.fleet, api.FleetClass)
    out["default_portfolio_observer"] = [default.portfolio, default.observer]
    out["status_empty_all"] = guarded(store, default.status)
    out["status_empty_named"] = guarded(store, default.status, "plan-1")
    out["tick_unregistered"] = guarded(store, default.tick, "plan-1", loader_for(api))
    out["plan_unregistered"] = guarded(store, default.plan, "plan-1")
    given = api.Fleet(store, ticking(), tokens())
    explicit = api.FleetBacklog(store, api.fleet_port(given))
    out["explicit_fleet_is_kept"] = explicit.fleet is api.fleet_port(given)
    return {"surface": out}


def b_plan(api) -> dict:
    cases = {}
    good = plan(api, [item("one"), item("two", priority=20, dependencies=["one"])])
    canonical = api.validate_plan(good)
    cases["canonical"] = {"first_item_sorted": canonical["items"][0] == dict(sorted(good["items"][0].items())), "plan_id": canonical["plan_id"],
                          "enabled": canonical["enabled"], "plan": canonical}
    bad = [("plan_schema", {"schema": "urn:zeus:fleet-backlog:2"}), ("plan_fields", {"version": 1}),
           ("plan_invalid_id", {"plan_id": "bad id"}), ("plan_invalid_repository", {"repository": "/abs/repo-a"}),
           ("plan_invalid_enabled", {"enabled": "yes"}), ("plan_invalid_items", {"items": []}),
           ("plan_duplicate", {"items": [item("one"), item("one")]}),
           ("dependency_self", {"items": [item("one", dependencies=["one"])]}),
           ("dependency_unknown", {"items": [item("one", dependencies=["absent"])]}),
           ("dependency_cycle", {"items": [item("one", dependencies=["two"]), item("two", dependencies=["one"])]}),
           ("item_path_outside", {"items": [{**item("one"), "manifest_path": "../outside/x.json"}]}),
           ("item_path_not_json", {"items": [{**item("one"), "manifest_path": "docs/x.md"}]}),
           ("item_revision_short", {"items": [{**item("one"), "manifest_revision": "short"}]}),
           ("item_sha_not_hex", {"items": [{**item("one"), "manifest_sha256": "z" * 64}]}),
           ("item_priority_bool", {"items": [{**item("one"), "priority": True}]}),
           ("item_priority_negative", {"items": [{**item("one"), "priority": -1}]}),
           ("item_lane_invalid", {"items": [{**item("one"), "lane": "bad lane"}]}),
           ("item_extra_command", {"items": [{**item("one"), "command": "rm -rf /"}]})]
    for name, overrides in bad:
        cases["refuse_" + name] = call(api.validate_plan, {**good, **overrides})
    cases["disabled_plan"] = {"enabled": api.validate_plan(plan(api, [item("one")], enabled=False))["enabled"]}
    for name, pin_document in (("pin_valid", pin()), ("pin_short_revision", pin(revision="short")), ("pin_path_outside", pin(path="../x.json")),
                               ("pin_extra", {**pin(), "extra": 1}), ("pin_not_dict", ["x"])):
        cases[name] = call(api.validate_pin, pin_document)

    # register: cached, repository conflict, the frozen scope, growth and the pause flag
    world = World(api, [item("one"), item("later", priority=90)])
    cases["register_cached"] = call(world.coordinator.register, plan(api, [item("one"), item("later", priority=90)]), pin())
    cases["plan_row"] = call(world.coordinator.plan, "plan-1")
    cases["plan_other"] = call(world.coordinator.plan, "plan-other")
    cases["register_invalid_plan"] = guarded(world.store, world.coordinator.register, {"schema": "x"}, pin())
    cases["register_invalid_pin"] = guarded(world.store, world.coordinator.register, plan(api, [item("one")]), {"revision": "x"})
    world.tick()
    before = deepcopy(world.store.data)
    moves = [("pin_revision", item("one", revision="9" * 40)), ("lane", item("one", lane="b")), ("project", item("one", project="local-assets")),
             ("criterion", item("one", criterion="absorbed-assets")), ("dependency", item("one", dependencies=["later"]))]
    for name, moved in moves:
        cases["frozen_" + name] = guarded(world.store, world.coordinator.register,
                                          plan(api, [moved, item("later", priority=90)]), pin(revision="9" * 40))
    cases["frozen_item_removed"] = guarded(world.store, world.coordinator.register, plan(api, [item("later", priority=90)]), pin(revision="9" * 40))
    cases["frozen_repository_conflict"] = guarded(world.store, world.coordinator.register,
                                                  {**plan(api, [item("one"), item("later", priority=90)]), "repository": "7" * 64},
                                                  pin(revision="9" * 40))
    cases["frozen_store_untouched"] = world.store.data == before
    cases["grown"] = call(world.coordinator.register, plan(api, [item("one"), item("later", priority=90), item("new", priority=95)]),
                          pin(revision="9" * 40))
    cases["paused_registration"] = call(world.coordinator.register, plan(api, [item("one"), item("later", priority=90)], enabled=False),
                                        pin(revision="8" * 40))
    cases["tick_plan_paused"] = world.tick()
    cases["plan_row_after"] = call(world.coordinator.plan, "plan-1")

    # the frozen scope also holds once the job was accepted
    world = World(api, [item("one")])
    world.tick()
    world.settle("op-one", ACCEPTED)
    cases["frozen_after_accepted"] = guarded(world.store, world.coordinator.register,
                                             plan(api, [item("one", criterion="absorbed-assets")]), pin(revision="9" * 40))
    cases["pin_stale_register_second_plan"] = call(world.coordinator.register, plan(api, [item("x1")], plan_id="plan-2"), pin())
    cases["status_two_plans"] = call(world.coordinator.status)
    return {"plan": cases}


def c_tick(api) -> dict:
    cases = {}
    world = World(api, [item("one"), item("two", priority=20, dependencies=["one"])])
    first = world.tick()
    cases["tick_first"] = first
    cases["fleet_jobs_after_first"] = world.job_ids()
    cases["bindings_after_first"] = world.portfolio.bindings
    cases["portfolio_calls"] = world.portfolio.calls
    cases["tick_waiting"] = world.tick()
    cases["job_one_status_waiting"] = world.store.data[api.BUCKET_JOBS, "op-one"]["status"]
    cases["settle_one"] = world.settle("op-one", ACCEPTED)
    cases["tick_second"] = world.tick()
    cases["job_two_dependencies"] = world.store.data[api.BUCKET_JOBS, "op-two"]["dependencies"]
    cases["tick_exhausted"] = world.tick()
    cases["intent_keys"] = world.bucket_keys(api.BUCKET_INTENTS)
    cases["identity"] = {}
    for item_id, job_id in (("one", "op-one"), ("two", "op-two")):
        recorded = world.intent(item_id)["job_binding"]
        cases["identity"][item_id] = {"equals_binding_of_job_row": recorded == api.binding(world.store.data[api.BUCKET_JOBS, job_id]),
                                      "keys": sorted(recorded)}
    cases["status_view_omits_repository"] = "repository" not in world.fleet.status()["jobs"][0]
    cases["records"] = records(world.store)
    cases["canary_or_root_in_second"] = CANARY in json.dumps(cases["tick_second"]) or ROOT in json.dumps(cases["tick_second"])

    # an exhausted backlog is idle: a repeated poll writes nothing
    world = World(api, [item("one")])
    world.tick()
    before, polls = store_digest(world.store), []
    for _ in range(3):
        polls.append(world.tick()["outcome"])
    cases["idle_polls"] = {"outcomes": polls, "store_unchanged": store_digest(world.store) == before}

    # a lost response and restarts keep exactly one durable identity
    world = World(api, [item("one")])
    load = world.load()
    cases["lost_first"] = world.tick(load)["job_id"]
    key = (api.BUCKET_INTENTS, "plan-1:one")
    settled = deepcopy(world.store.data[key])
    cases["lost_settled"] = {"state": settled["state"], "job_id": settled["job_id"]}
    world.store.data[key] = {**settled, "state": "intended", "enqueued_at": None}
    cases["lost_replay"] = world.tick(load)
    cases["lost_replay_state"] = world.store.data[key]["state"]
    cases["lost_replay_jobs"] = world.job_ids()
    world.store.data[key] = {**settled, "state": "intended", "enqueued_at": None}
    del world.store.data[api.BUCKET_JOBS, "op-one"]
    resumed = world.restart()
    cases["restart_before_enqueue"] = resumed.tick("plan-1", load)
    cases["restart_before_enqueue_jobs"] = world.job_ids()
    world.store.data[key] = {**settled, "state": "selected", "job_id": None, "job_binding": None, "job_manifest_sha256": None,
                             "goal_sha256": None, "base_revision": None, "link_state": "pending"}
    again = world.restart().tick("plan-1", load)
    cases["restart_before_read"] = again
    cases["restart_before_read_jobs"] = world.job_ids()
    cases["restart_before_read_intent"] = [world.store.data[key]["state"], world.store.data[key]["link_state"]]
    cases["lost_records"] = records(world.store)

    # a stale pin recorded on an intent refuses that item at selection
    world = World(api, [item("one"), item("other", priority=20)])
    world.tick()
    key = (api.BUCKET_INTENTS, "plan-1:one")
    world.store.data[key] = {**world.store.data[key], "manifest_revision": "8" * 40}
    result = world.tick()
    cases["stale_pin_tick"] = result
    cases["stale_pin_view"] = item_view(world, "plan-1", "one")

    # pauses
    world = World(api, [item("one")], enabled=False)
    cases["plan_paused"] = world.tick()
    cases["plan_paused_intents"] = world.bucket_keys(api.BUCKET_INTENTS)
    world.coordinator.register(plan(api, [item("one")]), pin(sha256="1" * 64))
    world.fleet.pause()
    cases["fleet_paused"] = world.tick()
    cases["fleet_paused_jobs"] = world.bucket_keys(api.BUCKET_JOBS)
    cases["status_fleet_paused"] = world.coordinator.status("plan-1")["fleet_paused"]
    world.fleet.resume()
    cases["after_resume"] = world.tick()["outcome"]

    # a failed dependency blocks only its dependents
    items = [item("one"), item("two", priority=20, dependencies=["one"]), item("independent", lane="b", priority=30)]
    world = World(api, items)
    load = world.load()
    cases["failed_dep_first"] = world.tick(load)["item_id"]
    world.settle("op-one", FAILED)
    cases["failed_dep_moved"] = world.tick(load)
    cases["failed_dep_blocked"] = world.tick(load)
    cases["failed_dep_jobs"] = sorted(world.job_ids())
    cases["failed_dep_status"] = world.coordinator.status("plan-1")
    return {"tick": cases}


def d_conflict(api) -> dict:
    cases = {}
    # an equal job id with another binding is a conflict for the owner
    world = World(api, [item("one"), item("other", priority=20)])
    world.fleet.enqueue("b", manifest(api, "op-one", ["docs/elsewhere.md"]), GOAL, [])
    before = deepcopy(world.store.data[api.BUCKET_JOBS, "op-one"])
    digest_before = store_digest(world.store)
    conflict = world.tick()
    cases["binding_conflict_tick"] = conflict
    cases["binding_conflict_digest_before_after"] = [digest_before, store_digest(world.store)]
    cases["binding_conflict_job_unchanged"] = world.store.data[api.BUCKET_JOBS, "op-one"] == before
    cases["binding_conflict_intent"] = world.intent("one")
    cases["binding_conflict_moved"] = world.tick()

    # a crash before the enqueue cannot adopt a foreign job or unlock a successor
    same = manifest(api, "op-one", ["docs/one.md"])
    foreign = [("another_lane_and_repository", "b", same, False), ("another_repository_alone", "b", same, True),
               ("another_frozen_manifest", "a", manifest(api, "op-one", ["docs/elsewhere.md"]), False)]
    for label, lane, document, shared in foreign:
        world = World(api, [item("one"), item("two", priority=20, dependencies=["one"])], shared=shared)
        world.fleet.enqueue(lane, document, GOAL, [])
        world.settle("op-one", ACCEPTED)
        intended = {**api.new_intent("plan-1", item("one"), NOW), "state": "intended", "job_id": "op-one", "job_manifest_sha256": "0" * 64,
                    "job_binding": api.expected_binding("a", lane_identity(api, "a"), "0" * 64, [], GOAL)}
        world.store.data[api.BUCKET_INTENTS, "plan-1:one"] = intended
        result = world.tick()
        cases["foreign_" + label] = {"tick": result, "intent_state": world.intent("one")["state"], "jobs": world.job_ids(),
                                     "intent_keys": world.bucket_keys(api.BUCKET_INTENTS)}

    # an intent without a complete recorded binding reconciles nothing
    world = World(api, [item("one")])
    world.fleet.enqueue("a", manifest(api, "op-one", ["docs/one.md"]), GOAL, [])
    world.store.data[api.BUCKET_INTENTS, "plan-1:one"] = {**api.new_intent("plan-1", item("one"), NOW), "state": "intended", "job_id": "op-one",
                                                          "job_binding": None}
    cases["no_binding_tick"] = world.tick()
    cases["no_binding_intent_state"] = world.intent("one")["state"]

    # a job row carrying another goal settles the open intent as a conflict
    world = World(api, [item("one")])
    world.tick()
    key = (api.BUCKET_INTENTS, "plan-1:one")
    recorded = deepcopy(world.store.data[key]["job_binding"])
    recorded["goal"]["sha256"] = "f" * 64
    world.store.data[key] = {**world.store.data[key], "state": "intended", "job_binding": recorded}
    cases["other_goal_tick"] = world.tick()
    cases["other_goal_state"] = world.store.data[key]["state"]

    # a recorded identity other than the one this tick computes
    world = World(api, [item("one")])
    world.tick()
    key = (api.BUCKET_INTENTS, "plan-1:one")
    world.store.data[key] = {**world.store.data[key], "state": "selected", "job_id": "op-recorded-other"}
    cases["intent_identity_tick"] = world.tick()
    cases["intent_identity_intent"] = world.intent("one")

    # the job row vanished between the enqueue and the confirmation (job_missing)
    world = World(api, [item("one")])
    original = world.coordinator.fleet.enqueue

    def vanishing(lane, manifest_document, goal, dependencies):
        result = original(lane, manifest_document, goal, dependencies)
        del world.store.data[api.BUCKET_JOBS, result["job"]["id"]]
        return result
    world.coordinator.fleet.enqueue = vanishing
    cases["job_missing_tick"] = world.tick()
    cases["job_missing_intent"] = world.intent("one")
    return {"conflict": cases}


def e_deferral(api) -> dict:
    cases = {}
    items = [item("one"), item("independent", lane="b", priority=20)]
    world = World(api, items)
    outage = world.load(outages={"one"})
    first = world.tick(outage)
    cases["first_outage"] = first
    cases["first_intent"] = {k: world.intent("one")[k] for k in ("attempts", "defer_ticks", "state", "deferrals", "reason_code", "error_type")}
    moved = world.tick(outage)
    cases["independent_moves"] = moved
    cases["countdown"] = world.intent("one")["defer_ticks"]
    again = world.tick(outage)
    cases["retried_after_wait"] = again
    cases["attempts_after"] = world.intent("one")["attempts"]
    cases["job_one_absent"] = [k for k in world.bucket_keys(api.BUCKET_JOBS) if k == "op-one"]
    resumed = world.restart()
    cases["restart_ticks"] = [resumed.tick("plan-1", outage)["outcome"] for _ in range(2)]
    cases["recovered"] = resumed.tick("plan-1", world.load())
    cases["recovered_jobs"] = sorted(world.job_ids())
    cases["recovered_intent"] = [world.intent("one")["deferrals"], world.intent("one")["defer_ticks"]]
    cases["records"] = records(world.store)

    # a permanently unavailable item: bounded retries, then the owner
    items = [item("one"), item("two", priority=20, dependencies=["one"]), item("independent", lane="b", priority=30)]
    observer = FakeObserver()
    world = World(api, items, observer=observer)
    outage = world.load(outages={"one"})
    outcomes = [world.tick(outage)["outcome"] for _ in range(30)]
    cases["permanent_outcomes"] = {"unavailable": outcomes.count("unavailable"), "sequence": outcomes, "max_deferrals": api.MAX_DEFERRALS}
    row = world.intent("one")
    cases["permanent_row"] = {k: row[k] for k in ("state", "reason_code", "error_type", "deferrals")}
    cases["permanent_independent_admitted"] = "op-independent" in world.job_ids()
    cases["permanent_last"] = world.tick(outage)
    cases["permanent_view"] = item_view(world, "plan-1", "one")
    cases["permanent_events"] = observer.records

    # a non-exception-type error name is not relayed
    world = World(api, [item("one")])

    class Odd(Exception):
        pass
    Odd.__name__ = "not a token!"

    def odd(_item):
        raise Odd("x")
    cases["unsafe_error_type"] = world.tick(odd)

    # two definite refusals block the item
    world = World(api, [item("one"), item("other", priority=20)])
    refusals = {"one": "manifest_pin_mismatch"}
    cases["refused_first"] = world.tick(world.load(refusals=refusals))
    cases["refused_second"] = world.tick(world.load(refusals=refusals))
    cases["refused_state"] = world.intent("one")["state"]
    cases["refused_moved"] = world.tick(world.load(refusals=refusals))
    corrected = plan(api, [item("one"), item("other", priority=20), item("one-fixed", priority=30)])
    cases["refused_corrected_register"] = call(world.coordinator.register, corrected, pin(revision="9" * 40))
    cases["refused_admitted"] = world.tick(world.load(refusals=refusals))
    cases["refused_history"] = [world.intent("one")["state"], world.intent("one")["reason_code"]]

    # a dependency without a job id, and a loader that names no repository
    world = World(api, [item("one"), item("two", priority=20, dependencies=["one"])])
    world.tick()
    world.settle("op-one", ACCEPTED)
    key = (api.BUCKET_INTENTS, "plan-1:one")
    world.store.data[key] = {**world.store.data[key], "job_id": None}
    cases["dependency_job_missing"] = world.tick()
    for label, repository in (("none", None), ("empty", ""), ("not_str", 7)):
        sub = World(api, [item("one")])
        base = sub.load()(item("one"))
        cases["repository_identity_" + label] = sub.tick(sub.load(overrides={"one": {**base, "repository": repository}}))

    # a fleet refusal of the enqueue is recorded and corrupts no queued job
    world = World(api, [item("one", lane="zzz")])
    cases["enqueue_refused"] = world.tick()
    cases["enqueue_refused_jobs"] = world.bucket_keys(api.BUCKET_JOBS)
    cases["enqueue_refused_attempts"] = world.intent("one")["attempts"]
    return {"deferral": cases}


def f_link(api) -> dict:
    cases = {}
    # an outage leaves a durable pending linkage that resumes and unlocks nothing
    items = [item("one"), item("two", priority=20, dependencies=["one"])]
    broken = FakePortfolio(api, "outage")
    world = World(api, items, portfolio=broken)
    outage = world.tick()
    cases["outage_tick"] = outage
    cases["outage_jobs"] = world.job_ids()
    cases["outage_bindings"] = broken.bindings
    world.settle("op-one", ACCEPTED)
    cases["accepted_but_unlinked"] = world.tick()
    cases["unlinked_view"] = item_view(world, "plan-1", "one")
    cases["unlinked_counts"] = world.coordinator.status("plan-1")["plans"][0]["counts"]
    healthy = FakePortfolio(api)
    resumed = world.restart(portfolio=healthy)
    cases["linked_tick"] = resumed.tick("plan-1", world.load())
    cases["linked_bindings"] = healthy.bindings
    cases["linked_jobs"] = world.job_ids()
    cases["successor_tick"] = resumed.tick("plan-1", world.load())

    # an existing different binding is a conflict and is never rewritten
    portfolio = FakePortfolio(api, "conflict")
    world = World(api, [item("one"), item("other", lane="b", priority=20)], portfolio=portfolio)
    cases["conflict_tick"] = world.tick()
    cases["conflict_view"] = item_view(world, "plan-1", "one")
    portfolio.mode = "ok"
    cases["conflict_moved"] = world.tick()
    cases["conflict_calls"] = portfolio.calls

    # a definite refusal of the binding owner blocks the linkage
    portfolio = FakePortfolio(api, "refused")
    world = World(api, [item("one"), item("other", lane="b", priority=20)], portfolio=portfolio)
    cases["refused_tick"] = world.tick()
    cases["refused_view"] = item_view(world, "plan-1", "one")
    cases["refused_next"] = world.tick()
    cases["refused_records"] = records(world.store)

    # without a binding owner no tick reports a linked success
    world = World(api, [item("one")], portfolio=None)
    cases["absent_tick"] = world.tick()
    cases["absent_jobs"] = world.job_ids()
    cases["absent_again"] = world.tick()
    cases["absent_intent"] = {k: world.intent("one")[k] for k in ("link_state", "link_reason", "deferrals", "defer_ticks")}

    # a linkage outage that exhausts its deferrals blocks the linkage
    portfolio = FakePortfolio(api, "outage")
    world = World(api, [item("one")], portfolio=portfolio)
    sequence = [world.tick()["outcome"] for _ in range(40)]
    cases["link_exhaustion"] = {"outcomes": sequence, "intent": {k: world.intent("one")[k] for k in ("link_state", "link_reason", "deferrals",
                                                                                                    "defer_ticks", "state")}}
    portfolio.mode = "ok"
    cases["link_after_exhaustion"] = world.tick()

    # an already linked intent is not bound again (the link action)
    portfolio = FakePortfolio(api)
    world = World(api, [item("one")], portfolio=portfolio)
    world.tick()
    cases["linked_calls_first"] = list(portfolio.calls)
    cases["linked_again"] = world.tick()
    cases["linked_calls_after"] = list(portfolio.calls)
    return {"link": cases}


def g_status_observe(api) -> dict:
    cases = {}
    world = World(api, [item("one"), item("two", priority=20, dependencies=["one"])])
    world.tick()
    world.settle("op-one", ACCEPTED)
    world.tick()
    projection = world.coordinator.status("plan-1")
    [view] = projection["plans"]
    cases["status_plan"] = projection
    cases["status_all"] = world.coordinator.status()
    cases["status_item_keys"] = sorted(view["items"][0])
    cases["status_no_delivery_claim"] = "merge" not in json.dumps(view["items"]) and "deployed" not in json.dumps(view["items"])
    text = json.dumps(projection)
    cases["status_no_leak"] = CANARY not in text and ROOT not in text and "lane_a" not in text
    cases["status_unregistered"] = guarded(world.store, world.coordinator.status, "plan-other")

    # the logged transitions carry identities only
    capture = LogCapture()
    logger = api.LOGGER
    previous = logger.level
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    try:
        world = World(api, [item("one"), item("two", priority=20)])
        world.tick()
        for _ in range(api.MAX_ATTEMPTS):
            world.tick(world.load(refusals={"two": "manifest_refused"}))
        world.tick()
        cases["log_lines"] = capture.lines
        joined = "\n".join(line[1] for line in capture.lines)
        cases["log_no_leak"] = CANARY not in joined and ROOT not in joined and "docs/GOAL.md" not in joined
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous)

    # the fixed structured transitions reach the observation port
    observer = FakeObserver()
    world = World(api, [item("one"), item("outage", lane="b", priority=20), item("bad", priority=30)], observer=observer)
    failing = world.load(outages={"outage"}, refusals={"bad": "manifest_refused"})
    healthy = world.load()
    steps = [("admitted", healthy), ("outage_unavailable", failing), ("bad_refused", failing), ("outage_again_silent", failing),
             ("bad_admitted", healthy), ("deferred_wait_silent", healthy), ("outage_recovered", healthy), ("exhausted_silent", healthy)]
    cases["observe_steps"] = []
    for name, loader in steps:
        result = world.tick(loader)
        cases["observe_steps"].append([name, result["outcome"], result["item_id"], len(observer.records)])
    cases["observe_events"] = observer.records
    cases["observe_leak"] = any(w in json.dumps(observer.records) for w in (CANARY, ROOT, "docs/GOAL.md", "injected", "lane_a"))

    # a conflict and a link conflict reach the observer as refused
    observer = FakeObserver()
    portfolio = FakePortfolio(api, "conflict")
    world = World(api, [item("one")], observer=observer, portfolio=portfolio)
    world.tick()
    cases["observe_link_conflict"] = observer.records
    observer = FakeObserver()
    world = World(api, [item("one"), item("other", priority=20)], observer=observer)
    world.fleet.enqueue("b", manifest(api, "op-one", ["docs/elsewhere.md"]), GOAL, [])
    world.tick()
    cases["observe_binding_conflict"] = observer.records

    # no store transaction is ever opened inside another one
    world = World(api, [item("one"), item("two", priority=20, dependencies=["one"])])
    world.tick()
    world.settle("op-one", ACCEPTED)
    world.tick()
    world.coordinator.status("plan-1")
    world.coordinator.status()
    cases["no_nested_transaction"] = {"depth": world.store.depth, "transactions_over_six": world.store.transactions > 6}
    return {"status_observe": cases}


def fleet_backlog(api) -> dict:
    groups = {}
    for step in (a_surface, b_plan, c_tick, d_conflict, e_deferral, f_link, g_status_observe):
        groups.update(step(api))
    return {**groups, "m7_tests": M7_TESTS, "cases_per_group": {k: len(v) for k, v in groups.items()}}
