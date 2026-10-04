"""S10 round-1 correction F2-B (FLEET-REBUILD-S10-ACCEPT F2 rows 1 and 2): the owner-actions declined path and the frontdesk and
research-dispatch queue waits, each driven through its REAL composition builder with fixture stores and a recording observer behind
the catalog-checking wrapper (a non-catalog attribute fails the test); no provider, process, Git network or PostgreSQL.

Wired here: `entry.cli.owner_actions` tick/run -> `composition.owner_actions.process_observer` (own component `owner-actions`) ->
`coordinator(observer=)` -> the scheduler's `path_declined`; `composition.cli_desk.build_runner` -> `composition.queue_waits.ObservedDesk`;
`composition.cli_research_program.research_program(observer=)` -> the `ObservedResearchProgram` wrapper. Not wired, reported to the owner:
the Fleet runner's declined-path observer (`composition.cli_fleet`), whose only pin-safe form needs a ported-fixture edit.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_s10_a5_2_seams import declined, observed, only
from test_s10_c8b3_owner_actions import args, fleet_config, root, settings, wiring  # noqa: F401

from codex_harness import composition
from codex_harness.composition import (
    cli,
    cli_bus,
    cli_desk,
    cli_research_program,
    observation,
    operation,
    queue_waits,
)
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.application.owner_actions import scheduler as scheduler_module
from codex_harness.coordination.application.owner_actions.scheduler import OwnerActionScheduler
from codex_harness.observation.domain.feature_registry import FEATURES
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

PORTED = Path(__file__).resolve().parent / "ported"
REVISION = "0" * 39 + "a"
T0 = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def service(settings):  # noqa: F811
    return composition.ServiceHandle(MemoryStore(), packaged_organization())


def ref(value):
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


# ----- owner actions: the process path passes a process observer ---------------------------------------------------------
def owner_tick(service, monkeypatch, command, observer, **fields):
    """The shipped `entry.cli.owner_actions._execute` with its REAL `coordinator`: only the fleet registration read and the
    observer builder (which records the component it was asked for) are fixtures."""
    built = []
    monkeypatch.setattr(FleetRegistry, "registered", lambda self: {"config": fleet_config()})
    monkeypatch.setattr(observation, "build_observer", lambda store, component, **kw: built.append(component) or observer)
    with service.store.transaction() as tx:
        tx.put(scheduler_module.BUCKET_POLICIES, "p1", {"policy": {"enabled": False}, "pin": {}})
    return root._execute(service, args(command, **fields)), built


def test_the_tick_command_passes_its_own_process_observer_and_a_disabled_policy_emits_path_declined(service, monkeypatch):
    recorder, observer = observed()
    result, built = owner_tick(service, monkeypatch, "tick", observer, policy="p1")
    assert built == ["owner-actions"], "its own component: the `assess` child's `cli.owner-actions` spool is not reused"
    assert result["outcome"] == "disabled" and result["reason_code"] == "policy_disabled" and result["exit_code"] == 0
    assert only(recorder) == declined("owner_actions", "disabled")


def test_the_run_command_emits_once_per_tick_through_the_same_observer(service, monkeypatch):
    recorder, observer = observed()
    monkeypatch.setattr(wiring.time, "sleep", lambda seconds: None)
    result, built = owner_tick(service, monkeypatch, "run", observer, policy=["p1"], interval=1, max_ticks=2)
    assert built == ["owner-actions"] and result["ticks"] == 2
    assert recorder.events == [declined("owner_actions", "disabled")] * 2


def test_the_business_result_is_the_same_without_an_observer_and_the_other_commands_build_none(service, monkeypatch):
    recorder, observer = observed()
    with_observer, _ = owner_tick(service, monkeypatch, "tick", observer, policy="p1")
    without = wiring.coordinator(service, fleet_config(), {}, lanes=lambda lane_id: None, continuation=object())
    assert without.scheduler.observer is None  # the legacy optional observer absent: the seam is inert
    assert wiring.tick_policy(without, fleet_config(), "p1") == {key: value for key, value in with_observer.items()
                                                                  if key != "exit_code"}
    assert len(recorder.events) == 1
    built = []
    monkeypatch.setattr(observation, "build_observer", lambda store, component, **kw: built.append(component))
    with pytest.raises(Exception):  # a document-less `migrate` still reads the file first: no observer was built for it
        root._execute(service, args("migrate", document=str(service.store) + ".absent"))
    assert built == []


def test_the_scheduler_declines_nothing_for_an_enabled_or_unregistered_policy(service):
    recorder, observer = observed()
    OwnerActionScheduler(service.store, observer=observer).tick("missing")
    assert recorder.events == []


# ----- frontdesk: the claim through the real build_runner ----------------------------------------------------------------
@pytest.fixture
def desk_runner(monkeypatch, settings):  # noqa: F811
    monkeypatch.setattr(operation, "build_executor", lambda *a, **k: "executor")
    monkeypatch.setattr(cli_bus, "bus", lambda: "bus")
    monkeypatch.setattr(cli, "workflow", lambda handle: "workflow")
    monkeypatch.setattr(observation, "build_collector", lambda store, seen: "collector")

    def build(observer, enqueued=T0, claimed="2026-01-01T00:00:30+00:00"):
        handle = composition.ServiceHandle(MemoryStore(), packaged_organization())
        runner = cli_desk.build_runner(handle, SimpleNamespace(revision=REVISION), observer)
        desk = runner.desk._desk
        desk.token = lambda: "owner-token"
        desk.clock = lambda: enqueued
        session = "123e4567-e89b-42d3-a456-426614174000"
        desk.create_session({"session_id": session, "title": "t"})
        request = desk.submit({"session_id": session, "request_id": "223e4567-e89b-42d3-a456-426614174000",
                               "intent": "consult", "text": "hello"})["request"]["id"]
        desk.clock = lambda: claimed
        return runner, handle, request
    return build


def test_a_desk_request_queued_at_t_and_claimed_at_t_plus_30_emits_one_wait_and_the_claim_is_unchanged(desk_runner):
    recorder, observer = observed()
    runner, handle, request = desk_runner(observer)
    claimed = runner.desk.claim_next()
    assert claimed["id"] == request and claimed["status"] == "dispatching" and claimed["owner_token"] == "owner-token"
    assert only(recorder) == ("operations.queue_item_waited", "observed", {
        "queue": "frontdesk", "item_ref": ref(request), "wait_seconds": 30.0, "outcome": "started"})
    assert runner.desk.claim_next() is None and len(recorder.events) == 1, "no second claim, no second observation"


def test_the_claim_result_and_the_store_rows_are_identical_with_and_without_the_observer(desk_runner):
    runs = []
    for observer in (observed()[1], None):
        runner, handle, request = desk_runner(observer)
        row = runner.desk.claim_next()
        runs.append((row, deepcopy(handle.store.data)))
    assert runs[0] == runs[1] and runs[0][0]["status"] == "dispatching"


@pytest.mark.parametrize("enqueued", ["2026-01-01T00:00:00", "not a time", None, "2026-01-01T00:01:00+00:00"])
def test_an_unknown_or_later_enqueue_time_emits_nothing_and_the_row_is_still_returned(desk_runner, enqueued):
    recorder, observer = observed()
    runner, handle, request = desk_runner(observer)
    runner.desk._desk = SimpleNamespace(claim_next=lambda: {"id": "r1", "created_at": enqueued,
                                                             "dispatched_at": "2026-01-01T00:00:30+00:00"})
    assert runner.desk.claim_next()["id"] == "r1"
    assert recorder.events == []


def test_an_idle_claim_emits_nothing_and_the_wrapper_delegates_every_other_desk_method(desk_runner):
    recorder, observer = observed()
    runner, handle, request = desk_runner(observer)
    assert runner.desk.request(request)["status"] == "queued" and runner.desk.dispatching() == []
    runner.desk._desk = SimpleNamespace(claim_next=lambda: None)
    assert runner.desk.claim_next() is None and recorder.events == []


# ----- research dispatch: the claim through the real research_program builder ---------------------------------------------
def test_the_builder_without_an_observer_is_the_plain_program_and_with_one_the_wrapper():
    from codex_harness.research.application.research_program import ResearchProgram

    plain = cli_research_program.research_program(MemoryStore())
    assert type(plain) is ResearchProgram
    _, observer = observed()
    wrapped = cli_research_program.research_program(MemoryStore(), token=lambda: "o", observer=observer)
    assert isinstance(wrapped, ResearchProgram) and type(wrapped) is not ResearchProgram
    assert wrapped.token() == "o" and wrapped._observer is observer


HEAD = "a" * 40
SOURCE = {"topic": "storage", "project_ids": ["ops"], "reason_codes": ["store_timeout"]}
DEFINITIONS = {"schema": "urn:zeus:portfolio-definitions:1", "projects": [
    {"id": "ops", "title": "Operations", "outcome": "bound fleet work completes", "source_ref": "docs/GOAL.md",
     "criteria": [{"id": "c1", "text": "jobs reach a terminal accepted state"}]}]}


def research_config():
    return {"schema": "urn:zeus:research-program:1", "id": "rp-001", "base_revision": HEAD,
            "deadline": "2029-06-01T00:00:00+00:00", "interval_seconds": 3600, "max_cycles": 2, "max_adoptions": 1,
            "budget": {"per_host": 10, "total": 20}, "topics": [{"id": "storage", "keywords": ["postgres"]}],
            "local_candidates": [], "investigation_source": dict(SOURCE),
            "template": {"schema": "urn:zeus:autonomous:2", "id": "council-template", "base_revision": HEAD,
                         "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "rationale": "r"},
                         "plan": {"objective": "improve the research report", "acceptance_criteria": ["focused tests pass"],
                                  "allowed_paths": ["docs/RUNBOOK.md"]},
                         "budget": {"per_host": 10, "total": 20},
                         "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1},
                         "deadline": "2030-01-01T00:00:00+00:00",
                         "research": {"topic": "research report", "questions": ["What is the SSOT?"], "search_scope": ["docs"]},
                         "current_state": {"records": [{"bucket": "tasks", "id": "t-1"}], "max_age_seconds": 600}}}


def research_scenario(observer):
    """Two cycles over the program the composition builds: the investigation is first synthesized as an eligible candidate while
    the machine ledger leaves no headroom (nothing is claimed), and claimed in the next cycle, 3600 s later, once headroom exists."""
    from codex_harness.coordination.application.fleet.state import BUCKET_JOBS
    from codex_harness.intake.application.portfolio import Portfolio
    from codex_harness.research.application.program_state import ProgramState
    from codex_harness.research.application.research_program import BUCKET_DISPATCHES
    from codex_harness.research.domain.research_program import validate_config

    store, now = MemoryStore(), {"value": T0}

    def clock():
        return now["value"]

    with store.transaction() as tx:
        for job in ("j-1", "j-2"):
            tx.put(BUCKET_JOBS, job, {"id": job, "lane": "lane-1", "status": "failed", "reason_code": "store_timeout",
                                      "error_type": None, "updated_at": T0})
    owner = Portfolio(store, DEFINITIONS, clock=clock)
    for job in ("j-1", "j-2"):
        owner.bind(job, "ops", "c1")
    owner.reconcile()
    programs = cli_research_program.research_program(store, token=lambda: "owner", observer=observer)
    programs.clock, programs.state = clock, ProgramState(store, clock)
    programs.register(validate_config(research_config(), cli_research_program.packaged_policy()), "repo-identity", [])
    programs.resume("rp-001")
    claims = []
    for ledger, instant in ((10 ** 6, T0), (0, "2026-01-01T01:00:00+00:00")):
        now["value"] = instant
        cycle = programs.reserve_cycle("rp-001", "repo-identity")["cycle"]
        counts = {"host": "fixture", "this_host": ledger, "all_hosts": ledger, "unreadable": 0}
        claims.append(programs.record_collection(cycle["id"], "owner", {}, [], counts))
        if claims[-1]["candidate"] is None:
            programs.complete_cycle(cycle["id"], "owner")
    with store.transaction() as tx:
        rows = tx.scan(BUCKET_DISPATCHES)
    keys = ("id", "investigation", "program", "cycle", "candidate", "claimed_at", "job_ids", "snapshot_sha256")
    return claims, [{key: row[key] for key in keys} for row in rows]


def test_a_research_claim_made_one_hour_after_the_candidate_was_enqueued_emits_one_wait():
    recorder, observer = observed()
    claims, rows = research_scenario(observer)
    assert claims[0]["candidate"] is None and claims[1]["candidate"]["investigation"] == rows[0]["id"] and len(rows) == 1
    assert only(recorder) == ("operations.queue_item_waited", "observed", {
        "queue": "research_dispatch", "item_ref": ref(rows[0]["id"]), "wait_seconds": 3600.0, "outcome": "started"})


def test_the_research_claim_and_the_dispatch_rows_are_identical_without_an_observer():
    recorder, observer = observed()
    with_observer, without = research_scenario(observer), research_scenario(None)
    assert with_observer[1] == without[1] and with_observer[0][1]["candidate"] == without[0][1]["candidate"]
    assert len(recorder.events) == 1


def test_a_refused_collection_commits_no_claim_and_emits_nothing():
    recorder, observer = observed()
    programs = cli_research_program.research_program(MemoryStore(), observer=observer)
    with pytest.raises(Exception):
        programs.record_collection("unknown-cycle", "owner", {}, [], {})
    assert recorder.events == [] and programs._claims == []


@pytest.mark.parametrize("enqueued, claimed", [(None, T0), ("2026-01-01T00:00:00", T0), (T0, "garbage"),
                                               ("2026-01-02T00:00:00+00:00", T0)])
def test_a_wait_without_two_aware_ordered_instants_emits_nothing(enqueued, claimed):
    recorder, observer = observed()
    queue_waits.emit_queue_wait(observer, "research_dispatch", "inv", enqueued, claimed)
    assert recorder.events == [] and queue_waits.queue_wait_seconds(enqueued, claimed) is None
    queue_waits.emit_queue_wait(None, "research_dispatch", "inv", T0, T0)  # no observer: inert


def test_registry_rows_stay_instrumented_with_their_wired_producers():
    assert FEATURES["queue_wait"].instrumented and FEATURES["queue_wait"].seam is None
    assert FEATURES["declined_paths"].instrumented and FEATURES["declined_paths"].seam is None
