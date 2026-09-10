"""FA-017: actual process fencing, distinct from authenticated user isolation."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_workflow import assignment

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, digest


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
@pytest.mark.parametrize('bucket', ['tasks', 'decisions_pending'])
@pytest.mark.parametrize('field,value', [('agent', 'other'), ('actor', 'other'),
    ('recovery_sequence', 9), ('recovery_sequence', False), ('recovery_sequence', 0.0),
    ('lease_owner', 'other')])
def test_failure_receipt_rechecks_full_typed_identity(backend, bucket, field, value, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    w = Workflow(store, organization())
    w.submit(assignment())
    lease = w.claim('worker:implementation', 'owner')
    if bucket != 'tasks':
        w.complete(lease, {'candidate': {'revision': 'a' * 40, 'base': 'b' * 40,
                    'tree': 'c' * 40, 'author': lease['agent']}})
        with store.transaction() as tx:
            report = tx.scan('outbox')[0]['message']
        w.handle(report)
        with store.transaction() as tx:
            row = tx.get(bucket, report['message_id'])
            assert 'actor' in row and 'agent' not in row
            row.update(status='running', attempt=1, generation=1, lease_owner='owner',
                       lease_until=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
            tx.put(bucket, row['id'], row)
        lease = {**row, '_bucket': bucket}
    failed = w.fail(lease, 'explicit failure')
    expected = digest({'bucket': bucket, 'task_id': lease['id'], 'generation': lease['generation'],
        'attempt': lease['attempt'], 'owner': 'owner', 'error': 'explicit failure',
        'retryable': True, 'failure': None})
    assert failed['failure_receipt'] == expected  # Historical digest input remains unchanged.
    with store.transaction() as tx:
        before = tx.records()
    assert w.fail(lease, 'explicit failure') == failed  # Missing actor/recovery key symmetry.
    rejection = 'Stale or expired task execution' if field == 'lease_owner' else 'Stale failure retry'
    # Changed owner misses the digest and hits ordinary terminal-state rejection.
    with pytest.raises(ContractError, match=rejection):
        w.fail({**lease, field: value}, 'explicit failure')
    if bucket == 'decisions_pending':
        missing_actor = {k: v for k, v in lease.items() if k != 'actor'}
        with pytest.raises(ContractError, match='Stale failure retry'):
            w.fail(missing_actor, 'explicit failure')
    with store.transaction() as tx:
        assert tx.records() == before
        assert len(tx.scan('execution_failures')) == len(tx.scan('execution_notices')) == 1


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_failure_receipt_retains_historical_digest(backend, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    w = Workflow(store, organization())
    message = assignment()
    message['message_id'] = '00000000-0000-4000-8000-000000000001'
    w.submit(message)
    lease = w.claim('worker:implementation', 'owner')
    failed = w.fail(lease, 'explicit failure')
    assert failed['failure_receipt'] == '47b73837d2a235941c1126112e7038bc12764c817985ccdf1c5f1158768c3fdc'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
@pytest.mark.parametrize('field,value', [('created_at', None), ('created_at', True),
    ('created_at', {}), ('created_at', 'bad'), ('created_at', '2026-01-01T00:00:00'),
    ('status', None), ('status', True), ('status', '')])
def test_bad_queue_metadata_cannot_abort_other_agent_claim(backend, field, value, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    w = Workflow(store, organization())
    poison = w.submit(assignment('research', 'worker:github'))
    healthy = w.submit(assignment())
    with store.transaction() as tx:
        row = tx.get('tasks', poison['id'])
        if value is None:
            row.pop(field)
        else:
            row[field] = value
        tx.put('tasks', row['id'], row)
    assert w.claim('worker:implementation', 'healthy')['id'] == healthy['id']
    with store.transaction() as tx:
        row = tx.get('tasks', poison['id'])
        assert row['status'] == 'blocked'
        assert row['error'] == ('InvalidExecutionOrder' if field == 'created_at' else 'InvalidExecutionState')
        assert len(tx.scan('execution_notices')) == 1 and not tx.scan('execution_notice_errors')


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
@pytest.mark.parametrize('value', [None, True, ''])
def test_bad_decision_status_is_contained_before_claim(backend, value, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    w = Workflow(store, organization())
    healthy = w.submit(assignment())
    poison = {'id': 'poison', 'actor': 'lead:research', 'attempt': 0, 'generation': 0}
    if value is not None:
        poison['status'] = value
    with store.transaction() as tx:
        tx.put('decisions_pending', poison['id'], poison)
    assert w.claim('worker:implementation', 'healthy')['id'] == healthy['id']
    with store.transaction() as tx:
        assert tx.get('decisions_pending', poison['id'])['error'] == 'InvalidExecutionState'
        assert len(tx.scan('execution_notices')) == 1 and not tx.scan('execution_notice_errors')


CHILD = '''
import json,os,sys
from pathlib import Path
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError
w=Workflow(PostgresStore(os.environ['IDENTITY_TEST_DSN']),organization())
data=json.loads(Path(sys.argv[1]).read_text('utf-8'));op=data['operation']
try:
 if op=='claim': result=w.claim(data['agent'],data['owner'])
 elif op=='heartbeat': w.heartbeat(data['lease']);result={'accepted':True}
 elif op=='fail': result=w.fail(data['lease'],'explicit failure')
 elif op=='complete': result=w.complete(data['lease'],{'summary':'explicit process completion'})
 else: raise ValueError(op)
except ContractError as exc:
 result={'rejected':str(exc)}
print(json.dumps(result))
'''


@pytest.mark.parametrize('nested', [False, True])
def test_native_shared_paths_tied_times_retry_and_foreign_fencing(isolated_pgstore, tmp_path, nested):
    store = isolated_pgstore
    w = Workflow(store, organization())
    root = tmp_path / 'shared project \uac80\uc99d'
    root.mkdir()
    other_root = root / 'nested project' if nested else root
    other_root.mkdir(exist_ok=True)
    tasks = sorted([w.submit(assignment('research', 'worker:github')) for _ in range(2)], key=lambda t: t['id'])
    foreign = w.submit(assignment())
    tied = datetime.now(timezone.utc).isoformat()
    with store.transaction() as tx:
        for task, cwd in [(tasks[0], root), (tasks[1], other_root), (foreign, root)]:
            row = tx.get('tasks', task['id'])
            # Extension fixtures prove row preservation, not a native retrospective feature.
            row.update(created_at=tied, heartbeat_at=tied,
                project_context={'id': task['id'], 'cwd': str(cwd)},
                retrospective={'seen': 3, 'target': 5, 'ref': 'fixture:' + task['id']})
            tx.put('tasks', row['id'], row)
    script = root / 'native.py'
    script.write_text(CHILD, encoding='utf-8')
    observations = []

    def run(operation, cwd=root, **data):
        path = root / 'input.json'
        path.write_text(json.dumps({'operation': operation, **data}), encoding='utf-8')
        child = subprocess.run([sys.executable, str(script), str(path)], cwd=cwd,
            env=dict(os.environ, IDENTITY_TEST_DSN=store.dsn, PYTHONIOENCODING='utf-8'),
            capture_output=True, timeout=40,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        assert child.returncode == 0, child.stderr.decode('utf-8')
        result = json.loads(child.stdout)
        observations.append({'operation': operation, 'cwd': str(cwd), 'exit_code': child.returncode,
                             'result': result})
        return result

    first = run('claim', agent='worker:github', owner='first-owner')
    other = run('claim', cwd=other_root, agent='worker:implementation', owner='other-owner')
    assert first['id'] == tasks[0]['id'] and other['id'] == foreign['id']
    # Equal lease timestamps are explicit PG fixture inputs, not simultaneous host events.
    with store.transaction() as tx:
        for lease in (first, other):
            row = tx.get('tasks', lease['id'])
            row['lease_until'] = min(first['lease_until'], other['lease_until'])
            tx.put('tasks', row['id'], row)
        sibling = tx.get('tasks', tasks[1]['id'])
        other_before = tx.get('tasks', other['id'])
    assert run('heartbeat', lease=first) == {'accepted': True}
    with store.transaction() as tx:
        assert tx.get('tasks', other['id']) == other_before
        first_before = tx.get('tasks', first['id'])
    assert run('heartbeat', cwd=other_root, lease=other) == {'accepted': True}
    with store.transaction() as tx:
        assert tx.get('tasks', first['id']) == first_before
        other_before = tx.get('tasks', other['id'])
    for field, value in [('id', other['id']), ('lease_owner', 'other-owner'),
                         ('generation', 9), ('agent', other['agent']), ('recovery_sequence', 9)]:
        with store.transaction() as tx:
            before = tx.records()
        assert 'rejected' in run('heartbeat', cwd=other_root, lease={**first, field: value})
        with store.transaction() as tx:
            assert tx.records() == before
    failed = run('fail', lease=first)
    assert run('fail', cwd=other_root, lease=first) == failed
    for field, value in [('agent', other['agent']), ('actor', 'other'), ('recovery_sequence', 9)]:
        with store.transaction() as tx:
            before = tx.records()
        assert 'rejected' in run('fail', cwd=other_root, lease={**first, field: value})
        with store.transaction() as tx:
            assert tx.records() == before
    resumed = run('claim', cwd=other_root, agent='worker:github', owner='restarted-owner')
    assert resumed['id'] == first['id'] and resumed['attempt'] == 2
    assert resumed['generation'] == first['generation'] + 1
    assert all(resumed[k] == first[k] for k in ('message', 'input_hash', 'project_context', 'retrospective'))
    completed = run('complete', lease=resumed)
    assert completed['status'] == 'succeeded'
    with store.transaction() as tx:
        assert tx.get('tasks', other['id']) == other_before
        assert tx.get('tasks', tasks[1]['id']) == sibling
        assert len(tx.scan('execution_failures')) == len(tx.scan('execution_notices')) == 1
    assert run('claim', cwd=other_root, agent='worker:github', owner='next-owner')['id'] == sibling['id']
    if evidence := os.environ.get('ZEUS_IDENTITY_TEST_EVIDENCE'):
        path = Path(evidence)
        path.mkdir(parents=True, exist_ok=True)
        (path / ('nested.json' if nested else 'shared.json')).write_text(json.dumps({
            'scope': 'Real PG and child processes; explicit extension-state and equal-time fixtures; '
                     'executor fencing, not tenant authentication or model/human E2E',
            'nested': nested, 'observations': observations}, indent=2) + '\n', encoding='utf-8')
