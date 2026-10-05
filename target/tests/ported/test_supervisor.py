# Ported from SOURCE M7 tests/test_supervisor.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
import sys
from types import SimpleNamespace

import pytest

from m7_coordination import Harness, organization

from codex_harness.composition import supervisor
from codex_harness.entry.processes import supervisor as supervisor_entry
from codex_harness.storage.adapters.memory_store import MemoryStore


def test_once_reports_failure_to_scheduler_and_resolves_runtime(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HARNESS_REPOSITORY", str(tmp_path))
    monkeypatch.setenv("HARNESS_RUNTIME_DIR", "state")
    monkeypatch.setattr(sys, "argv", ["harness-supervisor", "--once"])
    monkeypatch.setattr(supervisor, "release_thread", None)
    monkeypatch.setattr(supervisor, "source_thread", None)

    def failed(*args):
        raise RuntimeError("fixture unavailable service")

    monkeypatch.setattr(supervisor, "tick", failed)
    with pytest.raises(SystemExit) as error:
        supervisor_entry.main()  # S11 M B5: M7 supervisor.main(); the argument shape is entry.processes.supervisor, the loop composition.supervisor.run
    assert error.value.code == 1
    assert "fixture unavailable service" in capsys.readouterr().out
    assert (tmp_path / "state").is_dir()


def test_once_success_is_distinct_from_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_REPOSITORY", str(tmp_path))
    monkeypatch.delenv("HARNESS_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(sys, "argv", ["harness-supervisor", "--once"])
    monkeypatch.setattr(supervisor, "release_thread", None)
    monkeypatch.setattr(supervisor, "source_thread", None)
    calls = []
    monkeypatch.setattr(supervisor, "tick", lambda *args: calls.append(args[:2]))
    supervisor_entry.main()  # S11 M B5: M7 supervisor.main()
    assert calls == [(False, False)]


def test_embedding_failure_and_recovery_remain_visible(tmp_path):
    service = SimpleNamespace(store=MemoryStore())

    def failed(*args, **kwargs):
        raise ConnectionError("fixture model download failed")

    executor = SimpleNamespace(knowledge=SimpleNamespace(embed_missing=failed))
    supervisor.refresh_embeddings(service, executor, tmp_path)
    with service.store.transaction() as tx:
        assert tx.get("health", "embeddings")["status"] == "failed"
    executor.knowledge.embed_missing = lambda *args, **kwargs: None
    supervisor.refresh_embeddings(service, executor, tmp_path)
    with service.store.transaction() as tx:
        result = tx.get("health", "embeddings")
        assert result["status"] == "healthy" and "error_type" not in result


def test_broken_graph_index_does_not_prevent_queued_agent_from_waking(tmp_path, monkeypatch):
    service = Harness(MemoryStore(), organization())
    with service.store.transaction() as tx:
        tx.put("tasks", "queued", {"id": "queued", "agent": "worker:implementation",
                                  "status": "queued"})
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stderr="", stdout=(
            '{"Service":"postgres","State":"running"}\n'
            '{"Service":"redis","State":"running"}\n'))

    def broken(*args):
        raise ValueError("fixture corrupt source index")

    executor = SimpleNamespace(git=SimpleNamespace(_git=lambda *a: "revision"),
                               knowledge=SimpleNamespace(index_python=broken,
                                   project_runtime=lambda *a: None, embed_missing=lambda *a, **k: None),
                               artifacts=SimpleNamespace())
    bus = SimpleNamespace(client=SimpleNamespace(exists=lambda *a: False, xlen=lambda *a: 0),
                          stream=lambda agent: agent, compact=lambda *a: 0)

    class InlineThread:
        def __init__(self, target, args, **kwargs): self.target, self.args = target, args
        def start(self): self.target(*self.args)
        def is_alive(self): return False

    monkeypatch.setenv("HARNESS_REPOSITORY", str(tmp_path))
    monkeypatch.setattr(supervisor, "build", lambda: service)
    monkeypatch.setattr(supervisor, "build_executor", lambda *a: executor)
    monkeypatch.setattr(supervisor.cli_bus, "bus", lambda: bus)  # S11 M B5: M7 RedisBus(url) is composition.cli_bus.bus()
    monkeypatch.setattr(supervisor, "run_process", run)
    monkeypatch.setattr(supervisor, "source_thread", SimpleNamespace(is_alive=lambda: True))
    monkeypatch.setattr(supervisor, "maintenance_thread", None, raising=False)
    monkeypatch.setattr(supervisor.threading, "Thread", InlineThread)
    monkeypatch.setattr(supervisor, "last_maintenance", float('-inf'))
    monkeypatch.setattr(supervisor, "last_collection", float('inf'))
    # S11 M B5: M7 ReleaseRunner(...) is composition.cli_executor.release_runner(service, executor)
    monkeypatch.setattr(supervisor.cli_executor, "release_runner", lambda *a: SimpleNamespace(
        monitor=lambda: {"status": "no_deployment"}))
    supervisor.tick()
    assert any("up" in argv and argv[-1] == "implementation-worker" for argv in calls)
    with service.store.transaction() as tx:
        assert tx.get("health", "graph-index")["status"] == "failed"


def test_transient_release_failure_retries_without_losing_queue_metadata(monkeypatch):
    service = Harness(MemoryStore(), organization())
    with service.store.transaction() as tx:
        tx.put("release_queue", "release", {"id": "release", "status": "queued", "metadata": "keep"})
    calls = []

    # S11 M B5: M7 passed `fence` to ReleaseRunner(...); composition.cli_executor.release_runner(service, executor) returns the
    # runner and composition.supervisor.deploy_queued sets `runner.fence` on it (read at call time), so the double reads it there.
    def runner(*args):
        box = SimpleNamespace()

        def run(release_id):
            box.fence()
            calls.append(release_id)
            if len(calls) == 1:
                raise TimeoutError("fixture temporary failure")
            return {"status": "active"}
        box.run = run
        return box

    monkeypatch.setattr(supervisor.cli_executor, "release_runner", runner)
    executor = SimpleNamespace(git=None, artifacts=None)
    supervisor.deploy_queued(service, executor)
    supervisor.deploy_queued(service, executor)
    assert len(calls) == 1
    with service.store.transaction() as tx:
        row = tx.get("release_queue", "release")
        assert row["status"] == "retry"
        row["retry_at"] = "2000-01-01T00:00:00+00:00"
        tx.put("release_queue", "release", row)
    supervisor.deploy_queued(service, executor)
    with service.store.transaction() as tx:
        row = tx.get("release_queue", "release")
        assert row["status"] == "active" and row["metadata"] == "keep"
        assert row["attempt"] == len(row["attempts"]) == len(calls) == 2
