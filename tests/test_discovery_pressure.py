"""INV-DISCOVERY-PRESSURE-001 (T1a): proactive discovery pressure, matrix rows T1-01..T1-13 of FLEET-T1-SPEC.

Every Fleet, backlog and continuation row here is a labelled synthetic FIXTURE written straight into a MemoryStore
in the shape of the real buckets; no provider, model, network fetch or process runs. The thresholds come from a
fixture policy labelled `suggested_unconfirmed`, exactly like the packaged one, never from a library constant.
"""
import copy
from types import SimpleNamespace

import pytest

from codex_harness.adapters.discovery_pressure import packaged_policy
from codex_harness.adapters.observation_spool import MemorySpool
from codex_harness.adapters.research import ResearchSources
from codex_harness.adapters.research_program import EXTERNAL_SOURCES, collect_live
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.discovery_pressure import DiscoveryPressure, status
from codex_harness.application.fleet import Fleet
from codex_harness.application.observations import MemoryDirectory, Observer
from codex_harness.domain.discovery_pressure import (
    BUCKET,
    KEY,
    DiscoveryPaused,
    DiscoveryRefused,
    census,
    decide,
    validate_policy,
)
from codex_harness.domain.observation import new_process_run_id

BUDGET = {"per_host": 192, "total": 192, "mode": "subscription"}
POLICY = {"schema": "urn:zeus:discovery-pressure-policy:1", "id": "fixture-policy", "k_pause": 3, "k_resume": 1,
          "threshold_status": "suggested_unconfirmed", "input_max_age_seconds": 300}
T0 = "2026-09-28T00:00:00+00:00"
# FIXTURE call-ledger readings (the counts FleetLauncher.budget_exhausted admits against).
LEDGER = {"host": "fixture", "this_host": 0, "all_hosts": 0, "unreadable": 0}
LEDGER_DAMAGED = {"host": "fixture", "this_host": 1, "all_hosts": 1, "unreadable": 1}


def fleet_store(max_parallel=2, budget=BUDGET):
    store = MemoryStore()
    Fleet(store).register({"schema": "urn:zeus:fleet:1", "id": "fleet-fixture", "max_parallel": max_parallel,
                           "budget": dict(budget),
                           "lanes": [{"id": lane, "team": lane, "repository": "/fixture/repo-" + lane, "schema": "lane_" + lane,
                                      "redis_namespace": "fleet-" + lane, "runtime": "/fixture/rt-" + lane}
                                     for lane in ("a", "b")]})
    return store


def job(job_id, status="queued", lane="a", dependencies=(), paths=("src/x/",), budget=BUDGET, created=T0):
    """FIXTURE fleet job row with the fields admission reads."""
    return {"id": job_id, "status": status, "lane": lane, "repository": "/fixture/repo-" + lane,
            "dependencies": list(dependencies), "created_at": created, "updated_at": created,
            "manifest": {"budget": dict(budget), "plan": {"allowed_paths": list(paths)}}}


def put(store, bucket, row, key=None):
    with store.transaction() as tx:
        tx.put(bucket, key or row["id"], row)


def observer(store):
    return Observer(store, MemorySpool(new_process_run_id()), component="test-pressure", directory=MemoryDirectory())


def evaluator(store, policy=POLICY, ledger=LEDGER):
    return DiscoveryPressure(store, policy, observer(store), ledger=None if ledger is None else (lambda: ledger))


def audits(store):
    with store.transaction() as tx:
        return [row for row in tx.scan("observation_audit") if row.get("event_type") == "operations.discovery_pressure_changed"]


def queued(store, count, lane="a"):
    for index in range(count):
        put(store, "fleet_jobs", job(f"q{lane}{index}", lane=lane, paths=(f"src/{lane}{index}/",)))


