import sys
from types import SimpleNamespace

import pytest

from codex_harness import supervisor
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization


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
        supervisor.main()
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
    supervisor.main()
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
    monkeypatch.setattr(supervisor, "RedisBus", lambda *a: bus)
    monkeypatch.setattr(supervisor, "run_process", run)
    monkeypatch.setattr(supervisor, "source_thread", SimpleNamespace(is_alive=lambda: True))
    monkeypatch.setattr(supervisor, "maintenance_thread", None, raising=False)
    monkeypatch.setattr(supervisor.threading, "Thread", InlineThread)
    monkeypatch.setattr(supervisor, "last_maintenance", float('-inf'))
    monkeypatch.setattr(supervisor, "last_collection", float('inf'))
    monkeypatch.setattr(supervisor, "ReleaseRunner", lambda *a: SimpleNamespace(
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

    def runner(*args, fence):
        def run(release_id):
            fence()
            calls.append(release_id)
            if len(calls) == 1:
                raise TimeoutError("fixture temporary failure")
            return {"status": "active"}
        return SimpleNamespace(run=run)

    monkeypatch.setattr(supervisor, "ReleaseRunner", runner)
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
