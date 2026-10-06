"""S11 XC-8 (TQ-XCUT-PLAN section 10; XC-7 G1-G4): the production composition wires what M7 wired.

Behavioural, through the composed builders (`operation.build_executor`, `operation.Executor`, `cli.execution_recovery`,
`continuation.coordinator`). Expected results: M7 `adapters/discovery_pressure.py:25-28` (proactive discovery is admitted on an
idle registered Fleet, held on a lane store), M7 `adapters/executor.py:1786-1789` and `application/execution_recovery.py:82-92,247-252`
(threshold review and its recovery), DESIGN-s10 section 17 A5-2 (`operations.capacity_refused {fleet_unit, unit_limit}`); the
recorded outcomes are those of the XC-7 repro scripts."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import cli, configuration, continuation, operation
from codex_harness.composition.managed_runtime import fixture_config
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest
from codex_harness.research.domain.discovery_pressure import PROACTIVE, DiscoveryPaused
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

UNIT1, UNIT2 = "1" * 64, "2" * 64


@pytest.fixture
def host(tmp_path, monkeypatch):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime"), "ZEUS_COMPOSITION_PROFILE": "development"}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    (tmp_path / "runtime").mkdir()
    return tmp_path


def built(tmp_path):
    service = composition.ServiceHandle(MemoryStore(), packaged_organization())
    return operation.build_executor(service, knowledge=False, evidence_profile=None, isolation=None,
                                    profile="development")


def composed(tmp_path):
    service = composition.ServiceHandle(MemoryStore(), packaged_organization())
    git = SimpleNamespace(_git=lambda *a, **k: "revision", repository=tmp_path)
    return operation.Executor(service, git, FileArtifacts(str(tmp_path / "artifacts")), knowledge=None)


def test_a_proactive_fetch_is_admitted_on_a_registered_idle_fleet(host):
    executor = built(host)
    FleetRegistry(executor.service.store).register(fixture_config(host))
    admitted = executor.run_task.research.pressure.admit()
    assert (admitted["decision"], admitted["reason_code"], admitted["recorded"]) == ("allow", "pressure_ok", True)


def test_a_proactive_fetch_holds_on_a_lane_store_without_a_fleet_registry(host):
    executor = built(host)
    held = executor.run_task.research.pressure.admit()
    assert (held["decision"], held["reason_code"], held["recorded"]) == ("hold", "fleet_unregistered", True)
    with pytest.raises(DiscoveryPaused, match="fleet_unregistered"):
        executor.run_task.research.collect("github", intent=PROACTIVE)  # held before any IO


def decision_row(status="running"):
    return {"id": "d-threshold", "phase": "threshold_review", "actor": "lead:improvement", "status": status,
            "input": {"request_id": "r1"}, "generation": 1, "attempt": 1, "owner": "o", "lease_owner": "o",
            "task_id": "t", "lease_until": "2099-01-01T00:00:00+00:00"}


def test_a_claimed_threshold_review_decision_reaches_review_threshold(host):
    executor = composed(host)
    decision = decision_row()
    with pytest.raises(ContractError) as refused:
        executor.decisions.threshold_review({**decision, "_bucket": "decisions_pending"})
    # source-faithful (XC-7 repro): review_threshold's own lease rule, not the refusing default
    assert "not wired" not in str(refused.value)
    assert str(refused.value) == "Stale or expired task execution"
    outcome = executor.decisions.decide("lead:improvement", decision)
    assert outcome["status"] == "stale" and outcome["error"] != "Threshold review is not wired"


def test_operator_recovery_of_a_threshold_review_row_reaches_the_threshold_records(host):
    service = composition.ServiceHandle(MemoryStore(), packaged_organization())
    artifacts = FileArtifacts(str(host / "artifacts"))
    rid = "req-1"
    row = {"id": digest([rid, "lead:improvement"]), "phase": "threshold_review", "actor": "lead:improvement",
           "input": {"request_id": rid}, "status": "failed"}
    request = {"id": rid, "row_id": "prop-1", "binding": "x", "status": "failed",
               "failure": "decision_attempt_budget_exhausted", "failed_decision": row["id"]}
    with service.store.transaction() as tx:
        tx.put("threshold_review_requests", rid, request)
        tx.put("decisions_pending", row["id"], row)
    recovery = cli.execution_recovery(service, artifacts)
    with pytest.raises(ContractError) as refused, service.store.transaction() as tx:
        recovery._related_checked(tx, "decisions_pending", row)
    assert str(refused.value) == "Calculated threshold record required"  # the records are read, not 'not wired'


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event_type, outcome, **fields):
        self.events.append((event_type, outcome, fields.get("attributes")))


def test_the_second_unit_reservation_is_refused_and_observed_through_the_composed_continuation(host):
    store = MemoryStore()
    config = fixture_config(host)
    lane = config["lanes"][0]
    config["lanes"] = [lane, {**lane, "id": "spare", "schema": "lane_spare", "redis_namespace": "spare",
                              "runtime": lane["runtime"] + "-spare"}]
    FleetRegistry(store).register({**config, "max_parallel": 1})
    recorder = Recorder()
    owners = continuation.coordinator(store, config, {}, lanes=object(), conductor=object(), evidence=object(),
                                      observer=recorder)
    port = owners.tick.fleet
    port.reserve_unit(UNIT1, "conductor", "fixture", "subject")
    assert recorder.events == []
    with pytest.raises(Exception, match="capacity"):
        port.reserve_unit(UNIT2, "conductor", "fixture", "subject")
    assert [(e[0], e[2]["scope"], e[2]["refusal_reason"]) for e in recorder.events] == [
        ("operations.capacity_refused", "fleet_unit", "unit_limit")]