# ----- T1-01 boundaries and hysteresis -------------------------------------------------------------------------
@pytest.mark.parametrize("waiting,prior,expected", [
    (6, None, "paused"),          # W = 3C pauses (the first reading is evaluated, not skipped)
    (5, None, "active"),          # initial memory is active; in-band keeps it
    (5, "paused", "paused"),      # in-band keeps paused
    (3, "paused", "paused"),
    (2, "paused", "active"),      # W = C resumes
    (0, "paused", "active"),
])
def test_boundaries_and_band_follow_the_policy_document(waiting, prior, expected):
    observed = {"registered": True, "paused": False, "capacity": 2, "waiting": waiting, "complete": True}
    outcome = decide({"hysteresis_state": prior} if prior else None, observed, validate_policy(POLICY))
    assert outcome["hysteresis_state"] == expected
    assert outcome["decision"] == ("hold" if expected == "paused" else "allow")


def test_capacity_is_the_configured_slots_not_the_free_ones():
    store = fleet_store(max_parallel=2)
    put(store, "fleet_jobs", job("busy-a", status="dispatching", lane="a"))
    put(store, "fleet_jobs", job("busy-b", status="dispatching", lane="b", paths=("src/b/",)))
    decision = evaluator(store).admit()
    assert decision["capacity"] == 2 and decision["occupancy"] == {"jobs_reserving": 2, "units_held": 0}


# ----- T1-02 job exclusions -------------------------------------------------------------------------------------
def test_only_jobs_waiting_for_capacity_or_their_lane_count_as_waiting():
    store = fleet_store()
    put(store, "fleet_jobs", job("running-a", status="dispatching", lane="a", paths=("src/shared/",)))
    put(store, "fleet_jobs", job("failed-dep", status="failed", lane="b", paths=("src/f/",)))
    put(store, "fleet_jobs", job("ready", lane="b", paths=("src/r/",)))                       # counts
    put(store, "fleet_jobs", job("lane-only", lane="a", paths=("src/other/",)))               # counts (lane_busy)
    put(store, "fleet_jobs", job("lane-and-conflict", lane="a", paths=("src/shared/",)))      # excluded
    put(store, "fleet_jobs", job("dep-failed", lane="b", dependencies=("failed-dep",), paths=("src/d/",)))
    put(store, "fleet_jobs", job("stale", lane="b", budget={"per_host": 1, "total": 1}, paths=("src/s/",)))
    put(store, "fleet_jobs", job("unknown-held", status="unknown", lane="b", paths=("src/u/",)))
    with store.transaction() as tx:
        registry = Fleet._registry(tx)
        jobs = {row["id"]: row for row in tx.scan("fleet_jobs")}
    observed = census(config=registry["config"], control={"paused": False}, jobs=jobs, units=[], plans=[],
                      intents=[], continuation_intents=[], ledger=LEDGER)
    assert observed["waiting"] == 2 and observed["complete"] is True
    assert observed["excluded"] == {"path_conflict": 1, "dependency_failed": 1, "budget_stale": 1}
    assert observed["occupancy"]["jobs_reserving"] == 2, "an unknown job keeps its reservation, never counts as waiting"


# ----- T1-03 / T1-04 / T1-05 candidates with unproven readiness make W incomplete --------------------------------
def test_an_eligible_backlog_item_without_a_job_makes_pressure_unknown_not_zero():
    store = fleet_store()
    plan = {"schema": "urn:zeus:fleet-backlog:1", "plan_id": "plan-1", "repository": "r" * 64, "enabled": True,
            "items": [{"id": "item-1", "project_id": "p", "criterion_id": "c", "lane": "a", "manifest_path": "m.json",
                       "manifest_revision": "a" * 40, "manifest_sha256": "b" * 64, "priority": 1, "dependencies": []}]}
    put(store, "fleet_backlog_plans", {"plan_id": "plan-1", "plan": plan, "plan_sha256": "c" * 64,
                                       "pin": {"revision": "a" * 40, "path": "b.json", "sha256": "d" * 64}}, "plan-1")
    decision = evaluator(store).admit()
    assert (decision["decision"], decision["reason_code"], decision["waiting"]) == ("hold", "pressure_unknown", None)
    assert decision["waiting_jobs_lower_bound"] == 0 and decision["basis"]["unknown_counts"]["backlog"] == 1
    # A disabled plan contributes nothing: W is complete again.
    plan["enabled"] = False
    put(store, "fleet_backlog_plans", {"plan_id": "plan-1", "plan": plan, "plan_sha256": "c" * 64,
                                       "pin": {"revision": "a" * 40, "path": "b.json", "sha256": "d" * 64}}, "plan-1")
    assert evaluator(store).admit()["decision"] == "allow"


