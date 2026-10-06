"""S10 C6c: the `desk` and `research-program` roots and the `composition.cli_desk` / `composition.cli_research_program` builders (R-c26, E-c21).

MemoryStore, monkeypatched settings and builders; no provider, Docker, Redis server or PostgreSQL is touched. Parity with M7 on a
disposable PostgreSQL is the `entry.cli_desk_program.pg` compare family."""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from _layout import REPO
from filelock import FileLock

from codex_harness import composition
from codex_harness.composition import (
    cli,
    cli_bus,
    cli_desk,
    cli_research,
    cli_research_program,
    configuration,
    observation,
    operation,
)
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.domain.operation import LEAD
from codex_harness.entry import cli as entry
from codex_harness.entry.cli import autonomous, desk, research_program
from codex_harness.intake.domain.frontdesk import DeskRefused
from codex_harness.kernel.errors import ContractError
from codex_harness.research.domain.research_program import ProgramRefused, validate_config
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.routing.domain.model_selection import select_model
from codex_harness.storage.adapters.memory_store import MemoryStore

REVISION = "a" * 40
RUN_ARGS = SimpleNamespace(revision=REVISION, once=True, desk_command="run")


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


# ----- composition.cli_desk -----------------------------------------------------------------------------
def test_effective_ceilings_are_the_registered_fleet_budget_and_one_one_when_unregistered(monkeypatch):
    assert cli_desk.effective_ceilings(MemoryStore()) == {"per_host": 1, "total": 1}
    monkeypatch.setattr(FleetRegistry, "registered",
                        lambda self: {"config": {"budget": {"per_host": 4, "total": 9, "accounting": "subscription"}}})
    assert cli_desk.effective_ceilings(MemoryStore()) == {"per_host": 4, "total": 9, "accounting": "subscription"}


def test_build_runner_wires_no_knowledge_and_the_design_model_label(monkeypatch, service):
    built = {}
    observer = SimpleNamespace(close=lambda: None)

    def executor(*args, **kwargs):
        built["executor"] = (args, kwargs)
        return "executor"

    monkeypatch.setattr(operation, "build_executor", executor)
    monkeypatch.setattr(cli_bus, "bus", lambda: "bus")
    monkeypatch.setattr(cli, "workflow", lambda handle: "workflow")
    monkeypatch.setattr(observation, "build_collector", lambda store, seen: ("collector", seen))
    runner = cli_desk.build_runner(service, RUN_ARGS, observer)
    args, kwargs = built["executor"]
    assert args == (service,) and kwargs == {"observer": observer, "knowledge": False}
    model = select_model("design").requested_model
    wrapped = runner.executor
    assert (wrapped.executor, wrapped.purpose, wrapped.model, wrapped.ceilings) == ("executor", "frontdesk", model,
                                                                                    {"per_host": 1, "total": 1})
    assert wrapped.labels("turn", "agent") == ("codex", model)
    assert (runner.bus, runner.workflow, runner.observer, runner.collector) == ("bus", "workflow", observer,
                                                                                ("collector", observer))
    assert runner.desk.base_revision == REVISION and runner.service.store is service.store
    assert runner.service.org is service.org and runner.service.flusher is not None


def test_build_runner_refuses_an_invalid_revision_before_any_executor(monkeypatch, service):
    monkeypatch.setattr(operation, "build_executor", lambda *a, **k: pytest.fail("no executor for a bad revision"))
    with pytest.raises(DeskRefused):
        cli_desk.build_runner(service, SimpleNamespace(revision="abc"), SimpleNamespace())


def test_an_absent_composition_profile_refuses_the_desk_wiring(service):
    with pytest.raises(ContractError, match="composition_profile_unknown"):
        cli_desk.build_runner(service, RUN_ARGS, SimpleNamespace(close=lambda: None))


