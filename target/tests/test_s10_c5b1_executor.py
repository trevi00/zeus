"""S10 C5b-1: `composition.operation`, the production Executor and `build_executor` (OWNER-DECISIONS-S10 #2, #7, #8, #17, #18).

No provider is called (the root conftest's provider guard stays on): the transports are stubbed at their factory seams, the
store is a MemoryStore, and the host settings are a monkeypatched `composition.configuration.settings`."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import configuration, operation
from codex_harness.composition.evidence_gate import EvidenceGate
from codex_harness.composition.hook_units import HookUnits
from codex_harness.composition.invocation_budget import CapacityObservingLedger
from codex_harness.coordination.application import operation_finalization as operation_finalization_ref
from codex_harness.coordination.application.continuation.bindings import ContinuationBindings
from codex_harness.evidence.adapters.evidence_inspection import EvidenceInspector
from codex_harness.execution.adapters.providers import codex_app_server
from codex_harness.execution.adapters.providers.claude_cli import ClaudeHost
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses
from codex_harness.kernel.errors import IsolationError
from codex_harness.kernel.message import envelope
from codex_harness.observation.application.catalog_observer import CatalogCheckingObserver
from codex_harness.observation.domain.observation import redact_text
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

IMAGE = "sha256:" + "a" * 64
SRC = Path(operation.__file__)


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime")}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    return values


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _executor(tmp_path, **kwargs):
    service = composition.ServiceHandle(MemoryStore(), packaged_organization())
    git = SimpleNamespace(_git=lambda *a, **k: "revision", repository=tmp_path)
    return operation.Executor(service, git, FileArtifacts(str(tmp_path / "artifacts")), knowledge=None, **kwargs)


def test_the_wiring_table(tmp_path, settings):
    executor = _executor(tmp_path)
    task = executor.run_task
    assert isinstance(executor.observer, CatalogCheckingObserver)
    assert isinstance(task.invocations, CapacityObservingLedger)
    assert executor.workflow.park_terminal is operation_finalization_ref.park
    assert task.evidence_gate is executor.evidence_gate and isinstance(executor.evidence_gate, EvidenceGate)
    assert isinstance(executor.evidence_gate.evidence.inspector, EvidenceInspector)
    assert isinstance(task.continuations, ContinuationBindings)
    assert isinstance(task.hook_candidates.lifecycle, HookUnits)
    assert task.host_python == sys.executable
    for name in ("audit_execution", "roles", "council", "feedback", "composition_admission", "research_admission"):
        assert getattr(task, name) is None, name
    assert executor.decisions is not None and executor.service.store is task.store


def test_the_transport_factories_carry_the_real_host_facilities(tmp_path, settings, monkeypatch):
    transports = _executor(tmp_path).run_task.transports
    seen = {}
    monkeypatch.setattr(codex_app_server, "AppServer", lambda **kw: seen.update(kw) or "app-server")
    assert transports.host_app_server(model="m") == "app-server"
    assert isinstance(seen["processes"], ChokepointProcesses) and seen["model"] == "m"
    from codex_harness.execution.adapters.providers import claude_cli
    captured = {}
    monkeypatch.setattr(claude_cli, "ClaudeCodeRuntime", lambda **kw: captured.update(kw) or "claude")
    assert transports.claude_runtime(model="m") == "claude"
    assert isinstance(captured["host"], ClaudeHost) and captured["host"].redact is redact_text


def test_host_isolation_refuses_a_configured_selection_until_c5c(settings):
    settings.update({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    with pytest.raises(IsolationError, match="S10 unit C5c"):
        operation.host_isolation(None)
    with pytest.raises(IsolationError, match="S10 unit C5c"):
        operation.build_executor(service=object(), observer=object(), knowledge=False, evidence_profile=None)


def test_host_isolation_keeps_the_m7_refusals_and_none_when_unconfigured(settings):
    assert operation.host_isolation(None) is None
    from codex_harness.evidence.domain import project_evidence as domain
    container = {"schema": domain.SCHEMA_V2, "execution": {"kind": "container", "image": IMAGE}}
    assert domain.requires_container(container)
    with pytest.raises(IsolationError, match="project_evidence_profile_requires_isolation"):
        operation.host_isolation(container)
    settings.update({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    with pytest.raises(IsolationError, match="isolation_refuses_project_evidence_profile"):
        operation.host_isolation({"schema": "host"})
    other = {**container, "execution": {"kind": "container", "image": "sha256:" + "b" * 64}}
    with pytest.raises(IsolationError, match="project_evidence_image_mismatch"):
        operation.host_isolation(other)


def test_decide_one_on_an_empty_queue_is_none(tmp_path, settings):
    assert _executor(tmp_path).decide_one("lead:reviewer") is None


def test_build_executor_takes_its_observer_from_build_observer(tmp_path, settings, monkeypatch):
    handle = composition.ServiceHandle(MemoryStore(), packaged_organization())
    monkeypatch.setattr(composition, "build", lambda: handle)
    executor = operation.build_executor(knowledge=False)
    assert executor.service is handle and isinstance(executor.observer, CatalogCheckingObserver)
    assert executor.run_task is not None and executor.decisions is not None and executor.knowledge is None
    assert executor.run_task.audit_execution is None and executor.research.pressure is not None


def test_an_implementation_runs_end_to_end_through_the_real_evidence_gate(tmp_path, settings, monkeypatch):
    root = tmp_path / "repository"
    root.mkdir()
    for args in (("init", "-b", "main"), ("config", "user.name", "Fixture"), ("config", "user.email", "f@localhost")):
        _git(root, *args)
    (root / "original.txt").write_text("original", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "Initial fixture")
    from codex_harness.host_os.adapters.git_workspace import GitWorkspace
    git = GitWorkspace(str(root), str(tmp_path / "workspaces"))
    service = composition.ServiceHandle(MemoryStore(), packaged_organization())
    executor = operation.Executor(service, git, FileArtifacts(str(tmp_path / "artifacts")))

    class Runtime:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def run(self, prompt, cwd, schema, timeout, **kwargs):
            Path(cwd, "change.txt").write_text("implemented", encoding="utf-8")
            return {"answer": {"summary": "fixture implementation", "tests": []}, "events": [], "thread_id": "thread",
                    "turn_id": "turn", "usage": None, "rotate": False, "interrupted": False,
                    "requested_model": kwargs.get("model")}

    monkeypatch.setattr(codex_app_server, "AppServer", lambda **kw: Runtime())
    parent = packaged_organization().actor("worker:implementation").parent
    message = envelope("task.assign", parent, "worker:implementation", "implement",
                       {"plan": {"objective": "fixture", "acceptance_criteria": ["x"], "allowed_paths": ["change.txt"]}},
                       "fixture", None)
    message["where"]["revision"] = git._git("rev-parse", "HEAD")
    executor.workflow.submit(message)
    row = executor.execute_one("worker:implementation")
    assert row["status"] == "succeeded", row.get("error")
    inspection = row["result"]["evidence_inspection"]
    assert inspection["inspection_id"] and inspection["verdict"]


def test_operation_imports_nothing_from_tests():
    tree = ast.parse(SRC.read_text("utf-8"))
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
    modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not [name for name in modules if name.split(".")[0] in {"tests", "conftest", "m7_executor"}]