def test_a_continuation_intent_counts_once_through_its_job_and_otherwise_makes_w_incomplete():
    store = fleet_store()
    put(store, "continuation_intents", {"id": "i1", "route": "requalification", "state": "admitted",
                                        "successor_job": "succ-1"})
    first = evaluator(store).admit()
    assert first["reason_code"] == "pressure_unknown" and first["basis"]["unknown_counts"]["continuation"] == 1
    put(store, "fleet_jobs", job("succ-1"))  # the successor job exists: the job is the single identity
    second = evaluator(store).admit()
    assert second["basis"]["complete"] is True and second["waiting"] == 1 and second["decision"] == "allow"
    put(store, "continuation_intents", {"id": "i2", "route": "research", "state": "intended"})
    assert evaluator(store).admit()["basis"]["complete"] is True, "a research intent is not dispatch work"


def test_a_held_intent_is_excluded_and_an_open_backlog_intent_with_its_job_counts_once():
    store = fleet_store()
    put(store, "continuation_intents", {"id": "held", "route": "correction", "state": "intended",
                                        "hold": {"reason_code": "authority_drift"}})
    assert evaluator(store).admit()["basis"]["complete"] is True, "a held intent is not waiting work, nor unknown"
    plan = {"schema": "urn:zeus:fleet-backlog:1", "plan_id": "plan-1", "repository": "r" * 64, "enabled": True,
            "items": [{"id": "item-1", "project_id": "p", "criterion_id": "c", "lane": "a", "manifest_path": "m.json",
                       "manifest_revision": "a" * 40, "manifest_sha256": "b" * 64, "priority": 1, "dependencies": []}]}
    put(store, "fleet_backlog_plans", {"plan_id": "plan-1", "plan": plan, "plan_sha256": "c" * 64,
                                       "pin": {"revision": "a" * 40, "path": "b.json", "sha256": "d" * 64}}, "plan-1")
    put(store, "fleet_backlog_intents", {"id": "i-1", "plan_id": "plan-1", "item_id": "item-1", "state": "intended",
                                         "job_id": "job-of-item", "attempts": 1})
    put(store, "fleet_jobs", job("job-of-item"))
    decision = evaluator(store).admit()
    assert decision["basis"]["unknown_counts"]["backlog"] == 0 and decision["waiting"] == 1, "counted once, as the job"


# ----- T1-06 intent -----------------------------------------------------------------------------------------------
class NoFetch(ResearchSources):
    def fetch(self, url):  # noqa: D401 - FIXTURE: any fetch here is a test failure
        raise AssertionError("fetched " + url)


class Holding:
    def __init__(self):
        self.calls = 0

    def admit(self):
        self.calls += 1
        return {"decision": "hold", "reason_code": "pressure_high"}


@pytest.mark.parametrize("intent,code", [(None, "discovery_intent_required"), ("", "discovery_intent_required"),
                                         ("research", "discovery_intent_invalid")])
def test_a_missing_or_unknown_intent_refuses_before_any_fetch(intent, code):
    pressure = Holding()
    with pytest.raises(DiscoveryRefused) as refused:
        NoFetch(None, pressure=pressure).collect("github", intent=intent)
    assert refused.value.reason_code == code and pressure.calls == 0


