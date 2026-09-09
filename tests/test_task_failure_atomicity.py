from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.store import MemoryStore, MemoryTransaction, PostgresTransaction
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import envelope


@pytest.mark.parametrize("backend", ["memory", pytest.param("postgres", marks=pytest.mark.integration)])
@pytest.mark.parametrize("failure", ["current", "expired", "replaced", "completed", "commit_failed"])
def test_task_failure_and_diagnosis_share_current_lease(tmp_path, monkeypatch, request, backend, failure):
    store = MemoryStore() if backend == "memory" else request.getfixturevalue("isolated_pgstore")
    service = Harness(store, organization())
    executor = Executor(service, SimpleNamespace(repository=tmp_path), FileArtifacts(tmp_path / "artifacts"),
                        research=SimpleNamespace(collect=lambda *a: {"items": []}))
    message = envelope("task.assign", "lead:research", "worker:github", "research", {}, "fixture")
    executor.workflow.submit(message)

    def fail(*args, **kwargs):
        with store.transaction() as tx:
            task = tx.get("tasks", message["message_id"])
            if failure == "expired":
                task["lease_until"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            elif failure == "replaced":
                task.update(lease_owner="replacement", generation=task["generation"] + 1)
            tx.put("tasks", task["id"], task)
        if failure == "completed":
            executor.workflow.complete(task, {"summary": "already committed"})
        raise RuntimeError("fixture task failure")

    monkeypatch.setattr(executor, "_run", fail)
    transaction_type = MemoryTransaction if backend == "memory" else PostgresTransaction
    put = transaction_type.put

    def interrupted(tx, bucket, key, body):
        put(tx, bucket, key, body)
        if failure == "commit_failed" and bucket == "decisions_pending":
            raise OSError("fixture interrupted diagnosis commit")

    monkeypatch.setattr(transaction_type, "put", interrupted)
    if failure == "commit_failed":
        with pytest.raises(OSError):
            executor.execute_one("worker:github")
    else:
        result = executor.execute_one("worker:github")
        assert result["status"] == ("retry" if failure == "current" else
                                    "succeeded" if failure == "completed" else "stale")
    with store.transaction() as tx:
        task = tx.get("tasks", message["message_id"])
        diagnoses = tx.scan("decisions_pending")
        if failure == "current":
            assert len(diagnoses) == len(task["attempt_outcomes"]) == 1
            assert diagnoses[0]["input"]["source_task_id"] == task["id"]
        else:
            assert not diagnoses
        if failure == "replaced":
            assert task["lease_owner"] == "replacement" and task["generation"] == 2
        if failure == "commit_failed":
            assert task["status"] == "running" and not task.get("attempt_outcomes")
