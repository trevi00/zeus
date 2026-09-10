from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.store import MemoryStore, MemoryTransaction, PostgresTransaction
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import envelope


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_decision_retry_does_not_replenish_durable_time_budget(tmp_path, monkeypatch, backend, request):
    # Execution failure input fixture; this does not claim a real model invocation.
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    service = Harness(store, organization())
    executor = Executor(service, SimpleNamespace(repository=tmp_path), FileArtifacts(tmp_path / 'artifacts'))
    with store.transaction() as tx:
        tx.put('decisions_pending', 'decision', {'id': 'decision', 'actor': 'lead:improvement',
            'phase': 'diagnose', 'input': {'source_task_id': 'task', 'source_actor': 'worker:implementation',
                'evidence_ref': 'fixture:error', 'occurrence_id': 'occurrence'},
            'message': envelope('task.assign', 'lead:improvement', 'worker:implementation',
                                'implement', {}, 'correlation'), 'status': 'pending', 'attempt': 0})

    def fail(*args, **kwargs):
        raise RuntimeError('Controlled unit execution failure')

    monkeypatch.setattr(executor, '_run', fail)
    executor.decide_one('lead:improvement')
    with store.transaction() as tx:
        first = tx.get('decisions_pending', 'decision')
        assert first['status'] == 'retry'
        assert first['execution_deadline'] and first['execution_clock']['deadline_remaining'] > 0
    executor.decide_one('lead:improvement')
    with store.transaction() as tx:
        second = tx.get('decisions_pending', 'decision')
        assert second['attempt'] == first['attempt'] + 1
        assert second['execution_deadline'] == first['execution_deadline']
        assert second['execution_clock']['deadline_remaining'] <= first['execution_clock']['deadline_remaining']


@pytest.mark.parametrize("phase,actor", [("diagnose", "lead:improvement"),
                                        ("review_lead", "lead:improvement"),
                                        ("review_conductor", "conductor")])
@pytest.mark.parametrize("failure", ["none", "expired", "replaced", "commit_failed"])
@pytest.mark.parametrize("backend", ["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def test_decision_effects_require_current_lease_and_atomic_completion(
        tmp_path, monkeypatch, phase, actor, failure, backend, request):
    store = MemoryStore() if backend == "memory" else request.getfixturevalue("isolated_pgstore")
    service = Harness(store, organization())
    git = SimpleNamespace(repository=tmp_path, inspect=lambda *a: {},
                          review_workspace=lambda *a: str(tmp_path),
                          _git=lambda *a, **k: "" if a[0] == "status" else "revision")
    executor = Executor(service, git, FileArtifacts(tmp_path / "artifacts"))
    candidate = {"revision": "revision", "base": "base", "tree": "tree",
                 "author": "worker:implementation"}
    data = {"candidate": candidate, "source_actor": "worker:implementation",
            "occurrence_id": "occurrence", "source_task_id": "task",
            "evidence_ref": "fixture:error"}
    if phase == "review_conductor":
        release = executor.releases.propose(candidate, {"checks": ["tests"]})
        executor.releases.review(release["id"], "lead:improvement", "revision", True, "fixture:lead")
        data["release_id"] = release["id"]
    message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                       {}, "correlation")
    with service.store.transaction() as tx:
        before = tx.scan("releases")
        tx.put("decisions_pending", "decision", {"id": "decision", "actor": actor,
               "phase": phase, "input": data, "message": message, "status": "pending", "attempt": 0})

    def result(*args, **kwargs):
        if failure in {"expired", "replaced"}:
            with service.store.transaction() as tx:
                row = tx.get("decisions_pending", "decision")
                if failure == "expired":
                    row["lease_until"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                else:
                    row.update(owner="replacement", lease_owner="replacement",
                               generation=row["generation"] + 1)
                tx.put("decisions_pending", "decision", row)
        return {"accepted": True, "confirmed": True, "root_cause": "cause", "scope": "scope",
                "execution_ref": "fixture:review", "reason": "fixture"}

    monkeypatch.setattr(executor, "_run", result)
    transaction_type = MemoryTransaction if backend == "memory" else PostgresTransaction
    put = transaction_type.put

    def interrupted_put(tx, bucket, key, body):
        if failure == "commit_failed" and bucket == "decisions_pending" and body["status"] == "succeeded":
            raise OSError("fixture interrupted commit")
        put(tx, bucket, key, body)

    monkeypatch.setattr(transaction_type, "put", interrupted_put)
    executor.decide_one(actor)
    with service.store.transaction() as tx:
        if failure == "none":
            assert tx.get("decisions_pending", "decision")["status"] == "succeeded"
            if phase == "diagnose":
                assert len(tx.scan("incidents")) == 1
                assert not tx.scan("releases")
            elif phase == "review_lead":
                assert len(tx.scan("releases")) == len(tx.scan("outbox")) == 1
            else:
                assert tx.scan("releases")[0]["status"] == "reviewed"
                assert len(tx.scan("release_queue")) == 1
            return
        assert tx.scan("releases") == before
        for bucket in ("incidents", "hooks", "release_queue", "improvement_loops"):
            assert not tx.scan(bucket), bucket
        messages = [r['message'] for r in tx.scan('outbox')]
        if failure == 'commit_failed':
            # Failed business commit rolls back; the subsequent failure transition notifies.
            assert len(messages) == 1 and messages[0]['type'] == 'execution.notice'
            assert messages[0]['what']['details']['reason_code'] == 'execution_failed'
        else:
            assert not messages
        current = tx.get("decisions_pending", "decision")
        assert current["status"] != "succeeded"
        if failure == "replaced":
            assert current["lease_owner"] == "replacement" and current["status"] == "running"
