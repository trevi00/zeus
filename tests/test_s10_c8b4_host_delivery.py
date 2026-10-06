"""S10 C8b-4: the `host-delivery` root and `composition.cli_host_delivery` (R-c31, E-c21).

MemoryStore, monkeypatched settings and builders; no provider, process, Docker, GitHub, systemd or PostgreSQL is touched. Parity with M7 on a
disposable PostgreSQL is the `entry.cli_host_delivery.pg` compare family (its `tick` case needs a clock mask that does not exist, so `tick`
is covered here); the delivery stages themselves are the ported suites'."""
from __future__ import annotations

import ast
import json
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from _layout import REPO, TESTS

from codex_harness import composition
from codex_harness.composition import cli_host_delivery as wiring
from codex_harness.composition import configuration
from codex_harness.composition.release_verifier import ReleaseVerifier
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.delivery.adapters.host_delivery import ENABLED_SETTING
from codex_harness.delivery.application.host_delivery.controller import DeliveryController
from codex_harness.delivery.application.host_delivery.recovery import Recovery
from codex_harness.delivery.application.host_delivery.registry import DeliveryRegistry
from codex_harness.delivery.application.host_delivery.resumption import Resumption
from codex_harness.delivery.application.host_delivery.stages.verify import Verification
from codex_harness.delivery.application.host_delivery.withdrawal import Withdrawal
from codex_harness.delivery.domain.host_delivery import (
    KIND_MANAGED,
    KIND_MANAGED_SYSTEMD,
    RECOVERY_CONSUMPTION_REARM,
    RECOVERY_CONSUMPTION_RETRY,
    RECOVERY_GENERATION_RESTART,
    REGISTRY_SCHEMA,
    DeliveryRefused,
)
from codex_harness.entry import cli as entry
from codex_harness.entry.cli import host_delivery as root
from codex_harness.kernel.errors import ContractError
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

SHIM = TESTS / "ported" / "m7_delivery.py"
COMPOSITION_DRIVER = REPO / "compare" / "drivers" / "target" / "s7_delivery_composition.py"
CONTROL_DSN = "postgresql://fixture@fixture-host/control"  # a label: nothing connects to it


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime"), "HARNESS_DATABASE_URL": CONTROL_DSN}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(configuration, "runtime_dir", lambda: tmp_path / "runtime")
    return values


@pytest.fixture
def service(settings):
    return composition.ServiceHandle(MemoryStore(), packaged_organization())


