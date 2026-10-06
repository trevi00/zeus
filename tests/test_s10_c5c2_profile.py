"""S10 C5c-2: the composition profile (OWNER-DECISIONS-S10 #10; REBUILD-DESIGN-v2 section 4 row 8).

MemoryStore, a monkeypatched `configuration.settings`; no provider and no Docker is touched."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import configuration, isolation, operation
from codex_harness.kernel.errors import ContractError, IsolationError
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters import file_artifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

IMAGE = "sha256:" + "a" * 64


def _stand_in(root):
    return SimpleNamespace(config={"image": IMAGE}, root=root, docker=None, summary=lambda *a, **k: None,
                           review_context=lambda *a, **k: None)


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime")}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    handle = composition.ServiceHandle(MemoryStore(), packaged_organization())
    monkeypatch.setattr(composition, "build", lambda: handle)
    return values


@pytest.fixture
def built(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("FileArtifacts must not be built")

    monkeypatch.setattr(file_artifacts, "FileArtifacts", forbidden)
    return calls


def _build(**kwargs):
    return operation.build_executor(knowledge=False, evidence_profile=None, **kwargs)


@pytest.mark.parametrize("value", [None, "", "staging", "Production"])
def test_an_absent_empty_or_unknown_profile_is_refused_before_anything_is_built(settings, built, tmp_path, value):
    if value is not None:
        settings["ZEUS_COMPOSITION_PROFILE"] = value
    with pytest.raises(ContractError, match="composition_profile_unknown"):
        _build()
    with pytest.raises(ContractError, match="composition_profile_unknown"):
        _build(profile="staging")
    assert built == [] and not (tmp_path / "runtime").exists()


def test_production_without_isolation_is_refused_and_builds_nothing(settings, built, tmp_path):
    settings["ZEUS_COMPOSITION_PROFILE"] = "production"
    with pytest.raises(IsolationError, match="production_requires_isolation"):
        _build()
    assert built == [] and not (tmp_path / "runtime").exists()


def test_production_with_isolation_constructs_no_host_transport(settings, monkeypatch, tmp_path):
    stand_in = _stand_in(tmp_path / "isolated")
    settings.update({"ZEUS_COMPOSITION_PROFILE": "production", "ZEUS_WORKER_ISOLATION": "docker",
                     "ZEUS_WORKER_IMAGE": IMAGE})
    monkeypatch.setattr(isolation, "isolated_worker", lambda config: stand_in)
    executor = _build()
    assert executor.isolation is stand_in
    transports = executor.run_task.transports
    for factory in (transports.host_app_server, transports.claude_runtime):
        with pytest.raises(IsolationError, match="host_transport_refused_in_production"):
            factory()
    with pytest.raises(IsolationError, match="host_transport_refused_in_production"):
        transports.host_app_server(model="m")


def test_development_without_isolation_keeps_the_real_transport_factories(settings):
    settings["ZEUS_COMPOSITION_PROFILE"] = "development"
    transports = _build().run_task.transports
    assert transports.host_app_server is operation._host_app_server
    assert transports.claude_runtime is operation._host_claude_runtime


def test_the_profile_argument_overrides_the_setting(settings):
    settings["ZEUS_COMPOSITION_PROFILE"] = "production"
    transports = _build(profile="development").run_task.transports
    assert transports.host_app_server is operation._host_app_server
    del settings["ZEUS_COMPOSITION_PROFILE"]
    with pytest.raises(IsolationError, match="production_requires_isolation"):
        _build(profile="production")


def test_host_isolation_composes_the_isolated_worker_once(settings, monkeypatch, tmp_path):
    stand_in = _stand_in(tmp_path)
    settings.update({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    seen = []
    monkeypatch.setattr(isolation, "isolated_worker", lambda config: seen.append(config) or stand_in)
    assert operation.host_isolation(None) is stand_in
    assert len(seen) == 1 and seen[0]["image"] == IMAGE


def test_composition_profile_reads_the_alias_through_settings():
    assert operation.COMPOSITION_PROFILES == ("development", "production")
    assert operation.composition_profile({"ZEUS_COMPOSITION_PROFILE": "production"}) == "production"
    with pytest.raises(ContractError, match="composition_profile_unknown"):
        operation.composition_profile({})
