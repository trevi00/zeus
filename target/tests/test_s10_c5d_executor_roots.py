"""S10 C5d: the seven executor roots and the `composition.cli_executor` builders (R-c21, E-c21).

MemoryStore, a monkeypatched `configuration.settings`; no provider, Docker, Redis or PostgreSQL is touched."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import cli_executor, configuration, operation
from codex_harness.entry import cli as entry
from codex_harness.entry.cli import artifact, cleanup, execute_one, improve, rebase, release_abandon, research
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

ROOTS = {"execute-one": (execute_one, ["--agent", "worker:implementation"]), "artifact": (artifact, ["ref"]),
         "cleanup": (cleanup, []), "release-abandon": (release_abandon, ["rel", "--reason", "r"]),
         "rebase": (rebase, ["task"]), "research": (research, ["github", "--intent", "proactive"]),
         "improve": (improve, ["objective", "--acceptance", "a"])}


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime")}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    handle = composition.ServiceHandle(MemoryStore(), packaged_organization())
    monkeypatch.setattr(composition, "build", lambda: handle)
    return values


def _main(monkeypatch, command, argv):
    monkeypatch.setattr(sys, "argv", ["zeus", command, *argv])
    entry.main()


@pytest.mark.parametrize("command", sorted(ROOTS))
def test_an_absent_profile_refuses_every_executor_root(settings, monkeypatch, capsys, command):
    # E-c21: the target-only behaviour (M7 had no profile); OWNER-DECISIONS-S10 #10.
    with pytest.raises(SystemExit) as raised:
        _main(monkeypatch, command, ROOTS[command][1])
    assert raised.value.code == 1
    assert json.loads(capsys.readouterr().err) == {"error": "composition_profile_unknown"}


@pytest.mark.parametrize("command", sorted(ROOTS))
def test_the_dispatch_table_composes_each_executor_root(monkeypatch, command):
    called = []
    monkeypatch.setattr(ROOTS[command][0], "run", lambda args: called.append(args.command))
    _main(monkeypatch, command, ROOTS[command][1])
    assert called == [command]


def test_executor_is_build_executor_with_the_observer(monkeypatch):
    seen = []
    monkeypatch.setattr(operation, "build_executor", lambda service, **kwargs: seen.append((service, kwargs)) or "built")
    assert cli_executor.executor("service", observer="observer") == "built"
    assert cli_executor.executor("service") == "built"
    assert seen == [("service", {"observer": "observer"}), ("service", {"observer": None})]


def test_release_runner_wires_the_production_carries(settings, tmp_path):
    from codex_harness.coordination.application.messages import MessageHandler
    from codex_harness.delivery.adapters.deployment import ReleaseRunner
    from codex_harness.execution.adapters.providers.native_hooks import HookCandidates
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.host_os.adapters.verification import VerificationServices
    from codex_harness.review.adapters.release_suite import ReleaseSuite

    service = composition.build()
    git = SimpleNamespace(_git=lambda *args, **kwargs: "shown")
    artifacts = SimpleNamespace(root=str(tmp_path))
    runner = cli_executor.release_runner(service, SimpleNamespace(git=git, artifacts=artifacts))
    assert isinstance(runner, ReleaseRunner) and runner.git is git and runner.artifacts is artifacts
    assert runner.service is service and runner.auth == configuration.codex_auth().resolve()
    assert runner.runner is process_groups.run_process and runner.verification_services is VerificationServices
    assert isinstance(runner.request_rebase.__self__, MessageHandler)
    assert runner.request_rebase.__func__ is MessageHandler.request_rebase
    assert isinstance(runner.release_suite(artifacts, runner.fence), ReleaseSuite)
    hooks = runner.hooks(service, git, artifacts)
    assert isinstance(hooks, HookCandidates) and hooks.store is service.store and hooks.show("rev:path") == "shown"


def test_release_abandon_refuses_an_unknown_release_through_the_composed_runner(settings, monkeypatch, capsys, tmp_path):
    git = SimpleNamespace(_git=lambda *args, **kwargs: "")
    monkeypatch.setattr(cli_executor, "executor", lambda service, observer=None: SimpleNamespace(
        git=git, artifacts=SimpleNamespace(root=str(tmp_path))))
    with pytest.raises(SystemExit):
        _main(monkeypatch, "release-abandon", ["rel", "--reason", "r"])
    assert json.loads(capsys.readouterr().err) == {"error": "No prepared promotion to abandon"}


def test_artifact_maintenance_is_the_storage_collector_over_the_artifacts(settings, tmp_path):
    from codex_harness.coordination.application.events import EventJournal
    from codex_harness.kernel.ids import SYSTEM_CLOCK
    from codex_harness.storage.adapters.maintenance import ArtifactMaintenance

    service, artifacts = composition.build(), SimpleNamespace(root=str(tmp_path))
    maintenance = cli_executor.artifact_maintenance(service, artifacts)
    assert isinstance(maintenance, ArtifactMaintenance)
    assert maintenance.store is service.store and maintenance.artifacts is artifacts
    assert isinstance(maintenance.events, EventJournal) and maintenance.clock is SYSTEM_CLOCK


def test_rebase_asks_the_message_handler_that_took_over_request_rebase(settings, monkeypatch, capsys):
    from codex_harness.coordination.application.messages import MessageHandler

    asked = []
    git = SimpleNamespace(_git=lambda *args, **kwargs: "a" * 40)
    monkeypatch.setattr(cli_executor, "executor", lambda service, observer=None: SimpleNamespace(git=git))
    monkeypatch.setattr(MessageHandler, "request_rebase", lambda self, task, base: asked.append((task, base)) or {"ok": 1})
    flushed = []
    monkeypatch.setattr(composition.cli_bus, "flusher", lambda service: SimpleNamespace(flush=lambda bus, **k: flushed.append(k)))
    monkeypatch.setattr(composition.cli_bus, "bus", lambda: "bus")
    _main(monkeypatch, "rebase", ["task", "--onto", "main"])
    assert asked == [("task", "a" * 40)] and flushed == [{}]
    assert json.loads(capsys.readouterr().out) == {"ok": 1}
