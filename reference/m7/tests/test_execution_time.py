import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
from test_workflow import assignment

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.execution_recovery import ExecutionRecovery
from codex_harness.application.execution_time import ExecutionTimeError, check_clock
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization


@pytest.mark.parametrize('offset', [-30, 30])
def test_injected_schedule_time_cannot_change_host_lease_budget(offset):
    from codex_harness.domain.model import ContractError

    workflow = Workflow(MemoryStore(), organization())
    workflow.submit(assignment())
    with workflow.store.transaction() as tx:
        before = tx.records()
    with pytest.raises(ContractError, match='differs from host clock'):
        workflow.claim('worker:implementation', 'owner',
                       now=datetime.now(timezone.utc) + timedelta(seconds=offset))
    with workflow.store.transaction() as tx:
        assert tx.records() == before


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
@pytest.mark.parametrize('expired', [False, True])
def test_missing_attempt_cannot_abort_time_containment(backend, expired, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    workflow = Workflow(store, organization())
    message = assignment('research', 'worker:github')
    if expired:
        message['when']['deadline'] = '2000-01-01T00:00:00+00:00'
    with store.transaction() as tx:
        tx.put('tasks', 'poison', {'id': 'poison', 'agent': 'worker:github', 'message': message,
            'status': 'running', 'lease_until': None, 'created_at': '2000-01-01T00:00:00+00:00'})
    healthy = workflow.submit(assignment())
    assert workflow.claim('worker:implementation', 'healthy')['id'] == healthy['id']
    with store.transaction() as tx:
        row = tx.get('tasks', 'poison')
        assert row['status'] == ('expired' if expired else 'blocked')
        assert 'attempt' not in row and 'attempt_outcomes' not in row
        assert tx.scan('execution_time_events')[0]['attempt'] is None
        assert len(tx.scan('execution_notice_errors')) == 1


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_time_containment_retains_first_observation_on_redelivery(backend, request):
    from codex_harness.application.execution_time import contain_with_notice

    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    for observation in ({'sample': 'first'}, {'sample': 'later'}, None):
        with store.transaction() as tx:
            row = tx.get('tasks', lease['id'])
            contain_with_notice(tx, workflow.org, row, 'tasks', 'ClockDiscontinuity',
                                datetime.now(timezone.utc), observation)
    with store.transaction() as tx:
        events = tx.scan('execution_time_events')
        assert len(events) == len(tx.scan('execution_notices')) == 1
        assert events[0]['observation'] == {'sample': 'first'}


@pytest.mark.parametrize('wall_delta,mono_delta,reason', [(10, 10, None), (0, 10, 'ClockDiscontinuity'),
    (20, 10, 'ClockDiscontinuity'), (-10, 1, 'ClockDiscontinuity'), (0, -1, 'ClockDiscontinuity'),
    (0, float('nan'), 'InvalidExecutionClock'), (0, float('inf'), 'InvalidExecutionClock')])
def test_clock_comparison_contract(wall_delta, mono_delta, reason):
    # Pure input matrix, not a claim that the operating-system clock was changed.
    wall = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = {'execution_clock': {'version': 1, 'domain': 'sample', 'wall': wall.isoformat(),
           'monotonic': 100, 'lease_seconds': 600, 'deadline_remaining': None}}
    if reason:
        with pytest.raises(ExecutionTimeError, match=reason):
            check_clock(row, wall + timedelta(seconds=wall_delta), 100 + mono_delta, 'sample')
    else:
        assert check_clock(row, wall + timedelta(seconds=wall_delta), 100 + mono_delta, 'sample')[0] == mono_delta
    # A foreign monotonic origin never gets subtracted from the persisted origin.
    assert check_clock(row, wall, 1, 'another-process')[0] is None


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
@pytest.mark.parametrize('value', [None, 'invalid', '2026-01-01T00:00:00', True])
@pytest.mark.parametrize('bucket', ['tasks', 'decisions_pending'])
def test_bad_running_lease_is_contained_without_starving_healthy_task(backend, value, bucket, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    workflow = Workflow(store, organization())
    with store.transaction() as tx:
        tx.put(bucket, 'poison', {'id': 'poison', 'agent': 'worker:github', 'actor': 'lead:research',
            'message': assignment(), 'input': {}, 'status': 'running', 'generation': 1, 'attempt': 1,
            'lease_owner': 'old', 'lease_until': value, 'created_at': '2026-01-01T00:00:00+00:00'})
    task = workflow.submit(assignment())
    assert workflow.claim('worker:implementation', 'healthy')['id'] == task['id']
    with store.transaction() as tx:
        assert tx.get(bucket, 'poison')['error'] == 'InvalidExecutionLease'
        assert tx.get(bucket, 'poison')['status'] == 'blocked'
        assert len(tx.scan('execution_time_events')) == len(tx.scan('execution_notices')) == 1


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_discontinuity_is_durable_and_requires_explicit_repair(backend, request, tmp_path):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    # Corrupt the persisted observation to exercise containment; host clock remains unchanged.
    with store.transaction() as tx:
        row = tx.get('tasks', lease['id'])
        row['execution_clock']['wall'] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        tx.put('tasks', row['id'], row)
    with pytest.raises(ExecutionTimeError, match='ClockDiscontinuity'):
        workflow.heartbeat(lease)
    assert workflow.claim('worker:implementation', 'no-silent-resume') is None
    with store.transaction() as tx:
        assert tx.get('tasks', lease['id'])['status'] == 'blocked'
        event = tx.scan('execution_time_events')[0]
        assert event['observation']['delta_wall'] < -5
        assert len(tx.scan('execution_notices')) == 1
    artifacts = FileArtifacts(tmp_path / 'artifacts')
    ref = artifacts.put('Observed controlled clock-record discontinuity', 'test')['ref']
    recovery = ExecutionRecovery(store, organization(), artifacts)
    packet = recovery.prepare('tasks', lease['id'], operation='repair', max_attempts=4, deadline=None,
                              reason='Investigated clock basis', evidence_refs=[ref], operator='test-operator')
    recovery.apply(packet)
    assert workflow.claim('worker:implementation', 'repaired')['generation'] > lease['generation']


def test_real_deadline_across_process_restart_cannot_renew_or_commit(isolated_pgstore, tmp_path):
    store = isolated_pgstore
    workflow = Workflow(store, organization())
    message = assignment()
    message['when']['deadline'] = (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat()
    workflow.submit(message)
    lease = workflow.claim('worker:implementation', 'owner')
    assert datetime.fromisoformat(lease['lease_until']) <= datetime.fromisoformat(message['when']['deadline'])
    assert workflow.remaining_seconds(lease, 900) <= 3
    path = tmp_path / 'lease.json'
    path.write_text(json.dumps(lease), encoding='utf-8')
    time.sleep(max(0, (datetime.fromisoformat(message['when']['deadline']) - datetime.now(timezone.utc)).total_seconds()) + 0.1)
    script = '''
import json,os,sys
from pathlib import Path
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError
w=Workflow(PostgresStore(os.environ['TIME_TEST_DSN']),organization())
lease=json.loads(Path(sys.argv[1]).read_text('utf-8'))
try:
    w.complete(lease,{'summary':'must never commit'}) if sys.argv[2]=='complete' else w.heartbeat(lease)
except ContractError:
    print('rejected')
else:
    raise SystemExit('Late operation accepted')
'''
    for operation in ('complete', 'heartbeat'):
        result = subprocess.run([sys.executable, '-c', script, str(path), operation], capture_output=True,
            timeout=30, env=dict(os.environ, TIME_TEST_DSN=store.dsn),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        assert result.returncode == 0 and result.stdout.strip() == b'rejected'
    with store.transaction() as tx:
        row = tx.get('tasks', lease['id'])
        assert row['status'] == 'expired' and row['result'] is None
        assert len(tx.scan('execution_time_events')) == len(tx.scan('execution_notices')) == 1
        assert all(r['message']['type'] == 'execution.notice' for r in tx.scan('outbox'))
        assert tx.scan('execution_time_events')[0]['observation']['time_basis'] == 'utc_foreign_or_legacy'


def test_real_pg_lock_wait_is_not_a_clock_step(isolated_pgstore, tmp_path):
    store = isolated_pgstore
    workflow = Workflow(store, organization())
    first = workflow.submit(assignment('research', 'worker:github'))
    workflow.claim('worker:github', 'live-owner')
    healthy = workflow.submit(assignment())
    barrier = tmp_path / 'locked'
    script = '''
import os,sys,time
from pathlib import Path
from codex_harness.adapters.store import PostgresStore
with PostgresStore(os.environ['TIME_TEST_DSN']).transaction():
    Path(sys.argv[1]).write_text('locked')
    time.sleep(6)
'''
    child = subprocess.Popen([sys.executable, '-c', script, str(barrier)],
        env=dict(os.environ, TIME_TEST_DSN=store.dsn), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        limit = time.monotonic() + 15
        while not barrier.exists() and child.poll() is None and time.monotonic() < limit:
            time.sleep(0.02)
        assert barrier.exists()
        assert workflow.claim('worker:implementation', 'after-lock')['id'] == healthy['id']
        _, stderr = child.communicate(timeout=15)
        assert child.returncode == 0, stderr.decode('utf-8')
        with store.transaction() as tx:
            assert tx.get('tasks', first['id'])['status'] == 'running'
            assert not tx.scan('execution_time_events')
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