@pytest.mark.parametrize("intent", ["user_request", "incident", "existing_work_result", "task_required"])
def test_exempt_intents_fetch_without_consulting_pressure(intent):
    fetched = []

    class Fetching(ResearchSources):
        def fetch(self, url):
            fetched.append(url)
            return '<rss><channel><item><link>https://news.hada.io/topic?id=1</link><title>t</title></item></channel></rss>'
    pressure = Holding()
    artifacts = SimpleNamespace(put=lambda body, source: {"ref": "sha256:" + "0" * 64})
    result = Fetching(artifacts, pressure=pressure).collect("geeknews", intent=intent)
    assert fetched and result["items"] and pressure.calls == 0
    # Without any evaluator wired, an exempt fetch still proceeds (fail-closed applies to proactive only).
    assert Fetching(artifacts).collect("geeknews", intent=intent)["items"]


def test_a_proactive_fetch_without_an_evaluator_holds():
    with pytest.raises(DiscoveryPaused) as paused:
        NoFetch(None).collect("github", intent="proactive")
    assert paused.value.reason_code == "pressure_unavailable"


# ----- T1-07 an unregistered or paused Fleet holds without a Fleet write -----------------------------------------
def test_unregistered_and_paused_fleets_hold_and_write_no_fleet_row():
    unregistered = MemoryStore()
    decision = evaluator(unregistered).admit()
    assert (decision["decision"], decision["reason_code"], decision["capacity"]) == ("hold", "fleet_unregistered", None)
    store = fleet_store()
    Fleet(store).pause()
    before = {bucket: copy.deepcopy(rows) for bucket, rows in _fleet_buckets(store).items()}
    decision = evaluator(store).admit()
    assert (decision["decision"], decision["reason_code"]) == ("hold", "fleet_paused")
    assert _fleet_buckets(store) == before, "pressure never pauses, admits or rewrites the Fleet"


def _fleet_buckets(store):
    with store.transaction() as tx:
        return {bucket: tx.scan(bucket) for bucket in ("fleet_registry", "fleet_control", "fleet_jobs", "fleet_units")}


# ----- T1-08 initial state and restart --------------------------------------------------------------------------------
def test_the_first_reading_is_evaluated_and_a_restart_keeps_the_hysteresis_memory():
    store = fleet_store(max_parallel=1)
    queued(store, 3)
    assert evaluator(store).admit()["hysteresis_state"] == "paused", "a high first reading pauses immediately"
    with store.transaction() as tx:
        for index in (0,):
            tx.put("fleet_jobs", f"qa{index}", {**tx.get("fleet_jobs", f"qa{index}"), "status": "accepted"})
    # W = 2 with C = 1 is inside the band; a NEW evaluator instance (a restart) keeps the recorded paused memory.
    restarted = evaluator(store).admit()
    assert (restarted["hysteresis_state"], restarted["decision"], restarted["waiting"]) == ("paused", "hold", 2)
    # An unknown reading holds but keeps the memory, and reading the status never writes.
    before = copy.deepcopy(store.data)
    assert status(store)["row"]["hysteresis_state"] == "paused" and store.data == before
    assert status(MemoryStore()) == {"schema": "urn:zeus:discovery-pressure:1", "evaluated": False, "row": None}


# ----- T1-09 one transition, one audit event ------------------------------------------------------------------------
def test_a_transition_is_audited_once_and_a_repeat_only_advances_the_evaluation_sequence():
    store = fleet_store(max_parallel=1)
    pressure = evaluator(store)
    first = pressure.admit()
    second = pressure.admit()
    assert (first["version"], second["version"]) == (1, 1)
    assert (first["evaluation_sequence"], second["evaluation_sequence"]) == (1, 2)
    assert len(audits(store)) == 1
    queued(store, 3)
    third = pressure.admit()
    assert (third["version"], third["hysteresis_state"]) == (2, "paused")
    events = audits(store)
    assert len(events) == 2
    latest = max(events, key=lambda row: row["attributes"]["version"])
    assert latest["attributes"]["from_state"] == "active" and latest["attributes"]["to_state"] == "paused"
    assert latest["reason_code"] == "pressure_high" and latest["attributes"]["waiting"] == 3


