"""S10 C5f: the `rlm` root over the composed executor (DESIGN-s10 §11, R-c23).

MemoryStore, a monkeypatched `configuration.settings`; no provider: the App Server is a fake context manager whose `run` records its
calls. Not a parity family: `rlm` calls a provider (R-c10)."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import configuration, isolation, operation
from codex_harness.entry import cli
from codex_harness.execution.adapters.providers.native_hooks import HostHooks
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.routing.domain.model_selection import select_model
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

IMAGE = "sha256:" + "a" * 64


class FakeAppServer:
    """Stands in for the codex AppServer; `instances` shows what was constructed and `calls` what ran."""

    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs, self.calls, self.entered, self.exited = kwargs, [], False, False
        FakeAppServer.instances.append(self)

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.exited = True
        return False

    def run(self, prompt, cwd, schema, model=None):
        self.calls.append({"prompt": prompt, "cwd": cwd, "schema": schema, "model": model})
        return {"answer": {"finding": "fake finding", "sufficient": True}}


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime"), "HARNESS_DATABASE_URL": "postgresql://unused/none"}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    handle = composition.ServiceHandle(MemoryStore(), packaged_organization())
    monkeypatch.setattr(composition, "build", lambda: handle)
    monkeypatch.setattr(operation, "host_evidence_profile", lambda: None)
    FakeAppServer.instances = []
    monkeypatch.setattr(operation, "_host_app_server", FakeAppServer)
    return values


def run_main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["zeus", "rlm", *argv])
    try:
        cli.main()
        code = 0
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_the_dispatch_table_composes_rlm():
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    tables = [{k.value for k in node.keys if isinstance(k, ast.Constant)}
              for node in ast.walk(tree) if isinstance(node, ast.Dict)]
    assert any("rlm" in table for table in tables)


def test_development_runs_the_recursive_context_over_the_factory_app_server(settings, monkeypatch, capsys, tmp_path):
    settings["ZEUS_COMPOSITION_PROFILE"] = "development"
    sentinel = {"PreToolUse": [{"matcher": "marker", "hooks": []}]}
    monkeypatch.setattr(HostHooks, "configuration", lambda self: sentinel)
    receipt = FileArtifacts(str(tmp_path / "runtime" / "artifacts")).put("some external evidence", "test")
    code, out, err = run_main(monkeypatch, capsys, receipt["ref"], "what is it?", "--max-calls", "3")
    assert code == 0, err
    (server,) = FakeAppServer.instances
    assert server.entered and server.exited
    # R-c23: the App Server got the host hook configuration the executor's own transports use.
    assert server.kwargs == {"hooks": sentinel}
    (call,) = server.calls
    assert call["model"] == select_model("design").requested_model
    assert call["cwd"] == str(tmp_path)
    assert json.loads(call["prompt"])["task"] == "what is it?"
    result = json.loads(out)
    assert result["source"] == receipt["ref"] and result["answer"] == {"finding": "fake finding", "sufficient": True}
    assert result["depth"] == 0 and result["children"] == []


def test_max_calls_comes_from_the_arguments(settings, monkeypatch, capsys, tmp_path):
    settings["ZEUS_COMPOSITION_PROFILE"] = "development"
    receipt = FileArtifacts(str(tmp_path / "runtime" / "artifacts")).put("x" * 7000, "test")
    code, out, err = run_main(monkeypatch, capsys, receipt["ref"], "q", "--max-calls", "1")
    assert code == 1 and json.loads(err) == {"error": "RLM call budget insufficient"}
    assert out == "" and FakeAppServer.instances[0].calls == []


def test_production_refuses_before_any_app_server_exists(settings, monkeypatch, capsys, tmp_path):
    stand_in = SimpleNamespace(config={"image": IMAGE}, root=tmp_path / "isolated", docker=None,
                               summary=lambda *a, **k: None, review_context=lambda *a, **k: None)
    settings.update({"ZEUS_COMPOSITION_PROFILE": "production", "ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    monkeypatch.setattr(isolation, "isolated_worker", lambda config: stand_in)
    code, out, err = run_main(monkeypatch, capsys, "ref", "q")
    assert code == 1 and out == ""
    assert json.loads(err) == {"error": "isolated worker: host_transport_refused_in_production"}
    assert FakeAppServer.instances == []


def test_an_absent_profile_is_refused(settings, monkeypatch, capsys):
    code, out, err = run_main(monkeypatch, capsys, "ref", "q")
    assert code == 1 and out == "" and json.loads(err) == {"error": "composition_profile_unknown"}
    assert FakeAppServer.instances == []
