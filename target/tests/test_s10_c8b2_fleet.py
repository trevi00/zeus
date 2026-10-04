"""S10 C8b-2: the `fleet` root, `composition.cli_fleet`, `composition.fleet_backlog` and the `bind_goal` move (R-c28, E-c21).

MemoryStore, monkeypatched settings and builders; no provider, process, Docker, journal, Git or PostgreSQL is touched. Parity with M7 on a
disposable PostgreSQL is the `entry.cli_fleet.pg` compare family; the recovery, relocation and backlog paths are the ported suites'."""
from __future__ import annotations

import ast
import importlib.util
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import (
    cli_fleet,
    cli_operation,
    configuration,
    fleet_backlog,
    observation,
)
from codex_harness.composition import continuation as wiring
from codex_harness.composition import fleet as composition_fleet
from codex_harness.coordination.application.fleet import runner as fleet_runner
from codex_harness.coordination.application.fleet.admission import AdmissionControl
from codex_harness.coordination.application.fleet.pause import FleetPause
from codex_harness.coordination.application.fleet.recovery import FleetRecovery
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.domain.fleet import FleetRefused
from codex_harness.entry import cli as entry
from codex_harness.entry.cli import fleet as root
from codex_harness.entry.cli import operation as entry_operation
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

SHIM = Path(__file__).resolve().parent / "ported" / "m7_coordination.py"


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime")}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(configuration, "runtime_dir", lambda: tmp_path / "runtime")
    return values


@pytest.fixture
def service(settings):
    return composition.ServiceHandle(MemoryStore(), packaged_organization())


def config_for(tmp_path: Path) -> dict:
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 1, "budget": {"per_host": 2, "total": 4},
            "lanes": [{"id": "a", "team": "team-a", "repository": str(tmp_path / "a" / "repo"), "schema": "lane_a",
                       "redis_namespace": "ns-a", "runtime": str(tmp_path / "a" / "runtime")}]}


@pytest.fixture
def registered(service, tmp_path):
    (tmp_path / "a" / "repo").mkdir(parents=True)
    config = config_for(tmp_path)
    FleetRegistry(service.store).register(config)
    return config