def test_a_failed_audit_rolls_the_evaluation_back():
    store = fleet_store()

    class Failing:
        def audit(self, tx, *args, **kwargs):
            raise RuntimeError("injected audit failure")
    with pytest.raises(RuntimeError):
        DiscoveryPressure(store, POLICY, Failing()).admit()
    with store.transaction() as tx:
        assert tx.get(BUCKET, KEY) is None, "no row without its mandatory audit event"


# ----- T1-10 an admitted fetch settles once; the next one checks again ------------------------------------------------
def test_each_proactive_fetch_checks_pressure_itself_and_a_started_one_is_not_cancelled():
    decisions = iter([{"decision": "allow", "reason_code": "pressure_ok"}, {"decision": "hold", "reason_code": "pressure_high"}])
    pressure = SimpleNamespace(admit=lambda: next(decisions))
    fetched = []

    class Fetching(ResearchSources):
        def fetch(self, url):
            fetched.append(url)
            return '<rss><channel><item><link>https://news.hada.io/topic?id=1</link><title>t</title></item></channel></rss>'
    artifacts = SimpleNamespace(put=lambda body, source: {"ref": "sha256:" + "0" * 64})
    status_by_source, _ = collect_live(Fetching(artifacts, pressure=pressure), intent="proactive")
    # The first feed was admitted and fetched exactly once; the transition between the two paused only the second.
    first, second = EXTERNAL_SOURCES
    assert len(fetched) == 1 and fetched[0] == ResearchSources.URLS[first]
    assert status_by_source[second]["status"] == "paused" and status_by_source[second]["pressure"] == "pressure_high"
    assert status_by_source[first]["status"] != "paused", "the started fetch was not cancelled or relabelled"


# ----- T1-11 unknown inputs hold, never W = 0 --------------------------------------------------------------------------
@pytest.mark.parametrize("policy,detail", [(None, "config_missing"), ({**POLICY, "k_resume": 5}, "config_invalid"),
                                           ({**POLICY, "threshold_status": "guessed"}, "config_invalid"),
                                           ({k: v for k, v in POLICY.items() if k != "input_max_age_seconds"}, "config_invalid")])
def test_a_missing_or_invalid_policy_holds_with_a_named_detail(policy, detail):
    decision = DiscoveryPressure(fleet_store(), policy, observer(MemoryStore())).admit()
    assert (decision["decision"], decision["reason_code"], decision["detail"]) == ("hold", "pressure_unknown", detail)


@pytest.mark.parametrize("budget", [BUDGET, {"per_host": 4, "total": 8}], ids=["subscription", "finite"])
def test_an_unreadable_call_ledger_with_waiting_jobs_is_unknown_in_both_modes(budget):
    store = fleet_store(budget=budget)
    put(store, "fleet_jobs", job("ready", budget=budget))
    for reader in (None, lambda: (_ for _ in ()).throw(OSError("ledger unreadable")), lambda: {"broken": True}):
        decision = DiscoveryPressure(store, POLICY, observer(store), ledger=reader).admit()
        assert decision["reason_code"] == "pressure_unknown" and decision["basis"]["unknown_counts"]["budget"] == 1
    assert evaluator(fleet_store(budget=budget), ledger=None).admit()["decision"] == "allow", \
        "with no waiting job the ledger cannot change W"


def test_an_exhausted_ledger_blocks_admission_so_waiting_jobs_leave_w():
    finite = {"per_host": 1, "total": 1}
    store = fleet_store(max_parallel=1, budget=finite)
    queued_rows = [job(f"q{index}", budget=finite, paths=(f"src/{index}/",)) for index in range(3)]
    for row in queued_rows:
        put(store, "fleet_jobs", row)
    full = {"host": "fixture", "this_host": 1, "all_hosts": 1, "unreadable": 0}
    decision = evaluator(store, ledger=full).admit()
    assert (decision["waiting"], decision["decision"]) == (0, "allow")
    assert decision["basis"]["excluded_counts"] == {"budget_exhausted": 3}
    # Subscription: a damaged ledger (an unreadable slot) refuses admission, exactly as the Fleet runner does.
    damaged = fleet_store(max_parallel=1)
    queued(damaged, 3)
    assert evaluator(damaged, ledger=LEDGER_DAMAGED).admit()["basis"]["excluded_counts"] == {"budget_exhausted": 3}
    assert evaluator(damaged, ledger=LEDGER).admit()["hysteresis_state"] == "paused", "a clean ledger lets W count"