def literal(path: Path, name: str):
    """The module-level assignment `name` of `path`, as a literal or, for a tuple of (key, Class), the pairs of names."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            if isinstance(node.value, ast.Tuple):
                return tuple((pair.elts[0].value, pair.elts[1].id) for pair in node.value.elts)
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def args(command, **fields):
    return SimpleNamespace(delivery_command=command, lane=None, **fields)


def targets_file(tmp_path: Path) -> Path:
    path = tmp_path / "targets.json"
    path.write_text(json.dumps({"schema": REGISTRY_SCHEMA, "targets": [
        {"target_id": "fixture", "kind": "process", "root": str(tmp_path / "root"),
         "state_dir": str(tmp_path / "state"), "service": "zeus-canary"}]}), encoding="utf-8")
    return path


# ----- host_delivery_owners builds the split as the shim and the S7 composition driver do -----------------------------------------------
@pytest.mark.parametrize("source", [SHIM, COMPOSITION_DRIVER])
def test_the_owners_are_the_split_objects_of_the_shim_in_its_construction_order(source):
    owners = wiring.host_delivery_owners(MemoryStore(), packaged_organization())
    pairs = literal(source, "OBJECTS")
    assert tuple(vars(owners)) == tuple(key for key, _ in pairs)
    assert {key: type(getattr(owners, key)).__name__ for key in vars(owners)} == dict(pairs)


def test_the_owners_share_the_store_the_org_and_the_ports(service):
    ports = {"github": object(), "hosts": {"process": object()}, "canaries": {"c": object()}, "observer": object(),
             "verifier": object(), "first_activation": object()}
    owners = wiring.host_delivery_owners(service.store, service.org, enabled=True, **ports)
    assert owners.state.store is owners.controller.store is service.store
    assert owners.verification.verifier is ports["verifier"]
    assert owners.controller.enabled is True and owners.registry.enabled is True
    assert owners.withdrawal.github is ports["github"] and owners.resumption.github is ports["github"]
    assert owners.state.hosts is ports["hosts"] and owners.state.observer is ports["observer"]
    assert owners.recovery.first_activation is ports["first_activation"]
    assert owners.controller.claims is owners.controller.settlement  # the one ReleaseQueue the shim passes as both


# ----- the M7 method -> split owner table (docstring) ---------------------------------------------------------------------------------
def test_each_tabled_method_is_held_by_the_routed_owner():
    routes = literal(SHIM, "ROUTES")
    classes = {"registry": DeliveryRegistry, "controller": DeliveryController, "withdrawal": Withdrawal,
               "resumption": Resumption, "recovery": Recovery}
    called = {"register_targets": "registry", "register": "registry", "status": "registry", "tick": "controller",
              "withdraw": "withdrawal", "resume": "resumption", "resume_first_activation": "recovery",
              "resume_consumption_retry": "recovery", "resume_consumption_rearm": "recovery",
              "resume_generation_restart": "recovery"}
    owners = wiring.host_delivery_owners(MemoryStore(), packaged_organization())
    for method, owner in called.items():
        assert routes[method] == owner
        assert callable(getattr(classes[owner], method))
        assert isinstance(getattr(owners, owner), classes[owner])
    table = wiring.__doc__
    for text in ("register_targets (entry `register-targets`)", "tick (entry `tick`, run_loop)", "withdraw (entry `withdraw`)",
                 "resume (entry `resume` without a document)", "resume_first_activation, resume_consumption_retry,"):
        assert text in table
    assert isinstance(owners.verification, Verification) and "stages.verify.Verification" in table


def test_the_entry_calls_only_tabled_owners():
    tree = ast.parse(Path(root.__file__).read_text(encoding="utf-8"))
    execute = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_execute")
    owners = {node.attr for node in ast.walk(execute) if isinstance(node, ast.Attribute)
              and isinstance(node.value, ast.Name) and node.value.id == "delivery"}
    assert owners <= {"withdrawal", "resumption", "recovery", "controller", "verification"}


# ----- controller ---------------------------------------------------------------------------------------------------------------------
def test_the_controller_is_disabled_by_default_and_builds_no_verifier(service, monkeypatch, tmp_path):
    monkeypatch.delenv(ENABLED_SETTING, raising=False)
    git = SimpleNamespace(repository=tmp_path, remote=None)
    delivery = wiring.controller(service, git=git)
    assert delivery.controller.enabled is False and delivery.verification.verifier is None
    assert delivery.state.store is service.store
    assert delivery.state.hosts and delivery.state.canaries  # the real host ports and the fixed canary map are wired


def test_the_host_opt_in_enables_the_controller_and_builds_the_verifier_only_with_a_workspace(service, settings, tmp_path):
    settings[ENABLED_SETTING] = "true"
    assert wiring.controller(service).controller.enabled is True
    assert wiring.controller(service).verification.verifier is None
    git = SimpleNamespace(repository=tmp_path, remote=None)
    delivery = wiring.controller(service, git=git)
    assert isinstance(delivery.verification.verifier, ReleaseVerifier)
    assert not (tmp_path / "runtime" / "verification").exists()  # nothing is created until an attempt runs
    assert wiring.controller(service, enabled=False, git=git).verification.verifier is None


def test_the_gate_authority_is_the_control_fleet_even_for_a_lane_store(service):
    lane = MemoryStore()
    delivery = wiring.controller(service, enabled=False, store=lane)
    assert delivery.state.store is lane and delivery.controller.store is lane
    for kind in (KIND_MANAGED, KIND_MANAGED_SYSTEMD):
        host = delivery.state.hosts.get(kind)
        assert host is not None and host.fleet.store is service.store


# ----- lane routing -------------------------------------------------------------------------------------------------------------------
def test_lane_git_builds_the_lane_workspace_from_the_lane_config(tmp_path):
    (tmp_path / "repo").mkdir()
    lane = {"repository": str(tmp_path / "repo"), "runtime": str(tmp_path / "runtime")}
    workspace = wiring.lane_git(lane, {"HARNESS_GITHUB_REPO": "owner/repo"})
    assert workspace.repository == (tmp_path / "repo").resolve()
    assert workspace.workspaces == (tmp_path / "runtime" / "workspaces").resolve()
    assert workspace.remote == "owner/repo"
    assert wiring.lane_git(lane, {}).remote is None


def lane_fleet(service, tmp_path):
    config = {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 1, "budget": {"per_host": 2, "total": 4},
              "lanes": [{"id": "a", "team": "team-a", "repository": str(tmp_path / "a" / "repo"), "schema": "lane_a",
                         "redis_namespace": "ns-a", "runtime": str(tmp_path / "a" / "runtime")}]}
    (tmp_path / "a" / "repo").mkdir(parents=True)
    FleetRegistry(service.store).register(config)
    return config


def test_resolve_lane_refuses_by_name_and_never_falls_back(service, tmp_path):
    for lane_id in ("", None):
        with pytest.raises(DeliveryRefused) as invalid:
            wiring.resolve_lane(service, lane_id)
        assert invalid.value.reason_code == "lane_invalid" and invalid.value.field == "lane"
    with pytest.raises(DeliveryRefused) as unregistered:
        wiring.resolve_lane(service, "a")
    assert unregistered.value.reason_code == "lane_registry_unregistered"
    lane_fleet(service, tmp_path)
    with pytest.raises(DeliveryRefused) as unknown:
        wiring.resolve_lane(service, "nope")
    assert unknown.value.reason_code == "lane_unknown"
    calls = []
    stores = {}

    def factory(dsn):
        stores["lane"] = MemoryStore()
        return stores["lane"]

    route = wiring.resolve_lane(service, "a", host={"HARNESS_DATABASE_URL": CONTROL_DSN}, store_factory=factory,
                                verify=lambda dsn, schema: calls.append(schema), control_schema=lambda store: "control")
    assert calls == ["lane_a"] and route["lane"]["id"] == "a" and route["store"] is stores["lane"]
    with pytest.raises(DeliveryRefused) as is_control:
        wiring.resolve_lane(service, "a", host={"HARNESS_DATABASE_URL": CONTROL_DSN}, store_factory=factory,
                            verify=lambda dsn, schema: None, control_schema=lambda store: "lane_a")
    assert is_control.value.reason_code == "lane_is_control"


def test_the_control_schema_probe_skips_a_store_without_a_dsn():
    assert wiring._control_schema(MemoryStore()) is None


# ----- an absent profile refuses where an executor is built -------------------------------------------------------------------------
def test_an_absent_composition_profile_refuses_where_the_executor_is_built(service, monkeypatch, tmp_path):
    monkeypatch.delenv("ZEUS_COMPOSITION_PROFILE", raising=False)
    monkeypatch.setattr(wiring, "_observer", lambda _service: None)
    with pytest.raises(ContractError) as refused:
        root._execute(service, args("tick", plan=None))
    assert str(refused.value) == "composition_profile_unknown"
    assert root._refusal(refused.value)["reason_code"] == "contract_refused"
    with pytest.raises(ContractError) as plan:
        root._execute(service, args("register", revision="a" * 40, path="plan.json"))
    assert str(plan.value) == "composition_profile_unknown"
    # status and register-targets build no executor and need no profile
    assert root._execute(service, args("status", plan=None))["exit_code"] == 0
    assert root._execute(service, args("register-targets", file=targets_file(tmp_path)))["exit_code"] == 0


# ----- the entry bodies --------------------------------------------------------------------------------------------------------------
def test_status_of_nothing_registered_and_of_an_unknown_plan(service, monkeypatch):
    monkeypatch.delenv(ENABLED_SETTING, raising=False)
    every = root._execute(service, args("status", plan=None))
    assert every["exit_code"] == 0 and every["registered"] is False and every["enabled"] is False
    assert root._execute(service, args("status", plan="nope"))["exit_code"] == 1


def test_register_targets_reads_the_file_as_m7_did(service, tmp_path):
    receipt = root._execute(service, args("register-targets", file=targets_file(tmp_path)))
    assert receipt["exit_code"] == 0 and receipt["registered"] is True and receipt["targets"] == ["fixture"]
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError) as raised:
        root._execute(service, args("register-targets", file=bad))
    assert root._refusal(raised.value) == {"status": "refused", "reason_code": "error", "error_type": "JSONDecodeError",
                                           "exit_code": 1}


def test_tick_runs_the_controller_owner_and_closes_the_observer(service, monkeypatch, tmp_path):
    closed = []
    monkeypatch.delenv(ENABLED_SETTING, raising=False)
    monkeypatch.setattr(wiring, "_git", lambda _service: SimpleNamespace(repository=tmp_path, remote=None))
    monkeypatch.setattr(wiring, "_observer", lambda _service: SimpleNamespace(close=lambda: closed.append(True)))
    idle = root._execute(service, args("tick", plan=None))
    assert idle["exit_code"] == 0 and idle["outcome"] == "idle" and "lane" not in idle and closed == [True]


def test_withdraw_and_resume_are_routed_to_their_owners(service, monkeypatch, tmp_path):
    seen = []
    recovery = SimpleNamespace(**{name: (lambda *a, _n=name: seen.append((_n, a)) or {"r": _n}) for name in (
        "resume_first_activation", "resume_consumption_retry", "resume_consumption_rearm", "resume_generation_restart")})
    double = SimpleNamespace(
        withdrawal=SimpleNamespace(withdraw=lambda *a: seen.append(("withdraw", a)) or {"w": 1}),
        resumption=SimpleNamespace(resume=lambda *a: seen.append(("resume", a)) or {"r": "resume"}), recovery=recovery)
    monkeypatch.setattr(wiring, "_git", lambda _service: SimpleNamespace(repository=tmp_path))
    monkeypatch.setattr(wiring, "_observer", lambda _service: None)
    monkeypatch.setattr(wiring, "controller", lambda _service, **kwargs: double)
    owner = {"plan": "p", "plan_sha256": "c" * 64, "evidence": "sha256:" + "e" * 64}
    assert root._execute(service, args("withdraw", reason="reviewed_base_moved", **owner))["w"] == 1
    assert root._execute(service, args("resume", document=None, **owner))["r"] == "resume"
    for kind, name in ((RECOVERY_CONSUMPTION_RETRY, "resume_consumption_retry"),
                       (RECOVERY_CONSUMPTION_REARM, "resume_consumption_rearm"),
                       (RECOVERY_GENERATION_RESTART, "resume_generation_restart"), ("other", "resume_first_activation")):
        document = tmp_path / "document.json"
        document.write_text(json.dumps({"kind": kind}), encoding="utf-8")
        assert root._execute(service, args("resume", document=str(document), **owner))["r"] == name
    assert [name for name, _ in seen] == ["withdraw", "resume", "resume_consumption_retry", "resume_consumption_rearm",
                                          "resume_generation_restart", "resume_first_activation"]
    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text("{not json", encoding="utf-8")
    with pytest.raises(DeliveryRefused) as refused:
        root._execute(service, args("resume", document=str(unreadable), **owner))
    assert refused.value.reason_code == "first_activation_document_unreadable"


def test_a_lane_route_resolves_before_any_store_git_or_observer_is_touched(service, monkeypatch):
    refused = DeliveryRefused("lane_unknown", "lane")
    monkeypatch.setattr(wiring, "resolve_lane", lambda _service, _lane: (_ for _ in ()).throw(refused))
    for name in ("_git", "_observer", "controller"):
        monkeypatch.setattr(wiring, name, lambda *a, **k: pytest.fail("reached before the lane resolved"))
    for command in ("register-targets", "register", "status", "tick", "run"):
        with pytest.raises(DeliveryRefused):
            root._execute(service, SimpleNamespace(delivery_command=command, lane="x"))


def test_the_entry_body_emits_a_refusal_and_exits_one(service, monkeypatch, capsys):
    monkeypatch.setattr(composition, "build", lambda: service)
    monkeypatch.setattr(wiring, "resolve_lane", lambda _service, _lane: (_ for _ in ()).throw(
        DeliveryRefused("lane_unknown", "lane")))
    with pytest.raises(SystemExit) as exited:
        root.run(SimpleNamespace(delivery_command="status", lane="x", plan=None))
    assert exited.value.code == 1
    assert json.loads(capsys.readouterr().out) == {"status": "refused", "reason_code": "lane_unknown",
                                                   "error_type": "DeliveryRefused", "exit_code": 1}


# ----- run_loop ----------------------------------------------------------------------------------------------------------------------
class Boundary:
    def __init__(self):
        self.calls = []

    def reset(self):
        self.calls.append("reset")

    def signal(self):
        self.calls.append("signal")


def test_run_loop_counts_the_outcomes_and_restores_the_signal_handlers():
    before = signal.getsignal(signal.SIGTERM)
    boundary = Boundary()
    outcomes = iter(["idle", "pending", "idle"])
    controller = SimpleNamespace(tick=lambda: {"outcome": next(outcomes)})
    sleeps = []
    summary = wiring.run_loop(controller, verifier=SimpleNamespace(boundary=boundary), interval=0, max_ticks=3,
                              sleep=sleeps.append)
    assert summary == {"schema": "urn:zeus:host-delivery-run:1", "ticks": 3, "outcomes": {"idle": 2, "pending": 1},
                       "stopped": False}
    assert sleeps == [1, 1] and boundary.calls == ["reset"] and signal.getsignal(signal.SIGTERM) is before


def test_run_loop_reads_the_verifier_from_the_delivery_as_m7_did_and_stops_on_a_signal():
    boundary = Boundary()

    def tick():
        signal.raise_signal(signal.SIGTERM)  # the loop's own handler, not the process's
        return {"outcome": "pending"}

    delivery = SimpleNamespace(tick=tick, verifier=SimpleNamespace(boundary=boundary))
    summary = wiring.run_loop(delivery, interval=1, max_ticks=5, sleep=lambda _s: None)
    # M7's loop sleeps once after the tick in flight, then sees the flag
    assert summary["stopped"] is True and summary["ticks"] == 1 and boundary.calls == ["reset", "signal"]


def test_run_once_through_the_entry_runs_one_idle_tick(service, monkeypatch, tmp_path):
    monkeypatch.delenv(ENABLED_SETTING, raising=False)
    monkeypatch.setattr(wiring, "_git", lambda _service: SimpleNamespace(repository=tmp_path, remote=None))
    monkeypatch.setattr(wiring, "_observer", lambda _service: None)
    summary = root._execute(service, args("run", once=True, interval=15, max_ticks=0))
    assert summary == {"schema": "urn:zeus:host-delivery-run:1", "ticks": 1, "outcomes": {"idle": 1}, "stopped": False,
                       "exit_code": 0}


# ----- the seams the entry layer cannot import ----------------------------------------------------------------------------------------
def test_the_adapter_seams_of_the_entry_layer(tmp_path, settings):
    assert wiring.configured_enabled({}) is False and wiring.configured_enabled({ENABLED_SETTING: " Yes "}) is True
    assert wiring._host_settings() == settings and wiring._settings() == settings
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text('{"a": 1}', encoding="utf-8")
    bad.write_text("{", encoding="utf-8")
    assert wiring.read_json(good) == {"a": 1} and wiring.read_json(bad) is None
    assert wiring.read_json(tmp_path / "absent.json") is None


def test_a_malformed_host_configuration_invents_none(monkeypatch):
    def broken():
        raise ValueError("labelled")

    monkeypatch.setattr(configuration, "settings", broken)
    assert wiring._host_settings() == {}


# ----- dispatch ---------------------------------------------------------------------------------------------------------------------------
def test_the_dispatch_table_composes_the_host_delivery_root(monkeypatch):
    tree = ast.parse(Path(entry.__file__).resolve().read_text(encoding="utf-8"))
    tables = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    assert "host-delivery" in [key.value for key in tables[0].value.keys]
    called = []
    monkeypatch.setattr(root, "run", lambda parsed: called.append((parsed.command, parsed.delivery_command)))
    monkeypatch.setattr(sys, "argv", ["zeus", "host-delivery", "status"])
    entry.main()
    assert called == [("host-delivery", "status")]
