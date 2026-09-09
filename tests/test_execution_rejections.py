import json
import os
import subprocess
import sys

import pytest
from test_workflow import assignment

from codex_harness.adapters.store import MemoryStore, MemoryTransaction, PostgresTransaction
from codex_harness.application.execution_rejections import reconcile
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
@pytest.mark.parametrize('field,value', [('generation', 9), ('attempt', 9), ('lease_owner', 'replacement'),
                                       ('agent', 'other'), ('recovery_sequence', 9), ('generation', True), ('none', None)])
def test_success_reconciliation_requires_complete_execution_identity(backend, field, value, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    completed = workflow.complete(lease, {'summary': 'committed'})
    with store.transaction() as tx:
        if field != 'none':
            completed[field] = value
            tx.put('tasks', lease['id'], completed)
        before = tx.records()
    result = reconcile(store, lease, ContractError('Stale execution'))
    assert result['status'] == ('succeeded' if field == 'none' else 'stale')
    assert reconcile(store, lease, ContractError('Stale execution')) == result
    if field != 'none':
        assert reconcile(store, lease, RuntimeError('New timestamp and error text')) == result
    with store.transaction() as tx:
        assert [r for r in tx.records() if r['bucket'] not in {'execution_rejections', 'events'}] == [
            r for r in before if r['bucket'] not in {'execution_rejections', 'events'}]
        assert len(tx.scan('execution_rejections')) == (0 if field == 'none' else 1)
        assert len([r for r in tx.scan('events') if r['type'] == 'execution.rejected']) == (0 if field == 'none' else 1)


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
@pytest.mark.parametrize('change,reason', [('missing', 'execution_missing'),
    ('failed', 'execution_not_running'), ('expired', 'execution_lease_expired'),
    ('invalid', 'invalid_execution_lease')])
def test_rejection_reasons_preserve_original_and_guard_errors(backend, change, reason, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    with store.transaction() as tx:
        current = tx.get('tasks', lease['id'])
        if change == 'missing':
            lease = {**lease, 'id': 'absent-execution'}
        elif change == 'failed':
            current['status'] = 'failed'
        else:
            current['lease_until'] = '2000-01-01T00:00:00+00:00' if change == 'expired' else 'invalid'
        tx.put('tasks', current['id'], current)
    result = reconcile(store, lease, RuntimeError('Original operation failed'), ContractError('Ownership rejected'))
    assert result['status'] == 'stale'
    with store.transaction() as tx:
        receipt = tx.get('execution_rejections', result['rejection_id'])
        assert receipt['request']['reason_code'] == reason
        assert receipt['error']['message'] == 'Original operation failed'
        assert receipt['rejection_error']['message'] == 'Ownership rejected'
        assert not tx.scan('outbox')


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_rejection_write_failure_rolls_back_and_valid_owner_errors_propagate(backend, request, monkeypatch):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    error = RuntimeError('Unrelated error')
    with pytest.raises(RuntimeError) as caught:
        reconcile(store, lease, error)
    assert caught.value is error
    workflow.cancel(lease['id'], 'conductor', 'test cancellation')
    kind = MemoryTransaction if backend == 'memory' else PostgresTransaction
    put = kind.put
    def interrupted(tx, bucket, key, body):
        put(tx, bucket, key, body)
        if bucket == 'events' and body['type'] == 'execution.rejected':
            raise OSError('Interrupted rejection commit')
    monkeypatch.setattr(kind, 'put', interrupted)
    with store.transaction() as tx:
        before = tx.records()
    with pytest.raises(OSError, match='Interrupted rejection'):
        reconcile(store, lease, ContractError('Stale'))
    with store.transaction() as tx:
        assert tx.records() == before


def test_real_postgres_process_redelivery_cannot_borrow_success(isolated_pgstore, tmp_path):
    store = isolated_pgstore
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    old = workflow.claim('worker:implementation', 'old')
    workflow.fail(old, 'Controlled retry')
    successor = workflow.claim('worker:implementation', 'successor')
    completed = workflow.complete(successor, {'summary': 'successor only'})
    path = tmp_path / 'old-execution.json'
    path.write_text(json.dumps(old), encoding='utf-8')
    script = '''
import json,os,sys
from pathlib import Path
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.execution_rejections import reconcile
from codex_harness.domain.model import ContractError
r=reconcile(PostgresStore(os.environ['REJECTION_TEST_DSN']),json.loads(Path(sys.argv[1]).read_text('utf-8')),ContractError('Stale execution'))
print(json.dumps(r))
'''
    env = dict(os.environ, REJECTION_TEST_DSN=store.dsn, PYTHONIOENCODING='utf-8')
    results = []
    children = [subprocess.Popen([sys.executable, '-c', script, str(path)], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0) for _ in range(2)]
    try:
        for child in children:
            stdout, stderr = child.communicate(timeout=30)
            assert child.returncode == 0, stderr.decode('utf-8')
            results.append(json.loads(stdout))
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)
    assert results[0] == results[1] and results[0]['status'] == 'stale'
    with store.transaction() as tx:
        assert tx.get('tasks', old['id']) == completed
        assert len(tx.scan('execution_rejections')) == 1
        assert len(tx.scan('outbox')) == 2  # Original retry notice and successor result only.