def shim():
    spec = importlib.util.spec_from_file_location("m7_coordination_c8b2_probe", SHIM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRunner:
    """Records the constructor and answers `run`; `fail` makes `run` raise after the handlers were installed."""
    built: list = []
    fail = False
    seen: dict = {}

    def __init__(self, registry, admission, pause, launcher, **ports):
        self.args, self.ports = (registry, admission, pause, launcher), ports
        FakeRunner.built.append(self)
        self.stopped = False

    def stop(self):
        self.stopped = True

    def run(self, once):
        FakeRunner.seen = {"once": once, "sigint": signal.getsignal(signal.SIGINT)}
        if FakeRunner.fail:
            raise RuntimeError("runner failed")
        return {"ticks": 1}


@pytest.fixture
def fakes(monkeypatch):
    FakeRunner.built, FakeRunner.fail, FakeRunner.seen = [], False, {}
    observers, launchers = [], []
    monkeypatch.setattr(fleet_runner, "FleetRunner", FakeRunner)
    monkeypatch.setattr(observation, "build_observer",
                        lambda store, component, role=None, root=None: observers.append(component) or ("observer", component))
    monkeypatch.setattr(composition_fleet, "lane_launcher",
                        lambda config, host, **kwargs: launchers.append((config, host)) or "launcher")
    return SimpleNamespace(observers=observers, launchers=launchers)


# ----- run_fleet: opt-in tickers, each with its own observer -----------------------------------------------------------------------------------
def test_run_fleet_builds_no_observer_and_no_ticker_without_the_host_settings(service, registered, fakes):
    result = cli_fleet.run_fleet(service, SimpleNamespace(once=True))
    runner = FakeRunner.built[0]
    assert result == {"ticks": 1, "exit_code": 0}
    assert fakes.observers == []
    assert runner.ports["backlog"] is None and runner.ports["continuation"] is None and runner.ports["control"] is None
    assert callable(runner.ports["reconcile"])
    assert [type(part) for part in runner.args[:3]] == [FleetRegistry, AdmissionControl, FleetPause]
    assert runner.args[3] == "launcher" and fakes.launchers == [(registered, {"HARNESS_RUNTIME_DIR": fakes.launchers[0][1]["HARNESS_RUNTIME_DIR"]})]
    assert FakeRunner.seen["once"] is True


def test_run_fleet_builds_each_ticker_with_its_own_observer_when_the_settings_are_set(service, registered, settings, fakes,
                                                                                     monkeypatch):
    settings[fleet_backlog.PLAN_SETTING] = " plan-1 "
    settings[wiring.POLICY_SETTING] = "p1,p2"
    built = {}
    monkeypatch.setattr(fleet_backlog, "backlog_ticker",
                        lambda store, config, plan_id, **kw: built.setdefault("backlog", (config, plan_id, kw)) and "backlog-tick")
    monkeypatch.setattr(wiring, "continuation_ticker",
                        lambda store, config, host, ids, **kw: built.setdefault("continuation", (config, ids, kw)) and "continuation-tick")
    control = object()
    cli_fleet.run_fleet(service, SimpleNamespace(once=False), control=control)
    runner = FakeRunner.built[0]
    assert fakes.observers == ["fleet-backlog", "fleet-continuation"]
    assert built["backlog"] == (registered, "plan-1", {"observer": ("observer", "fleet-backlog")})
    assert built["continuation"] == (registered, ["p1", "p2"], {"observer": ("observer", "fleet-continuation")})
    assert (runner.ports["backlog"], runner.ports["continuation"], runner.ports["control"]) == (
        "backlog-tick", "continuation-tick", control)
    assert FakeRunner.seen["once"] is False


def test_run_fleet_restores_the_signal_handlers_on_an_exception(service, registered, fakes):
    before = {name: signal.getsignal(getattr(signal, name)) for name in ("SIGINT", "SIGTERM")}
    FakeRunner.fail = True
    with pytest.raises(RuntimeError, match="runner failed"):
        cli_fleet.run_fleet(service, SimpleNamespace(once=True))
    assert FakeRunner.seen["sigint"] is not before["SIGINT"]  # the run's own handler was installed while it ran
    assert {name: signal.getsignal(getattr(signal, name)) for name in before} == before
    FakeRunner.built[0].stopped = False
    FakeRunner.seen["sigint"](signal.SIGINT, None)
    assert FakeRunner.built[0].stopped is True


def test_run_fleet_of_an_unregistered_fleet_refuses_before_a_launcher_or_observer(service, settings, fakes):
    with pytest.raises(FleetRefused) as refused:
        cli_fleet.run_fleet(service, SimpleNamespace(once=True))
    assert refused.value.reason_code == "unregistered"
    assert fakes.observers == [] and fakes.launchers == [] and FakeRunner.built == []


# ----- the three owner commands: the document is validated first, nothing is observed ---------------------------------------------------------
@pytest.mark.parametrize("command", [cli_fleet.reconcile_interrupted, cli_fleet.relocate, cli_fleet.migrate_host])
def test_an_owner_command_refuses_an_invalid_document_before_any_observation(command, service, monkeypatch):
    monkeypatch.setattr(cli_fleet, "_collectors", lambda: pytest.fail("no observation for an invalid document"))
    with pytest.raises(FleetRefused):
        command(service, SimpleNamespace(docker="docker", journal=Path("j")), {})


def test_the_resolved_input_is_read_once():
    reads = []
    resolved = cli_fleet._resolved(lambda: reads.append(1) or {"row": 1})
    assert reads == [] and resolved() is resolved() and reads == [1]


# ----- entry bodies --------------------------------------------------------------------------------------------------------------------------
def test_check_resolved_refuses_a_symlink_and_a_missing_repository(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    config = config_for(tmp_path)
    config["lanes"][0]["repository"] = str(tmp_path / "link")
    with pytest.raises(FleetRefused) as refused:
        root._check_resolved(config)
    assert (refused.value.reason_code, refused.value.field) == ("path_unresolved", "lanes[0].repository")
    config["lanes"][0]["repository"] = str(tmp_path / "absent")
    with pytest.raises(FleetRefused) as refused:
        root._check_resolved(config)
    assert refused.value.reason_code == "repository_missing"
    (tmp_path / "a" / "repo").mkdir(parents=True)
    assert root._check_resolved(config_for(tmp_path)) == config_for(tmp_path)  # a runtime root may be absent


def test_the_entry_body_emits_a_refusal_and_exits_one(service, monkeypatch, capsys):
    monkeypatch.setattr(composition, "build", lambda: service)
    with pytest.raises(SystemExit) as stopped:
        root.run(SimpleNamespace(fleet_command="pause"))
    assert stopped.value.code == 1
    assert '"reason_code": "unregistered"' in capsys.readouterr().out


def test_the_status_of_no_fleet_and_of_an_unknown_plan(service, registered, capsys):
    status = root._status(service, None)
    assert status["registered"] is True and status["reconciliation_required"] == [] and status["exit_code"] == 0
    unknown = root._backlog(service, SimpleNamespace(backlog_command="status", plan="nope"))
    assert unknown["registered"] is False and unknown["exit_code"] == 1
    every = root._backlog(service, SimpleNamespace(backlog_command="status"))
    assert every["exit_code"] == 0


def test_the_branches_call_the_composition_functions_with_the_owner_document(service, tmp_path, monkeypatch):
    document = tmp_path / "doc.json"
    document.write_text('{"k": 1}', encoding="utf-8")
    called = []
    for name in ("run_fleet", "reconcile_interrupted", "relocate", "migrate_host"):
        monkeypatch.setattr(cli_fleet, name, lambda *a, _n=name: called.append((_n, a[2:])) or {"exit_code": 0})
    args = SimpleNamespace(file=document)
    for command in ("run", "reconcile-interrupted", "relocate", "migrate-host"):
        args.fleet_command = command
        assert root._execute(service, args) == {"exit_code": 0}
    assert called == [("run_fleet", ()), ("reconcile_interrupted", ({"k": 1},)), ("relocate", ({"k": 1},)),
                      ("migrate_host", ({"k": 1},))]


# ----- the Fleet method -> split owner table of composition.cli_fleet ------------------------------------------------------------------------
def test_the_tabled_fleet_methods_are_held_by_the_routed_owner():
    probe = shim()
    classes = {"registry": FleetRegistry, "admission": AdmissionControl, "pause": FleetPause, "recovery": FleetRecovery}
    called = {"register": "registry", "enqueue": "registry", "record_delivery": "registry", "registered": "registry",
              "status": "registry", "reconciliation_required": "registry", "pause": "pause", "resume": "pause",
              "authorize_budget": "pause", "reconcile_interrupted": "recovery", "relocate": "recovery",
              "migrate_host": "recovery"}
    for method, owner in called.items():
        assert probe.OWNER[method] == owner
        assert callable(getattr(classes[owner], method))
    table = cli_fleet.__doc__
    for method in ("register, enqueue, record_delivery", "registered", "status, reconciliation_required",
                   "pause, resume, authorize_budget", "reconcile_interrupted, relocate, migrate_host"):
        assert method in table


# ----- R-c28: bind_goal and the one _parse -------------------------------------------------------------------------------------------------
def test_bind_goal_is_the_same_object_through_entry_and_composition():
    assert entry_operation.bind_goal is cli_operation.bind_goal
    assert fleet_backlog.bind_goal is cli_operation.bind_goal


def test_the_continuation_wiring_uses_the_one_parse():
    assert wiring._parse is fleet_backlog._parse
    assert "def _parse" not in Path(wiring.__file__).read_text(encoding="utf-8")


def test_configured_plan_is_opt_in():
    assert fleet_backlog.configured_plan({}) is None
    assert fleet_backlog.configured_plan({fleet_backlog.PLAN_SETTING: "  "}) is None
    assert fleet_backlog.configured_plan({fleet_backlog.PLAN_SETTING: " p "}) == "p"


# ----- dispatch ---------------------------------------------------------------------------------------------------------------------------
def test_the_dispatch_table_composes_the_fleet_root(monkeypatch):
    tree = ast.parse(Path(entry.__file__).resolve().read_text(encoding="utf-8"))
    tables = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    assert "fleet" in [key.value for key in tables[0].value.keys]
    called = []
    monkeypatch.setattr(root, "run", lambda parsed: called.append((parsed.command, parsed.fleet_command)))
    monkeypatch.setattr(sys, "argv", ["zeus", "fleet", "status"])
    entry.main()
    assert called == [("fleet", "status")]
