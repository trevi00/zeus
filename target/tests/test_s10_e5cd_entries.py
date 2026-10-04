"""S10 E5d: the managed runtime's `fleet_gate` and `run_fleet` (composition) and the `supervise` entry branch (R-e5cd, DESIGN-s10 §16).

MemoryStore and monkeypatched builders; no docker, systemd, Redis, PostgreSQL or network. The M7 host-migration CLI layer (E5c) is NOT
part of this file: it escalated on missing target homes (see the E5c report)."""
from __future__ import annotations

import argparse

import pytest

from codex_harness import composition
from codex_harness.composition import cli_fleet
from codex_harness.composition import managed_runtime as wiring
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.domain.fleet import FleetRefused
from codex_harness.delivery.adapters.managed_runtime import EXIT_REFUSED
from codex_harness.entry.processes import managed_runtime as entry
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

DIGEST = "d" * 64


@pytest.fixture
def service(monkeypatch):
    handle = composition.ServiceHandle(MemoryStore(), packaged_organization())
    monkeypatch.setattr(composition, "build", lambda: handle)
    return handle


def config_for(tmp_path) -> dict:
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 1, "budget": {"per_host": 2, "total": 4},
            "lanes": [{"id": "a", "team": "team-a", "repository": str(tmp_path / "a" / "repo"), "schema": "lane_a",
                       "redis_namespace": "ns-a", "runtime": str(tmp_path / "a" / "runtime")}]}


def test_fleet_gate_of_an_unregistered_fleet_refuses(service):
    with pytest.raises(FleetRefused) as refused:
        wiring.fleet_gate("managed-fleet", DIGEST)
    assert refused.value.reason_code == "unregistered"


def test_fleet_gate_commits_the_pause_and_reports_settled_debt_of_the_host_store(service, tmp_path):
    (tmp_path / "a" / "repo").mkdir(parents=True)
    FleetRegistry(service.store).register(config_for(tmp_path))
    verdict = wiring.fleet_gate("managed-fleet", DIGEST)
    assert verdict == {"paused": True, "hold": True, "reserving": [], "units_held": [], "settled": True}


def test_supervise_with_the_fleet_gate_refuses_a_state_dir_without_a_launch_request(tmp_path, capsys):
    assert entry.main(["supervise", "--state-dir", str(tmp_path)]) == EXIT_REFUSED
    assert capsys.readouterr().out == ""


def test_the_supervise_branch_passes_the_composition_fleet_gate(monkeypatch):
    seen = {}
    monkeypatch.setattr(entry, "supervise", lambda state_dir, *, gate: seen.update(state=state_dir, gate=gate) or 7)
    assert entry.main(["supervise", "--state-dir", "/state"]) == 7
    assert seen == {"state": "/state", "gate": wiring.fleet_gate}


def test_run_fleet_calls_the_fleet_cli_runner_with_once_false_and_the_control(monkeypatch, service):
    calls = []
    monkeypatch.setattr(cli_fleet, "run_fleet",
                        lambda handle, args, *, control=None: calls.append((handle, args, control)) or {"ticks": 1})
    control = object()
    assert wiring.run_fleet(control) == {"ticks": 1}
    [(handle, args, passed)] = calls
    assert handle is service and passed is control
    assert args == argparse.Namespace(once=False)


def test_the_fleet_workload_of_entry_runs_run_fleet_with_the_runtime_control(monkeypatch, tmp_path):
    from codex_harness.delivery.adapters.managed_runtime import RuntimeControl
    from codex_harness.delivery.domain.managed_runtime import WORKLOADS

    assert "fleet" in WORKLOADS
    descriptor = {"sentinel": True}
    monkeypatch.setattr(wiring, "validate_descriptor", lambda document: document)
    monkeypatch.setattr(wiring, "_read_json", lambda path: descriptor)
    monkeypatch.setattr(wiring, "_effective", lambda: ("image", "profile"))
    monkeypatch.setattr(wiring.host_delivery, "startup_receipt",
                        lambda document, *, image, profile_digest: {"descriptor_sha256": DIGEST})
    monkeypatch.setattr(wiring, "_write_json", lambda path, document: None)
    seen = []
    monkeypatch.setattr(wiring, "run_fleet", lambda control: seen.append(control))
    assert wiring.entry(str(tmp_path), "fleet") == 0
    [control] = seen
    assert isinstance(control, RuntimeControl) and control.activation() == DIGEST


def test_the_entry_module_has_no_unimplemented_carry():
    import inspect

    assert "NotImplementedError" not in inspect.getsource(entry)
    assert "NotImplementedError" not in inspect.getsource(wiring)
