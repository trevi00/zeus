"""FA-003: an expired or recreated execution never regains authority (INV-EXECUTION-IDENTITY-001)."""
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg
import pytest
from test_workflow import assignment

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, envelope
from codex_harness.domain.policy import POLICY


def backend_store(backend, request):
    return MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')


def purge(store, bucket, row_id):
    """Simulate a lost row (operator purge, partial restore); Zeus itself never deletes documents."""
    if isinstance(store, MemoryStore):
        del store.data[bucket, row_id]
    else:
        with psycopg.connect(store.dsn) as conn:
            conn.execute('DELETE FROM documents WHERE bucket=%s AND id=%s', (bucket, row_id))


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_expired_holder_cannot_act_after_reclaim(backend, request):
    store = backend_store(backend, request)
    w = Workflow(store, organization())
    task = w.submit(assignment())
    first = w.claim('worker:implementation', 'first-owner', lease_seconds=1)
    assert first['generation'] == 1
    time.sleep(1.2)
    second = w.claim('worker:implementation', 'second-owner', lease_seconds=60)
    assert second['id'] == task['id'] and second['generation'] == 2 and second['attempt'] == 2
    stale = [first, {**first, 'generation': 2}, {**first, 'lease_owner': 'second-owner'},
             {**second, 'generation': 1}]
    with store.transaction() as tx:
        before = tx.records()
    for handle in stale:
        with pytest.raises(ContractError, match='Stale or expired'):
            w.heartbeat(handle)
        with pytest.raises(ContractError, match='Stale or expired'):
            w.complete(handle, {'summary': 'stale'})
        with pytest.raises(ContractError, match='Stale or expired'):
            w.fail(handle, 'stale failure')
    with store.transaction() as tx:
        assert tx.records() == before, 'rejected stale actions leave no trace'
    w.heartbeat(second)
    assert w.complete(second, {'summary': 'current'})['status'] == 'succeeded'
    with store.transaction() as tx:
        fence = tx.get('execution_fences', 'tasks:' + task['id'])
    assert fence['generation'] == 2 and fence['owner'] == 'second-owner'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_recreated_task_row_cannot_reissue_generation(backend, request):
    store = backend_store(backend, request)
    w = Workflow(store, organization())
    message = assignment()
    task = w.submit(message)
    lease = w.claim('worker:implementation', 'owner')
    w.fail(lease, 'boom')
    with store.transaction() as tx:
        row = tx.get('tasks', task['id'])
    purge(store, 'tasks', task['id'])
    with pytest.raises(ContractError, match='used before'):
        w.submit(message)
    with store.transaction() as tx:
        assert tx.get('tasks', task['id']) is None
    # A tool that bypasses submit and re-inserts the row from generation 0 is blocked at claim.
    with store.transaction() as tx:
        tx.put('tasks', task['id'], {**row, 'status': 'queued', 'generation': 0, 'attempt': 0,
                                     'lease_owner': None, 'lease_until': None})
    healthy = w.submit(assignment())
    claimed = w.claim('worker:implementation', 'owner-2')
    assert claimed['id'] == healthy['id'], 'the healthy task is still served'
    with store.transaction() as tx:
        recreated = tx.get('tasks', task['id'])
        assert recreated['status'] == 'blocked' and recreated['error'] == 'ExecutionGenerationRegressed'
        assert recreated['lease_owner'] is None and recreated['generation'] == 0
        assert tx.get('execution_fences', 'tasks:' + task['id'])['generation'] == 1
        assert any(e['reason'] == 'ExecutionGenerationRegressed' for e in tx.scan('events') if 'reason' in e)
    with pytest.raises(ContractError, match='Stale or expired'):
        w.heartbeat(lease)


