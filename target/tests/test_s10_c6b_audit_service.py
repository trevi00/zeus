"""S10 C6b: the `audit-service` root under R-c25 (DESIGN-s10 §3 C6).

Parity with M7 is the `entry.cli_audit_service.pg` compare family; these tests cover what it cannot with a MemoryStore and monkeypatched
settings: the composition's wiring (`build_runner` injects the research scheduler V-c25, the repair owner, the executor with its default
knowledge, the collector and the observer), the runner's required `schedule`, the host lock and the dispatch. No provider is entered."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from filelock import FileLock

from codex_harness import composition
from codex_harness.composition import (
    audit_repair,
    cli_audit_service,
    cli_bus,
    configuration,
    observation,
    operation,
)
from codex_harness.coordination.application import audit_service
from codex_harness.entry import cli
from codex_harness.research.application.audit_progress import AuditProgress
from codex_harness.research.application.scheduling import schedule_audits
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime"), "HARNESS_DATABASE_URL": "postgresql://unused/none"}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(cli_audit_service, "current_revision", lambda: "rev-1", raising=True)
    return values


@pytest.fixture
def service(monkeypatch):
    handle = composition.ServiceHandle(MemoryStore(), packaged_organization())
    monkeypatch.setattr(composition, "build", lambda: handle)
    return handle


def test_build_runner_injects_the_scheduler_repair_executor_collector_and_observer(settings, service, monkeypatch):
    seen = {}
    executor, collector, repair, bus = object(), object(), object(), object()

    def build_executor(*args, **kwargs):
        seen["executor"] = (args, kwargs)
        return executor

    monkeypatch.setattr(operation, "build_executor", build_executor)
    monkeypatch.setattr(observation, "build_collector", lambda store, observer=None: seen.setdefault("collector", (store, observer)) and collector)
    monkeypatch.setattr(audit_repair, "build_repair", lambda svc, artifacts=None, **kw: seen.setdefault("repair", (svc, artifacts)) and repair)
    monkeypatch.setattr(cli_bus, "bus", lambda: bus)
    observer = object()
    args = SimpleNamespace(audit_id="a", max_tasks=3, once=True)
    runner = cli_audit_service.build_runner(service, args, observer,
                                            {"revision": "rev-1", "release_id": "rel-1", "partitions": 2})
    assert runner.schedule is schedule_audits                      # V-c25: composition injects the research scheduler
    assert runner.executor is executor and runner.bus is bus and runner.repair is repair
    assert runner.collector is collector and runner.observer is observer
    assert seen["executor"] == ((service,), {"observer": observer})  # the default executor: knowledge stays on
    assert seen["collector"] == (service.store, observer)
    assert seen["repair"][0] is service and seen["repair"][1] is not None
    assert isinstance(runner.progress, AuditProgress) and runner.progress.investigations is not None
    assert (runner.audit_id, runner.max_tasks, runner.revision, runner.release_id, runner.partitions) == ("a", 3, "rev-1", "rel-1", 2)


def test_the_runner_without_a_schedule_is_a_type_error(service):
    with pytest.raises(TypeError, match="schedule"):
        audit_service.AuditServiceRunner(service, "a")
    assert audit_service.AuditServiceRunner(service, "a", schedule=schedule_audits).schedule is schedule_audits


def test_the_runner_still_refuses_a_bad_audit_id_and_max_tasks(service):
    with pytest.raises(audit_service.AuditServiceRefused) as bad_id:
        audit_service.AuditServiceRunner(service, " ", schedule=schedule_audits)
    assert bad_id.value.reason_code == "audit_id_invalid"
    with pytest.raises(audit_service.AuditServiceRefused) as bad_max:
        audit_service.AuditServiceRunner(service, "a", max_tasks=0, schedule=schedule_audits)
    assert bad_max.value.reason_code == "max_tasks_invalid"


def test_a_held_lock_refuses_with_audit_service_lock_busy(settings, service, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    args = SimpleNamespace(audit_id="a", max_tasks=None, once=True)
    with FileLock(str(runtime / "audit-service.lock"), timeout=0):
        result = cli_audit_service.run_service(service, args)
    assert result == {"status": "refused", "reason_code": "audit_service_lock_busy", "exit_code": 1}


def test_the_lock_is_released_after_a_gate_refusal_before_any_observer(settings, service, tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("an observer or executor was built before the gate")

    monkeypatch.setattr(observation, "build_observer", forbidden)
    monkeypatch.setattr(operation, "build_executor", forbidden)
    args = SimpleNamespace(audit_id="a", max_tasks=None, once=True)
    with pytest.raises(audit_service.AuditServiceRefused) as refused:
        cli_audit_service.run_service(service, args)
    assert refused.value.reason_code == "activation_inactive"
    lock = FileLock(str(tmp_path / "runtime" / "audit-service.lock"), timeout=0)
    lock.acquire()                                                  # free again: the refusal released it
    lock.release()


def test_the_dispatch_table_composes_audit_service():
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    tables = [{k.value for k in node.keys if isinstance(k, ast.Constant)}
              for node in ast.walk(tree) if isinstance(node, ast.Dict)]
    assert any("audit-service" in table for table in tables)


def run_main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["zeus", "audit-service", *argv])
    try:
        cli.main()
        code = 0
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_main_status_of_an_unknown_audit_is_a_read_only_view(settings, service, monkeypatch, capsys):
    code, out, err = run_main(monkeypatch, capsys, "status", "--audit-id", "nope")
    assert code == 0, err
    view = json.loads(out)
    assert view["known_audit"] is False and view["audit_id"] == "nope" and view["exit_code"] == 0


def test_main_run_of_an_unknown_audit_prints_the_gate_refusal_and_exits_1(settings, service, monkeypatch, capsys):
    code, out, _err = run_main(monkeypatch, capsys, "run", "--audit-id", "nope", "--once")
    assert code == 1
    assert json.loads(out) == {"status": "refused", "reason_code": "activation_inactive",
                               "error_type": "AuditServiceRefused", "exit_code": 1}