def test_a_held_desk_lock_is_refused_and_builds_nothing(monkeypatch, service, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(observation, "build_observer", lambda *a, **k: pytest.fail("no observer behind a held lock"))
    held = FileLock(str(runtime / "frontdesk.lock"), timeout=0)
    held.acquire()
    try:
        assert cli_desk.run_desk(service, RUN_ARGS) == {"status": "refused", "reason_code": "desk_lock_busy", "exit_code": 1}
    finally:
        held.release()


def test_the_observer_and_lock_are_released_when_the_wiring_fails(monkeypatch, service, tmp_path):
    closed, roles = [], []
    monkeypatch.setattr(observation, "build_observer",
                        lambda store, name, role=None: roles.append((name, role)) or SimpleNamespace(close=lambda: closed.append(True)))

    def broken(handle, args, observer):
        raise RuntimeError("injected wiring failure")

    monkeypatch.setattr(cli_desk, "build_runner", broken)
    with pytest.raises(RuntimeError, match="injected"):
        cli_desk.run_desk(service, RUN_ARGS)
    assert closed == [True] and roles == [("cli.desk", LEAD)]
    lock = FileLock(str(tmp_path / "runtime" / "frontdesk.lock"), timeout=0)
    lock.acquire()  # not leaked
    lock.release()


def test_run_desk_reports_a_stopped_run_as_a_failure(monkeypatch, service):
    monkeypatch.setattr(observation, "build_observer", lambda *a, **k: SimpleNamespace(close=lambda: None))
    runner = SimpleNamespace(run=lambda once: {"failure": {"action": "unavailable"}, "stopped": True}, stop=lambda: None)
    monkeypatch.setattr(cli_desk, "build_runner", lambda handle, args, observer: runner)
    result = cli_desk.run_desk(service, RUN_ARGS)
    assert result == {"desk": "frontdesk", "revision": REVISION, "failure": {"action": "unavailable"}, "stopped": True,
                      "exit_code": 1}


# ----- entry.cli.desk -----------------------------------------------------------------------------------
def test_desk_status_is_the_store_read_and_builds_no_executor(monkeypatch, service):
    monkeypatch.setattr(operation, "build_executor", lambda *a, **k: pytest.fail("status builds no executor"))
    monkeypatch.setattr(observation, "build_observer", lambda *a, **k: pytest.fail("status builds no observer"))
    monkeypatch.setattr(cli_bus, "bus", lambda: pytest.fail("status builds no bus"))
    result = desk._execute(service, SimpleNamespace(desk_command="status", revision=REVISION))
    assert result["exit_code"] == 0 and result["sessions"] == []


def test_desk_refusal_is_a_code_and_a_type_only():
    assert desk._desk_refusal(DeskRefused("invalid_revision")) == {
        "status": "refused", "reason_code": "invalid_revision", "error_type": "DeskRefused", "exit_code": 1}
    assert desk._desk_refusal(RuntimeError("secret text"))["error_type"] == "RuntimeError"


def test_desk_run_prints_the_refusal_and_exits_one(monkeypatch, service, capsys):
    monkeypatch.setattr(composition, "build", lambda: service)
    with pytest.raises(SystemExit) as raised:
        desk.run(SimpleNamespace(desk_command="status", revision="abc"))
    assert raised.value.code == 1
    assert '"reason_code": "invalid_revision"' in capsys.readouterr().out


# ----- entry.cli.research_program / composition.cli_research_program ------------------------------------
class Wired:
    def __init__(self):
        self.built, self.events = {}, []


@pytest.fixture
def wired(monkeypatch, service, tmp_path):
    state = Wired()

    def record(name, value):
        def call(*args, **kwargs):
            state.events.append(name)
            state.built[name] = (args, kwargs)
            return value
        return call

    monkeypatch.setattr(cli_research_program, "research_program", record("programs", "programs"))
    monkeypatch.setattr(cli_research_program, "artifacts", record("artifacts", "artifacts"))
    monkeypatch.setattr(cli_research_program, "pressure_evaluator", record("pressure", "evaluator"))
    state.sources = SimpleNamespace(github_detail="detail")
    monkeypatch.setattr(cli_research_program, "research_sources", record("sources", state.sources))
    monkeypatch.setattr(cli_research, "git_source", record("source", "source"))
    monkeypatch.setattr(cli_research_program, "git_capture", record("capture", "capture"))
    monkeypatch.setattr(cli_research_program, "call_budget", record("budget", "budget"))
    monkeypatch.setattr(observation, "build_observer", record("observer", "observer"))
    runner = SimpleNamespace(run=lambda program_id, ticks, intent: {"id": program_id, "ticks": [{"reserved": False}]})
    monkeypatch.setattr(cli_research_program, "program_runner", record("runner", runner))
    state.service = service
    return state


def run_args(**overrides):
    return SimpleNamespace(**{"program_id": "rp-001", "ticks": 1, "intent": "user_request", "cycle_owner": None, **overrides})


def test_run_passes_the_autonomous_run_as_the_council(wired):
    result = research_program._run(wired.service, run_args())
    assert result == {"id": "rp-001", "ticks": [{"reserved": False}], "exit_code": 0}
    args, kwargs = wired.built["runner"]
    assert kwargs["council"] is autonomous._run and kwargs["github_detail"] == "detail"
    assert args[:6] == (wired.service, "programs", wired.sources, "source", "capture", "budget")
    assert wired.built["sources"][1] == {"pressure": None} and "pressure" not in wired.events and "observer" not in wired.events


def test_a_proactive_run_builds_the_pressure_evaluator_over_the_audit_observer(wired):
    research_program._run(wired.service, run_args(intent="proactive"))
    assert wired.events.index("observer") < wired.events.index("pressure") < wired.events.index("sources")
    assert wired.built["observer"][0][1] == "discovery-pressure"
    assert wired.built["pressure"][0] == (wired.service.store, "observer")
    assert wired.built["sources"][1] == {"pressure": "evaluator"}


def test_a_cycle_owner_token_reaches_the_program_state_machine(wired):
    owner = "c" * 64
    research_program._run(wired.service, run_args(cycle_owner=owner))
    token = wired.built["programs"][1]["token"]
    assert token() == owner


@pytest.mark.parametrize("overrides, code", [({"ticks": 0}, "ticks_invalid"), ({"ticks": 101}, "ticks_invalid"),
                                             ({"ticks": True}, "ticks_invalid"),
                                             ({"ticks": 2, "cycle_owner": "c" * 64}, "cycle_owner_invalid"),
                                             ({"ticks": 1, "cycle_owner": "nope"}, "cycle_owner_invalid")])
def test_run_refuses_a_bad_tick_count_or_owner_before_any_adapter(wired, overrides, code):
    with pytest.raises(ProgramRefused) as raised:
        research_program._run(wired.service, run_args(**overrides))
    assert raised.value.reason_code == code and wired.events == []


def test_a_failed_tick_is_a_non_zero_exit(wired, monkeypatch):
    runner = SimpleNamespace(run=lambda *a, **k: {"ticks": [{"result": "failed"}]})
    monkeypatch.setattr(cli_research_program, "program_runner", lambda *a, **k: runner)
    assert research_program._run(wired.service, run_args())["exit_code"] == 1


def test_execute_turns_any_failure_into_a_code_and_a_type(service):
    result = research_program._execute(service, SimpleNamespace(research_program_command="status", program_id="rp-nope"))
    assert result == {"status": "refused", "reason_code": "unknown_program", "error_type": "ProgramRefused", "exit_code": 1}


def test_recover_of_an_unknown_schema_reaches_the_owner_with_the_probe_of_the_named_run(monkeypatch, service, tmp_path):
    document = tmp_path / "request.json"
    document.write_text('{"schema": "urn:zeus:research-dispatch-recovery:9", "failed": {"run_id": "run-1"}}', encoding="utf-8")
    probes = []
    monkeypatch.setattr(cli_research_program, "transport_probe", lambda run_id: probes.append(run_id) or "probe")
    with pytest.raises(ProgramRefused) as raised:
        research_program._recover(service, SimpleNamespace(file=document))
    assert raised.value.reason_code == "recovery_request_invalid" and probes == ["run-1"]


def test_recover_of_a_revocation_builds_no_probe_and_a_successor_reads_the_evidence(monkeypatch, service, tmp_path):
    from codex_harness.research.domain.research_investigations import REVOCATION_SCHEMA, SUCCESSOR_SCHEMA
    monkeypatch.setattr(cli_research_program, "transport_probe", lambda run_id: pytest.fail("no transport for this schema"))
    seen = []
    monkeypatch.setattr(cli_research_program, "recovery_evidence", lambda: seen.append("evidence") or "evidence")
    for schema in (REVOCATION_SCHEMA, SUCCESSOR_SCHEMA):
        document = tmp_path / "request.json"
        document.write_text('{"schema": "' + schema + '"}', encoding="utf-8")
        with pytest.raises(ProgramRefused):
            research_program._recover(service, SimpleNamespace(file=document))
    assert seen == ["evidence"]


def program_document(head: str) -> dict:
    path = REPO / "compare" / "drivers" / "common" / "s10_cli_desk_program.py"
    spec = importlib.util.spec_from_file_location("s10_cli_desk_program", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.program_config(head)


def test_a_registered_program_status_carries_the_wall_clock_the_compare_family_does_not_record(service):
    """The `status` case of the family is dropped (its `registered_at` and `updated_at` would need a new mask)."""
    config = validate_config(program_document("b" * 40), cli_research_program.packaged_policy())
    programs = cli_research_program.research_program(service.store)
    assert programs.register(config, "d" * 64, [])["cached"] is False
    assert programs.register(config, "d" * 64, [])["cached"] is True
    result = research_program._execute(service, SimpleNamespace(research_program_command="status", program_id="rp-001"))
    assert result["exit_code"] == 0 and result["state"] == "paused" and result["registered_at"] and result["updated_at"]
    for command, state in (("resume", "active"), ("pause", "paused")):
        moved = research_program._execute(service, SimpleNamespace(research_program_command=command, program_id="rp-001"))
        assert moved["state"] == state and moved["exit_code"] == 0


def test_transport_probe_scopes_a_named_run_and_never_connects(monkeypatch, settings):
    monkeypatch.setattr(composition, "redis_url", lambda: "redis://127.0.0.1:1/0")
    assert cli_research_program.transport_probe(None).scoped is None
    assert cli_research_program.transport_probe("").scoped is None
    scoped = cli_research_program.transport_probe("run-1").scoped
    assert scoped is not None and scoped is not cli_research_program.transport_probe("run-1").bus


# ----- dispatch ---------------------------------------------------------------------------------------
def test_the_dispatch_table_composes_both_roots(monkeypatch):
    tree = ast.parse(Path(entry.__file__).resolve().read_text(encoding="utf-8"))
    tables = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    keys = [key.value for key in tables[0].value.keys]
    assert "desk" in keys and "research-program" in keys
    called = []
    monkeypatch.setattr(desk, "run", lambda args: called.append(args.command))
    monkeypatch.setattr(research_program, "run", lambda args: called.append(args.command))
    for argv in (["desk", "status", "--revision", REVISION], ["research-program", "status", "rp"]):
        monkeypatch.setattr(sys, "argv", ["zeus", *argv])
        entry.main()
    assert called == ["desk", "research-program"]