def test_cancel_and_corrupted_fence_fail_closed():
    store = MemoryStore()
    w = Workflow(store, organization())
    task = w.submit(assignment())
    w.cancel(task['id'], 'conductor', 'stop')
    with store.transaction() as tx:
        assert tx.get('execution_fences', 'tasks:' + task['id'])['generation'] == 1
    other = w.submit(assignment())
    with store.transaction() as tx:
        tx.put('execution_fences', 'tasks:' + other['id'], {'id': 'tasks:' + other['id'], 'generation': 'x'})
    assert w.claim('worker:implementation', 'owner') is None
    with store.transaction() as tx:
        assert tx.get('tasks', other['id'])['error'] == 'ExecutionGenerationRegressed'
    with pytest.raises(ContractError, match='regressed'):
        w.cancel(other['id'], 'conductor', 'stop')


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_release_controller_fence_survives_lock_expiry_and_row_recreation(backend, request):
    store = backend_store(backend, request)
    queue = ReleaseQueue(store)
    t0 = datetime.now(timezone.utc)
    with store.transaction() as tx:
        tx.put('release_queue', 'r1', {'id': 'r1', 'status': 'queued', 'at': t0.isoformat()})
    first = queue.claim(now=t0)
    assert first['generation'] == 1
    later = t0 + timedelta(seconds=POLICY.release_lease_seconds + 1)
    second = queue.claim(now=later)
    assert second['id'] == 'r1' and second['generation'] == 2 and second['owner'] != first['owner']
    with store.transaction() as tx:
        before = tx.records()
    for handle in (first, {**first, 'generation': 2}, {**second, 'owner': first['owner']}):
        with pytest.raises(ContractError, match='Stale release controller'):
            queue.heartbeat(handle, now=later)
        with pytest.raises(ContractError, match='Stale release controller'):
            queue.finish(handle, {'status': 'complete'}, now=later)
    with store.transaction() as tx:
        assert tx.records() == before
    queue.heartbeat(second, now=later)
    assert queue.finish(second, {'status': 'complete'}, now=later)['status'] == 'complete'
    with store.transaction() as tx:
        tx.put('release_queue', 'r1', {'id': 'r1', 'status': 'queued', 'at': t0.isoformat()})
    assert queue.claim(now=later) is None
    with store.transaction() as tx:
        row = tx.get('release_queue', 'r1')
        assert row['status'] == 'failed' and 'regressed' in row['reason']
        assert tx.get('execution_fences', 'release_queue:r1')['generation'] == 2


def test_recreated_decision_row_is_blocked_before_dispatch(tmp_path, monkeypatch):
    store = MemoryStore()
    service = Harness(store, organization())
    executor = Executor(service, SimpleNamespace(repository=tmp_path), FileArtifacts(tmp_path / 'artifacts'))
    row = {'id': 'decision', 'actor': 'lead:improvement', 'phase': 'diagnose',
           'input': {'source_task_id': 'task', 'source_actor': 'worker:implementation',
                     'evidence_ref': 'fixture:error', 'occurrence_id': 'occurrence'},
           'message': envelope('task.assign', 'lead:improvement', 'worker:implementation',
                               'implement', {}, 'correlation'), 'status': 'pending', 'attempt': 0}
    with store.transaction() as tx:
        tx.put('decisions_pending', 'decision', row)
    monkeypatch.setattr(executor, '_run', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('controlled')))
    executor.decide_one('lead:improvement')
    with store.transaction() as tx:
        assert tx.get('decisions_pending', 'decision')['status'] == 'retry'
        assert tx.get('execution_fences', 'decisions_pending:decision')['generation'] == 1
        tx.put('decisions_pending', 'decision', row)  # recreated from generation 0
    assert executor.decide_one('lead:improvement') is None
    with store.transaction() as tx:
        blocked = tx.get('decisions_pending', 'decision')
        assert blocked['status'] == 'blocked' and blocked['error'] == 'ExecutionGenerationRegressed'
        assert tx.get('execution_fences', 'decisions_pending:decision')['generation'] == 1
