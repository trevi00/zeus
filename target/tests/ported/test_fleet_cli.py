# Ported from SOURCE M7 tests/test_fleet_cli.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
"""`zeus fleet run` wiring of the optional managed runtime control (HOST-RUNTIME.md).

The store is a MemoryStore and the lane launcher, host settings and portfolio pass are labelled
in-test doubles: no `zeus operate run`, lane database, Docker, provider or model is reached, and the
process signal handlers are not replaced for the test process.
"""
import argparse
import signal
from types import SimpleNamespace

from m7_coordination import Fleet
from test_fleet import GOAL, FakeLauncher, RecordingControl, config, manifest

from codex_harness.composition.cli_fleet import run_fleet
from codex_harness.storage.adapters.memory_store import MemoryStore


def wired(tmp_path, monkeypatch):
    """The real `fleet_cli.run` (target: `composition.cli_fleet.run_fleet`) over a registered fleet, with its host-side ports doubled."""
    store = MemoryStore()
    fleet = Fleet(store)
    fleet.register(config(tmp_path))
    fleet.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    launchers = []

    def lane_launcher(registered, host):
        launchers.append(FakeLauncher({"op-1": {"status": "accepted", "reason_code": "lead_accepted",
                                                "exit_code": 0}}))
        return launchers[-1]

    # S11 M B5: patch targets are the target modules that now look the names up (composition.cli_fleet.run_fleet imports
    # settings and portfolio_reconciler at call time and builds the launcher through composition.fleet.lane_launcher).
    monkeypatch.setattr("codex_harness.composition.configuration.settings", lambda: {})
    monkeypatch.setattr("codex_harness.composition.fleet.lane_launcher", lane_launcher)
    monkeypatch.setattr("codex_harness.intake.adapters.portfolio.portfolio_reconciler", lambda store: None)
    monkeypatch.setattr(signal, "signal", lambda *args: None)
    return SimpleNamespace(store=store), fleet, launchers


def test_fleet_run_hands_the_managed_control_to_the_real_runner(tmp_path, monkeypatch):
    service, fleet, launchers = wired(tmp_path, monkeypatch)
    control = RecordingControl()
    control.paused = True
    control.stopping = True
    result = run_fleet(service, argparse.Namespace(once=False), control=control)  # S11 M B5: M7 fleet_cli.run
    # A stop request before the first pass: nothing is admitted, and the instance says so.
    assert result["exit_code"] == 0 and result["stopped"] is True and result["admitted"] == []
    assert launchers[0].launched == []
    assert control.beats == [{"admission": "stopping", "active": 0, "unresolved": 0}]
    assert {job["id"]: job["status"] for job in fleet.status()["jobs"]} == {"op-1": "queued"}


def test_fleet_run_without_a_control_is_unchanged(tmp_path, monkeypatch):
    service, _, launchers = wired(tmp_path, monkeypatch)
    result = run_fleet(service, argparse.Namespace(once=True))  # S11 M B5: M7 fleet_cli.run
    assert result["exit_code"] == 0 and result["admitted"] == ["op-1"]
    assert launchers[0].launched == ["op-1"]
    assert "heartbeat" not in result and "control" not in result