def test_a_hold_for_unknown_input_keeps_the_hysteresis_memory():
    store = fleet_store(max_parallel=1)
    queued(store, 3)
    assert evaluator(store).admit()["hysteresis_state"] == "paused"
    held = evaluator(store, ledger=None).admit()
    assert (held["decision"], held["reason_code"], held["hysteresis_state"]) == ("hold", "pressure_unknown", "paused")
    with store.transaction() as tx:
        tx.put("fleet_jobs", "qa0", {**tx.get("fleet_jobs", "qa0"), "status": "accepted"})
    in_band = evaluator(store).admit()
    assert (in_band["waiting"], in_band["hysteresis_state"], in_band["decision"]) == (2, "paused", "hold")


def test_the_packaged_policy_is_the_suggested_unconfirmed_three_and_one():
    policy = validate_policy(packaged_policy())
    assert (policy["k_pause"], policy["k_resume"], policy["threshold_status"]) == (3, 1, "suggested_unconfirmed")


# ----- T1-12 a paused feed is recorded as policy_paused, not a degraded or empty source -------------------------------
def test_a_held_feed_is_recorded_paused_with_no_items_and_is_not_degraded():
    sources = NoFetch(None, pressure=Holding())
    status_by_source, items = collect_live(sources, intent="proactive")
    assert items == []
    for row in status_by_source.values():
        assert row == {"status": "paused", "code": "policy_paused", "artifact": None, "fetched_at": None,
                       "items": None, "pressure": "pressure_high"}
    degraded = [name for name, row in status_by_source.items() if row["status"] not in ("ok", "paused")]
    assert degraded == []


# ----- T1-13 the monitor source reports the recorded row without evaluating -----------------------------------------
def test_the_monitor_source_projects_the_row_and_never_evaluates():
    from codex_harness.adapters import monitoring
    store = fleet_store()
    assert monitoring.discovery_pressure_facts(store)["evaluated"] is False
    with store.transaction() as tx:
        assert tx.get(BUCKET, KEY) is None, "reading did not create the row"
    evaluator(store).admit()
    facts = monitoring.discovery_pressure_facts(store)
    assert facts["evaluated"] is True and facts["row"]["policy"]["threshold_status"] == "suggested_unconfirmed"
    assert facts["row"]["waiting"] == 0 and facts["row"]["capacity"] == 2


def test_two_concurrent_evaluators_make_one_transition_on_real_postgres(isolated_pgstore):
    """Integration (real PostgreSQL): two evaluators crossing the same threshold at once serialize on the store
    transaction; exactly one transition and one audit event result, and the second only re-evaluates."""
    import threading
    store = isolated_pgstore
    Fleet(store).register({"schema": "urn:zeus:fleet:1", "id": "fleet-fixture", "max_parallel": 1,
                           "budget": dict(BUDGET),
                           "lanes": [{"id": "a", "team": "a", "repository": "/fixture/repo-a", "schema": "lane_a",
                                      "redis_namespace": "fleet-a", "runtime": "/fixture/rt-a"}]})
    queued(store, 3)
    results, barrier = [], threading.Barrier(2)

    def run():
        barrier.wait()
        results.append(evaluator(store).admit())
    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(result["evaluation_sequence"] for result in results) == [1, 2]
    assert {result["version"] for result in results} == {1} and {r["hysteresis_state"] for r in results} == {"paused"}
    assert len(audits(store)) == 1
