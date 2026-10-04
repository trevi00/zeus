"""S10 A5-2: the X1b/X5b producer seams of DESIGN-s10 §17 (R-a52): `capacity_refused`, `skill_selected`, `path_declined`.

MemoryStore, a recording observer behind the catalog-checking wrapper (a non-catalog attribute refuses and fails the test);
no provider, process, Git or PostgreSQL. Every seam is an optional `observer=None` (the composer's is a class attribute: the
S8 pin fixes `ContextComposer.__init__`); with None the outcome is the same and nothing is emitted.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from test_s10_c5b1_executor import _executor
from test_s10_c5b1_executor import settings as executor_settings  # noqa: F401
from test_s10_c8b2_fleet import FakeRunner, fakes, registered, service, settings  # noqa: F401

from codex_harness.composition import cli_fleet, fleet_backlog
from codex_harness.composition import continuation as wiring
from codex_harness.composition.continuation import continuation_owners
from codex_harness.composition.managed_runtime import fixture_config, fixture_manifest
from codex_harness.composition.owner_actions import owner_action_owners
from codex_harness.context.application.compose import ContextComposer
from codex_harness.context.domain.packet import ContextItem
from codex_harness.coordination.application.continuation.tick import ContinuationTick
from codex_harness.coordination.application.fleet.admission import AdmissionControl
from codex_harness.coordination.application.fleet.pause import FleetPause
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.application.fleet.runner import FleetRunner
from codex_harness.coordination.application.owner_actions import scheduler as scheduler_module
from codex_harness.coordination.application.owner_actions.scheduler import OwnerActionScheduler
from codex_harness.coordination.domain.fleet import FleetRefused
from codex_harness.delivery.application.host_delivery.controller import DeliveryController
from codex_harness.observation.application.catalog_observer import CatalogCheckingObserver
from codex_harness.observation.domain.feature_registry import FEATURES
from codex_harness.storage.adapters.memory_store import MemoryStore


class Recorder:
    """The inner observer: records; a catalog refusal (`_refused`) fails the test instead of being swallowed."""

    def __init__(self):
        self.events = []

    def emit(self, event_type, outcome, **fields):
        self.events.append((event_type, outcome, fields.get("attributes")))

    def _refused(self, event_type, exc):
        raise AssertionError(f"{event_type} left the catalog: {exc}")

    @property
    def types(self):
        return [event[0] for event in self.events]


def observed():
    recorder = Recorder()
    return recorder, CatalogCheckingObserver(recorder)


def only(recorder):
    assert len(recorder.events) == 1, recorder.events
    return recorder.events[0]


# ----- capacity_refused -------------------------------------------------------------------------------------------------
UNIT1, UNIT2 = "1" * 64, "2" * 64
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "fixture", "base_revision": "a" * 40, "bytes": 7}


def fleet(tmp_path, observer=None, max_parallel=1, jobs=("j1", "j2")):
    store = MemoryStore()
    registry, admission = FleetRegistry(store), AdmissionControl(store, observer=observer)
    config = fixture_config(tmp_path)
    lane = config["lanes"][0]
    config["lanes"] = [lane, {**lane, "id": "spare", "schema": "lane_spare", "redis_namespace": "spare",
                              "runtime": lane["runtime"] + "-spare"}]  # max_parallel may not exceed the lanes
    registry.register({**config, "max_parallel": max_parallel})
    for job_id in jobs:
        registry.enqueue("fixture", fixture_manifest(job_id), GOAL, [])
    return admission


def test_a_job_behind_max_parallel_emits_unit_limit_once_per_new_reason(tmp_path):
    recorder, observer = observed()
    admission = fleet(tmp_path, observer)
    first = admission.admit_one()  # j1 takes the slot; j2 sees it taken in the same decision
    assert first["job"]["id"] == "j1" and first["blocked"] == {"j2": "capacity"}
    blocked = admission.admit_one()
    assert blocked["job"] is None and blocked["blocked"] == {"j2": "capacity"}
    assert only(recorder) == ("operations.capacity_refused", "blocked",
                              {"scope": "fleet_unit", "refusal_reason": "unit_limit", "retry_after_seconds": None})
    assert admission.admit_one()["blocked"] == {"j2": "capacity"} and len(recorder.events) == 1  # an idle poll: nothing


def test_a_job_behind_its_busy_lane_emits_lane_full(tmp_path):
    recorder, observer = observed()
    admission = fleet(tmp_path, observer, max_parallel=2)
    assert admission.admit_one()["blocked"] == {"j2": "lane_busy"}
    assert only(recorder) == ("operations.capacity_refused", "blocked",
                              {"scope": "lane_slots", "refusal_reason": "lane_full", "retry_after_seconds": None})


def test_a_unit_reservation_over_max_parallel_emits_then_raises_as_before(tmp_path):
    recorder, observer = observed()
    admission = fleet(tmp_path, observer, jobs=())
    assert admission.reserve_unit(UNIT1, "conductor", "fixture", "subject")["cached"] is False and recorder.events == []
    with pytest.raises(FleetRefused) as with_observer:
        admission.reserve_unit(UNIT2, "conductor", "fixture", "subject")
    assert only(recorder) == ("operations.capacity_refused", "blocked",
                              {"scope": "fleet_unit", "refusal_reason": "unit_limit", "retry_after_seconds": None})
    plain = fleet(tmp_path, None, jobs=())
    plain.reserve_unit(UNIT1, "conductor", "fixture", "subject")
    with pytest.raises(FleetRefused) as without:
        plain.reserve_unit(UNIT2, "conductor", "fixture", "subject")
    assert (str(with_observer.value), with_observer.value.args) == (str(without.value), without.value.args)


def test_without_an_observer_the_admission_outcome_is_unchanged_and_nothing_is_emitted(tmp_path):
    outcomes = []
    for observer in (observed()[1], None):
        admission = fleet(tmp_path, observer)
        outcomes.append((admission.admit_one()["blocked"], admission.admit_one()["blocked"]))
    assert outcomes[0] == outcomes[1] == ({"j2": "capacity"}, {"j2": "capacity"})
    assert AdmissionControl(MemoryStore()).observer is None


def test_cli_fleet_hands_admission_only_an_observer_it_already_built(service, registered, settings, fakes,  # noqa: F811
                                                                      monkeypatch):
    cli_fleet.run_fleet(service, SimpleNamespace(once=True))  # no host settings: no observer, none passed
    assert fakes.observers == [] and FakeRunner.built[0].args[1].observer is None
    assert FakeRunner.built[0].ports["observer"] is None  # S10 F2: no settings, so the runner has no observer either
    settings[fleet_backlog.PLAN_SETTING] = "plan-1"
    settings[wiring.POLICY_SETTING] = "p1"
    monkeypatch.setattr(fleet_backlog, "backlog_ticker", lambda *a, **k: "backlog-tick")
    monkeypatch.setattr(wiring, "continuation_ticker", lambda *a, **k: "continuation-tick")
    cli_fleet.run_fleet(service, SimpleNamespace(once=True))
    assert fakes.observers == ["fleet-backlog", "fleet-continuation", "fleet-runner"]  # S10 F2
    assert FakeRunner.built[1].args[1].observer == ("observer", "fleet-backlog")
    # S10 F2: the runner's own observer (component fleet-runner), never the backlog one whose exact spool list M7 pins
    assert FakeRunner.built[1].ports["observer"] == ("observer", "fleet-runner")


# ----- skill_selected ---------------------------------------------------------------------------------------------------
def skill_ref(item_id):
    return "sha256:" + hashlib.sha256(item_id.encode("utf-8")).hexdigest()


def packet(*ids):
    return SimpleNamespace(evidence=[{"id": item_id} for item_id in ids])


def skills(*ids):
    return [ContextItem(item_id, "body", "ref", "rev") for item_id in ids]


def test_one_event_per_selected_or_omitted_project_skill():
    recorder, observer = observed()
    composer = ContextComposer(None, "/a", None, None)
    assert composer.observer is None
    composer.observer = observer
    composer._emit_skill_selection(skills("project-skill:a/x.md", "project-skill:b/y.md"),
                                   packet("project-skill:a/x.md", "other-evidence"))
    assert recorder.events == [
        ("development.skill_selected", "observed",
         {"skill_ref": skill_ref("project-skill:a/x.md"), "selected": True, "selection_reason": "other"}),
        ("development.skill_selected", "observed",
         {"skill_ref": skill_ref("project-skill:b/y.md"), "selected": False, "selection_reason": "other"})]
    assert "/" not in recorder.events[0][2]["skill_ref"]  # the path never enters the attributes


def test_no_skills_no_event_and_no_observer_no_emit():
    recorder, observer = observed()
    composer = ContextComposer(None, "/a", None, None)
    composer.observer = observer
    composer._emit_skill_selection([], packet())
    assert recorder.events == []
    ContextComposer(None, "/a", None, None)._emit_skill_selection(skills("project-skill:a"), packet())  # None: returns


def test_compose_emits_after_the_packet_and_the_result_is_the_same_without_an_observer():
    from test_s4_composer_turn_loop import Artifacts, Repository, request

    class Selector:
        def select(self, cwd, revision, objective):
            return skills("project-skill:a/x.md"), {"selected": 1}

    recorder, observer = observed()
    watched = ContextComposer(Artifacts(), "/a", Repository(), Selector())
    watched.observer = observer
    plain = ContextComposer(Artifacts(), "/a", Repository(), Selector())
    with_observer, without = watched.compose(request()), plain.compose(request())
    assert with_observer.rendered == without.rendered and with_observer.binding == without.binding
    attributes = only(recorder)[2]
    assert attributes == {"skill_ref": skill_ref("project-skill:a/x.md"), "selected": True, "selection_reason": "other"}


def test_the_operation_composition_injects_its_observer_into_the_composer(tmp_path, executor_settings):  # noqa: F811
    executor = _executor(tmp_path)
    assert executor.run_task.composer.observer is executor.observer


# ----- path_declined ----------------------------------------------------------------------------------------------------
def declined(feature, reason):
    return ("operations.path_declined", "observed", {"feature": feature, "decline_reason": reason})


def frames_of(row):
    return SimpleNamespace(policy=lambda policy_id: row)


def test_a_continuation_tick_of_an_unregistered_or_disabled_policy_emits_and_returns_the_same():
    results = []
    for row, expected in ((None, ("not_applicable", "policy_unregistered")),
                          ({"policy": {"enabled": False}}, ("disabled", "policy_disabled"))):
        recorder, observer = observed()
        with_observer = ContinuationTick(MemoryStore(), frames=frames_of(row), observer=observer).tick("p1")
        without = ContinuationTick(MemoryStore(), frames=frames_of(row)).tick("p1")
        assert with_observer == without and with_observer["reason_code"] == expected[1]
        assert only(recorder) == declined("continuation", expected[0])
        results.append(with_observer["outcome"])
    assert results == ["disabled", "disabled"] and ContinuationTick(MemoryStore()).observer is None


def test_the_continuation_composition_passes_its_observer_to_the_tick():
    _, observer = observed()
    assert continuation_owners(MemoryStore(), observer=observer).tick.observer is observer
    assert continuation_owners(MemoryStore()).tick.observer is None


def test_an_owner_actions_tick_of_a_disabled_policy_emits_and_returns_the_same():
    def tick(observer):
        store = MemoryStore()
        with store.transaction() as tx:
            tx.put(scheduler_module.BUCKET_POLICIES, "p1", {"policy": {"enabled": False}, "pin": {}})
        scheduler = OwnerActionScheduler(store, observer=observer, clock=lambda: "2026-01-01T00:00:00+00:00")
        return scheduler.tick("p1")

    recorder, observer = observed()
    with_observer, without = tick(observer), tick(None)
    assert with_observer == without and with_observer["reason_code"] == "policy_disabled"
    assert only(recorder) == declined("owner_actions", "disabled")
    recorder, observer = observed()
    OwnerActionScheduler(MemoryStore(), observer=observer).tick("missing")  # unregistered: not this seam's path
    assert recorder.events == []


def test_the_owner_actions_composition_forwards_an_observer_but_no_live_caller_holds_one():
    _, observer = observed()
    assert owner_action_owners(MemoryStore(), observer=observer).scheduler.observer is observer
    assert owner_action_owners(MemoryStore()).scheduler.observer is None


def test_a_disabled_host_delivery_controller_emits_through_the_state_observer():
    sentinel = object()

    def act(observer):
        state = SimpleNamespace(observer=observer, result=lambda *args, **kwargs: (args, kwargs))
        controller = DeliveryController(MemoryStore(), enabled=False, state=state)
        return controller._act({"plan": {"plan": {"plan_id": "d1"}}, "intent": {"stage": sentinel}})

    recorder, observer = observed()
    with_observer, without = act(observer), act(None)
    assert with_observer[1] == without[1] and with_observer[0][2:] == without[0][2:]
    assert only(recorder) == declined("host_delivery", "disabled")
    enabled_recorder, enabled_observer = observed()
    state = SimpleNamespace(observer=enabled_observer, gate=lambda plan: (_ for _ in ()).throw(RuntimeError("stop")))
    with pytest.raises(RuntimeError):
        DeliveryController(MemoryStore(), enabled=True, state=state)._act(
            {"plan": {"plan": {"plan_id": "d1"}}, "intent": {"stage": "x"}})
    assert enabled_recorder.events == []  # an enabled controller declines nothing


def test_the_fleet_runner_declines_each_pass_it_was_built_without_once_per_run(tmp_path):
    idle = SimpleNamespace(budget_exhausted=lambda budget: False, wait=lambda handles, seconds: [])  # no job is queued

    def run(observer, **passes):
        store = MemoryStore()
        registry = FleetRegistry(store)
        registry.register(fixture_config(tmp_path))
        runner = FleetRunner(registry, AdmissionControl(store), FleetPause(store), launcher=idle, observer=observer,
                             **passes)
        return runner.run(once=True)

    recorder, observer = observed()
    summary = run(observer)
    assert recorder.events == [declined("fleet_reconcile", "disabled"), declined("fleet_backlog", "disabled"),
                               declined("continuation", "disabled")]
    assert run(None) == summary  # the same summary without an observer
    recorder, observer = observed()
    run(observer, reconcile=lambda: None, backlog=lambda: {}, continuation=lambda: {})
    assert recorder.events == []  # a configured pass is not declined
    assert FleetRunner(None, None, None, None).observer is None


# ----- the registry -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("feature, event", [("capacity_admission", "operations.capacity_refused"),
                                            ("skill_selection", "development.skill_selected"),
                                            ("declined_paths", "operations.path_declined")])
def test_the_three_features_are_instrumented_with_no_seam(feature, event):
    row = FEATURES[feature]
    assert row.instrumented is True and row.seam is None and row.proof_events == (event,)
