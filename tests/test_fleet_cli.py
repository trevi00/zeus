"""`zeus fleet run` wiring of the optional managed runtime control (HOST-RUNTIME.md).

The store is a MemoryStore and the lane launcher, host settings and portfolio pass are labelled
in-test doubles: no `zeus operate run`, lane database, Docker, provider or model is reached, and the
process signal handlers are not replaced for the test process.
"""
import argparse
import signal
from types import SimpleNamespace

from test_fleet import GOAL, FakeLauncher, RecordingControl, config, manifest

from codex_harness.adapters import fleet_cli
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import Fleet


def wired(tmp_path, monkeypatch):
    """The real `fleet_cli.run` over a registered fleet, with its host-side ports doubled."""
    store = MemoryStore()
    fleet = Fleet(store)
    fleet.register(config(tmp_path))
    fleet.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    launchers = []

    def lane_launcher(registered, host):
        launchers.append(FakeLauncher({"op-1": {"status": "accepted", "reason_code": "lead_accepted",
                                                "exit_code": 0}}))
        return launchers[-1]

    monkeypatch.setattr("codex_harness.adapters.configuration.settings", lambda: {})
    monkeypatch.setattr("codex_harness.adapters.fleet_runtime.LaneLauncher", lane_launcher)
    monkeypatch.setattr("codex_harness.adapters.portfolio.portfolio_reconciler", lambda store: None)
    monkeypatch.setattr(signal, "signal", lambda *args: None)
    return SimpleNamespace(store=store), fleet, launchers


def test_fleet_run_hands_the_managed_control_to_the_real_runner(tmp_path, monkeypatch):
    service, fleet, launchers = wired(tmp_path, monkeypatch)
    control = RecordingControl()
    control.paused = True
    control.stopping = True
    result = fleet_cli.run(service, argparse.Namespace(once=False), control=control)
    # A stop request before the first pass: nothing is admitted, and the instance says so.
    assert result["exit_code"] == 0 and result["stopped"] is True and result["admitted"] == []
    assert launchers[0].launched == []
    assert control.beats == [{"admission": "stopping", "active": 0, "unresolved": 0}]
    assert {job["id"]: job["status"] for job in fleet.status()["jobs"]} == {"op-1": "queued"}


def test_fleet_run_without_a_control_is_unchanged(tmp_path, monkeypatch):
    service, _, launchers = wired(tmp_path, monkeypatch)
    result = fleet_cli.run(service, argparse.Namespace(once=True))
    assert result["exit_code"] == 0 and result["admitted"] == ["op-1"]
    assert launchers[0].launched == ["op-1"]
    assert "heartbeat" not in result and "control" not in result
