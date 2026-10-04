"""S10 C6a: the `operate` and `autonomous` roots and the `composition.cli_operation` builders (R-c24, E-c21).

MemoryStore, monkeypatched settings and builders; no provider, Docker, Redis server or PostgreSQL is touched. Parity with M7 on a
disposable PostgreSQL is the `entry.cli_operation.pg` compare family."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import (
    cli_bus,
    cli_operation,
    cli_research,
    configuration,
    observation,
    operation,
)
from codex_harness.coordination.application import autonomous as autonomous_use_case
from codex_harness.coordination.application import council as council_use_case
from codex_harness.coordination.application.autonomous import AutonomousRefused
from codex_harness.entry import cli as entry
from codex_harness.entry.cli import autonomous, operate
from codex_harness.entry.cli import operation as entry_operation
from codex_harness.entry.cli.dge import _repository_identity
from codex_harness.intake.domain import operation_manifest
from codex_harness.kernel.errors import ContractError
from codex_harness.research.domain import council
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore
from codex_harness.storage.adapters.redis_bus import run_namespace

ARGS = SimpleNamespace(file={"id": "op-001"}, operate_command="run", autonomous_command="run")
PROFILE = {"profile_digest": "d" * 64}
ISOLATION = SimpleNamespace(config={"mode": "docker", "image": "i", "limits": {}, "digest": "x"})


class Observer:
    def __init__(self, events):
        self.events = events

    def close(self):
        self.events.append("observer.close")


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_REDIS_NAMESPACE": "ns", "HARNESS_RUNTIME_DIR": str(tmp_path / "runtime")}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(configuration, "runtime_dir", lambda: tmp_path / "runtime")
    return values


@pytest.fixture
def service(settings):
    return composition.ServiceHandle(MemoryStore(), packaged_organization())


@pytest.fixture
def wired(monkeypatch, service):
    """Every collaborator before the use case, recording the order M7 `operation_cli.run` called them in."""
    events, built = [], {}

    def record(name, value):
        def call(*args, **kwargs):
            events.append(name)
            built[name] = (args, kwargs)
            return value
        return call

    monkeypatch.setattr(entry_operation, "read_manifest", record("manifest.read", {"id": "op-001"}))
    monkeypatch.setattr(entry_operation, "read_document", record("manifest.read", {"id": "op-001"}))
    monkeypatch.setattr(cli_operation, "packaged_policy", lambda: "packaged")
    monkeypatch.setattr(operation_manifest, "validate_manifest", record("manifest.validate", {"id": "op-001"}))
    monkeypatch.setattr(council, "validate_any_manifest", record("manifest.validate", {"id": "op-001"}))
    monkeypatch.setattr(cli_operation, "execution_policy", record("policy", "policy"))
    monkeypatch.setattr(operation, "host_evidence_profile", record("profile", PROFILE))
    monkeypatch.setattr(operation, "host_isolation", record("isolation", None))
    monkeypatch.setattr(cli_research, "git_source", record("source", "source"))
    monkeypatch.setattr(entry_operation, "bind_goal", record("goal", {"path": "goal"}))
    monkeypatch.setattr(cli_operation, "identity", record("identity", {"bound": 1}))
    monkeypatch.setattr(observation, "build_observer", lambda store, name: events.append("observer") or Observer(events))
    monkeypatch.setattr(observation, "build_collector", record("collector", "collector"))
    monkeypatch.setattr(cli_operation, "session_owner", record("session_owner", {}))
    monkeypatch.setattr(cli_operation, "call_budget", record("budget", "budget"))
    monkeypatch.setattr(cli_bus, "bus", record("bus", "bus"))
    monkeypatch.setattr(operation, "build_executor", record("executor", SimpleNamespace(artifacts="artifacts")))
    return SimpleNamespace(events=events, built=built, service=service)


def test_operate_run_wires_the_executor_in_m7_order_without_knowledge(monkeypatch, wired):
    ran = []
    monkeypatch.setattr(cli_operation, "operation", lambda *args, **kwargs: SimpleNamespace(
        run=lambda manifest, bound, goal: ran.append((manifest, bound, goal)) or {"exit_code": 0}))
    assert operate._run(wired.service, ARGS) == {"exit_code": 0}
    assert wired.events == ["manifest.read", "manifest.validate", "policy", "profile", "isolation", "source", "goal",
                            "identity", "observer", "session_owner", "executor", "bus", "budget", "collector",
                            "observer.close"]
    args, kwargs = wired.built["executor"]
    assert kwargs["knowledge"] is False and kwargs["evidence_profile"] is PROFILE and "isolation" not in kwargs
    assert kwargs["execution_policy"] == "policy" and args == (wired.service,)
    assert wired.built["identity"][1] == {}
    assert ran == [({"id": "op-001"}, {"bound": 1}, {"path": "goal"})]


def test_operate_run_passes_the_selected_isolation_to_the_executor_and_the_identity(monkeypatch, wired):
    monkeypatch.setattr(operation, "host_isolation", lambda profile: ISOLATION)
    monkeypatch.setattr(cli_operation, "operation", lambda *args, **kwargs: SimpleNamespace(run=lambda *a: {"exit_code": 0}))
    operate._run(wired.service, ARGS)
    assert wired.built["executor"][1]["isolation"] is ISOLATION
    assert wired.built["identity"][1] == {"isolation": ISOLATION.config}


def test_operate_run_closes_the_observer_when_the_executor_or_the_operation_fails(monkeypatch, wired):
    def refuse(*args, **kwargs):
        raise ContractError("executor_refused")
    monkeypatch.setattr(operation, "build_executor", refuse)
    with pytest.raises(ContractError, match="executor_refused"):
        operate._run(wired.service, ARGS)
    assert wired.events[-3:] == ["observer", "session_owner", "observer.close"]
    wired.events.clear()
    monkeypatch.setattr(operation, "build_executor", lambda *a, **k: SimpleNamespace(artifacts=None))
    monkeypatch.setattr(cli_operation, "operation", lambda *a, **k: SimpleNamespace(run=refuse))
    with pytest.raises(ContractError):
        operate._run(wired.service, ARGS)
    assert wired.events[-1] == "observer.close"


def test_operate_run_prints_the_refusal_and_exits_1(monkeypatch, wired, capsys):
    monkeypatch.setattr(composition, "build", lambda: wired.service)
    monkeypatch.setattr(entry_operation, "bind_goal", lambda manifest, source: (_ for _ in ()).throw(ContractError("x")))
    with pytest.raises(SystemExit) as raised:
        operate.run(SimpleNamespace(operate_command="run", file="f"))
    assert raised.value.code == 1
    assert json.loads(capsys.readouterr().out) == {"status": "refused", "reason_code": "contract_refused",
                                                    "error_type": "ContractError", "exit_code": 1}


def test_operate_status_reads_the_store_only_and_refuses_an_unknown_id(wired, monkeypatch, capsys):
    monkeypatch.setattr(composition, "build", lambda: wired.service)
    with pytest.raises(SystemExit) as raised:
        operate.run(SimpleNamespace(operate_command="status", operation_id="op-unknown"))
    assert raised.value.code == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "contract_refused"
    assert wired.events == [], "no profile, observer, executor, bus or budget is built"


def test_an_absent_profile_refuses_before_any_provider(monkeypatch, wired):
    # E-c21: the target-only behaviour (M7 had no profile); OWNER-DECISIONS-S10 #10. `operate`, then `autonomous`.
    monkeypatch.undo()
    monkeypatch.setattr(configuration, "settings", lambda: {})
    for module, run in ((operate, operate._run), (autonomous, autonomous._run)):
        events = []
        monkeypatch.setattr(entry_operation, "read_manifest", lambda path: {"id": "op-001"})
        monkeypatch.setattr(entry_operation, "read_document", lambda path, label: {"id": "op-001"})
        monkeypatch.setattr(operation_manifest, "validate_manifest", lambda document, policy: {"id": "op-001"})
        monkeypatch.setattr(council, "validate_any_manifest", lambda document, policy: {"id": "op-001"})
        monkeypatch.setattr(cli_operation, "execution_policy", lambda manifest, host: "policy")
        monkeypatch.setattr(cli_operation, "identity", lambda *a, **k: {})
        monkeypatch.setattr(operation, "host_evidence_profile", lambda: None)
        monkeypatch.setattr(operation, "host_isolation", lambda profile: None)
        monkeypatch.setattr(cli_research, "git_source", lambda root: None)
        monkeypatch.setattr(entry_operation, "bind_goal", lambda manifest, source: {})
        monkeypatch.setattr(observation, "build_observer", lambda store, name: Observer(events))
        monkeypatch.setattr(cli_operation, "session_owner", lambda *a, **k: {})
        with pytest.raises(ContractError, match="composition_profile_unknown"):
            run(composition.ServiceHandle(MemoryStore(), packaged_organization()), ARGS)
        assert events == ["observer.close"], module.__name__
    refused = autonomous._execute(composition.ServiceHandle(MemoryStore(), packaged_organization()), ARGS)
    assert refused == {"status": "refused", "reason_code": "contract_refused", "error_type": "ContractError", "exit_code": 1}


class Recording:
    """A LABELLED stand-in for AutonomousRun and CouncilRun: records the arguments it is given."""
    made = []

    def __init__(self, service, executor, bus, workflow, budget, collector, **wiring):
        self.arguments = (service, executor, bus, wiring)
        Recording.made.append((type(self).__name__, self))

    def run(self, manifest, bound, goal):
        return {"exit_code": 0, "namespace": self.arguments[2].namespace}


class AutonomousRecording(Recording):
    pass


class CouncilRecording(Recording):
    pass


@pytest.fixture
def run_scoped(monkeypatch, wired):
    Recording.made.clear()
    monkeypatch.setattr(autonomous_use_case, "AutonomousRun", AutonomousRecording)
    monkeypatch.setattr(council_use_case, "CouncilRun", CouncilRecording)
    monkeypatch.setattr(composition, "redis_url", lambda: "redis://a.example:6379/0")
    monkeypatch.setattr(cli_bus, "bus", cli_bus.bus)
    monkeypatch.setattr(council, "profile", lambda manifest: {"version": 1})
    monkeypatch.setattr(cli_operation, "read_only_snapshot", lambda: "snapshot")
    return wired


def test_autonomous_run_hands_the_run_scoped_bus_and_picks_the_v1_run(monkeypatch, run_scoped):
    receipts = []
    for run_id in ("rp-002.c001", "rp-003.c001", "rp-002.c001"):
        monkeypatch.setattr(council, "validate_any_manifest", lambda document, policy, run_id=run_id: {"id": run_id})
        receipts.append(autonomous._run(run_scoped.service, ARGS))
    namespaces = [receipt["namespace"] for receipt in receipts]
    assert namespaces == [run_namespace("ns", "rp-002.c001"), run_namespace("ns", "rp-003.c001"),
                          run_namespace("ns", "rp-002.c001")]
    assert "ns" not in namespaces and namespaces[0] != namespaces[1], "never the old global bus"
    assert [name for name, _ in Recording.made] == ["AutonomousRecording"] * 3
    service, executor, bus, wiring = Recording.made[0][1].arguments
    assert wiring["observer"].__class__ is Observer and wiring["repository"] == _repository_identity(configuration.repository_root())
    assert "snapshot" not in wiring and executor.artifacts == "artifacts"
    assert run_scoped.built["executor"][1]["knowledge"] is False


def test_autonomous_run_picks_the_council_for_profile_version_2(monkeypatch, run_scoped):
    monkeypatch.setattr(council, "profile", lambda manifest: {"version": 2})
    monkeypatch.setattr(council, "validate_any_manifest", lambda document, policy: {"id": "council-001"})
    receipt = autonomous._run(run_scoped.service, ARGS)
    assert [name for name, _ in Recording.made] == ["CouncilRecording"]
    _, executor, bus, wiring = Recording.made[0][1].arguments
    assert receipt["namespace"] == run_namespace("ns", "council-001") == bus.namespace
    assert wiring["snapshot"] == "snapshot" and wiring["artifacts"] == "artifacts"


def test_autonomous_status_is_the_store_read_and_refuses_an_unknown_run(service, capsys, monkeypatch):
    with pytest.raises(AutonomousRefused, match="unknown_run"):
        autonomous._status(service, SimpleNamespace(run_id="auto-unknown"))
    monkeypatch.setattr(composition, "build", lambda: service)
    with pytest.raises(SystemExit) as raised:
        autonomous.run(SimpleNamespace(autonomous_command="status", run_id="auto-unknown"))
    assert raised.value.code == 1
    assert json.loads(capsys.readouterr().out) == {"status": "refused", "reason_code": "unknown_run",
                                                    "error_type": "AutonomousRefused", "exit_code": 1}


def test_the_builders_wire_the_ports_the_s8_use_cases_take(service):
    from codex_harness.coordination.application.autonomous import AutonomousRun
    from codex_harness.coordination.application.council import CouncilRun
    from codex_harness.coordination.application.operation import Operation
    from codex_harness.research.application.dge import DebateSessions

    run = cli_operation.autonomous_run(service)
    assert type(run) is AutonomousRun and run.sessions_factory is DebateSessions and run.service.store is service.store
    assert callable(run.service.flusher.flush) and callable(run.service.record_incident)
    assert type(cli_operation.council_run(service)) is CouncilRun
    assert type(run.operation_factory(None, None, None, None, None)) is Operation
    assert type(cli_operation.operation(service)) is Operation


def test_the_bus_of_a_run_is_scoped_by_the_manifest_id(settings, monkeypatch):
    monkeypatch.setattr(composition, "redis_url", lambda: "redis://a.example:6379/0")
    bus = cli_operation.run_bus("auto-001")
    assert bus.namespace == run_namespace("ns", "auto-001") and bus.route["run_id"] == "auto-001"


def test_session_owner_is_empty_without_a_continuation_binding(service):
    assert cli_operation.session_owner(service, "op-001") == {}


def test_bind_goal_refuses_an_absent_base_and_an_absent_goal():
    from codex_harness.coordination.application.operation import OperationRefused

    manifest = {"base_revision": "a" * 40, "goal": {"path": "GOAL.md"}}
    with pytest.raises(OperationRefused, match="base_revision_missing"):
        entry_operation.bind_goal(manifest, SimpleNamespace(commit_exists=lambda revision: False))
    with pytest.raises(OperationRefused, match="goal_missing_at_base"):
        entry_operation.bind_goal(manifest, SimpleNamespace(commit_exists=lambda revision: True,
                                                            blob=lambda revision, path: (None, b"")))


def test_the_dispatch_table_composes_both_roots(monkeypatch):
    tree = ast.parse((Path(entry.__file__).resolve()).read_text(encoding="utf-8"))
    tables = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    keys = [key.value for key in tables[0].value.keys]
    assert "operate" in keys and "autonomous" in keys
    called = []
    monkeypatch.setattr(operate, "run", lambda args: called.append(args.command))
    monkeypatch.setattr(autonomous, "run", lambda args: called.append(args.command))
    import sys
    for argv in (["operate", "status", "op"], ["autonomous", "status", "run"]):
        monkeypatch.setattr(sys, "argv", ["zeus", *argv])
        entry.main()
    assert called == ["operate", "autonomous"]
