import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from test_workflow import assignment

from codex_harness.adapters.bus import RedisBus
from codex_harness.adapters.contracts import validate_message
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.execution_notices import record
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization, redis_url
from codex_harness.domain.model import ContractError


def test_failure_notice_is_byte_stable_historical_and_informational():
    workflow = Workflow(MemoryStore(), organization())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'first')
    workflow.fail(lease, 'Private raw model failure text')
    with workflow.store.transaction() as tx:
        before = tx.records()
        message = tx.scan('execution_notices')[0]['message']
    assert 'Private raw model failure text' not in json.dumps(message)
    validate_message(message)
    workflow.fail(lease, 'Private raw model failure text')
    with workflow.store.transaction() as tx:
        assert tx.records() == before
    workflow.claim('worker:implementation', 'next-attempt')
    result = workflow.handle(message)
    assert result['authority'] == 'informational_only' and workflow.handle(message) == result
    with workflow.store.transaction() as tx:
        assert len(tx.scan('tasks')) == 1 and len(tx.scan('workflow_inbox')) == 1
        assert not tx.scan('decisions_pending') and not tx.scan('releases')


def test_unproven_notice_or_wrong_route_is_rejected():
    workflow = Workflow(MemoryStore(), organization())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    workflow.fail(lease, 'Failure')
    with workflow.store.transaction() as tx:
        message = tx.scan('execution_notices')[0]['message']
    changed = deepcopy(message)
    changed['what']['details']['status'] = 'succeeded'
    with pytest.raises(ContractError, match='Unproven'):
        workflow.handle(changed)
    changed = deepcopy(message)
    changed['who']['recipient'] = 'conductor'
    with pytest.raises(ContractError, match='reporting edge'):
        workflow.handle(changed)


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_invalid_notice_source_is_quarantined_without_undoing_containment(backend, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    workflow = Workflow(store, organization())
    task = workflow.submit(assignment())
    with store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        row.update(retry_budget=[], generation='invalid-generation')
        tx.put('tasks', task['id'], row)
    assert workflow.claim('worker:implementation', 'detect') is None
    with store.transaction() as tx:
        assert tx.get('tasks', task['id'])['status'] == 'blocked'
        assert len(tx.scan('execution_notice_errors')) == 1
        assert not tx.scan('execution_notices') and not tx.scan('outbox')
        assert any(r['type'] == 'execution.notice_quarantined' for r in tx.scan('events'))


def test_notice_identity_ignores_wall_clock_and_nonsemantic_source_metadata():
    store, org = MemoryStore(), organization()
    row = {'id': 'task', 'agent': 'worker:implementation', 'attempt': 1, 'generation': 1, 'status': 'expired'}
    with store.transaction() as tx:
        first = record(tx, org, row, 'tasks', 'deadline_exceeded', '2026-01-01T00:00:00+00:00')
        row['completed_at'] = '2026-01-02T00:00:00+00:00'
        again = record(tx, org, row, 'tasks', 'deadline_exceeded', '2026-01-02T00:00:00+00:00')
        assert first == again and len(tx.scan('outbox')) == 1


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_quarantine_is_serializable_and_semantic(backend, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    row = {'id': 'corrupt', 'agent': [], 'attempt': 1, 'status': 'failed',
           'extra': {1: object(), 'mixed': float('nan')}}
    with store.transaction() as tx:
        first = record(tx, organization(), row, 'tasks', 'execution_failed', 'first')
        row.update(lease_until='changed', error='different raw error')
        again = record(tx, organization(), row, 'tasks', 'execution_failed', 'later')
        assert first == again
        assert len(tx.scan('execution_notice_errors')) == len(tx.scan('events')) == 1
        assert not tx.scan('outbox')
        json.dumps(first, allow_nan=False, sort_keys=True)
        assert first['source']['extra']['invalid_mapping'][0][1] == {'invalid_type': 'object'}


def test_receipt_replay_survives_missing_notice_but_unprocessed_notice_does_not():
    workflow = Workflow(MemoryStore(), organization())
    workflow.submit(assignment())
    workflow.fail(workflow.claim('worker:implementation', 'owner'), 'Failure')
    with workflow.store.transaction() as tx:
        message = tx.scan('execution_notices')[0]['message']
        notice = tx.get('execution_notices', message['message_id'])
        tx.put('execution_notices', message['message_id'], {})
    with pytest.raises(ContractError, match='Unproven'):
        workflow.handle(message)
    with workflow.store.transaction() as tx:
        tx.put('execution_notices', message['message_id'], notice)
    result = workflow.handle(message)
    with workflow.store.transaction() as tx:
        tx.put('execution_notices', message['message_id'], {})
    assert workflow.handle(message) == result


CHILD = '''
import json,os,sys,time
from pathlib import Path
from codex_harness.adapters.store import PostgresStore
from codex_harness.adapters.bus import RedisBus
from codex_harness.application.workflow import Workflow
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
store=PostgresStore(os.environ['NOTICE_TEST_DATABASE'])
w=Workflow(store,organization())
mode,lease_file,barrier,namespace=sys.argv[1:]
lease=json.loads(Path(lease_file).read_text('utf-8'))
def pause():
    Path(barrier).write_text('ready',encoding='utf-8')
    while True: time.sleep(0.05)
if mode=='before_commit':
    with store.transaction() as tx:
        w.fail(lease,'Controlled child failure',transaction=tx)
        pause()
elif mode=='after_commit':
    w.fail(lease,'Controlled child failure')
    pause()
elif mode=='after_publish':
    class PausedAfterRealPublish(RedisBus):
        def publish(self,message):
            super().publish(message)
            pause()
    Harness(store,organization()).flush_outbox(PausedAfterRealPublish(os.environ['NOTICE_TEST_REDIS'],namespace))
elif mode=='after_consume':
    bus=RedisBus(os.environ['NOTICE_TEST_REDIS'],namespace)
    entry,fields=bus.receive('lead:improvement','doomed-consumer',idle_ms=0)
    w.handle(bus.decode(fields))
    pause()
'''


def kill_at(mode, lease_file, barrier, namespace, env):
    process = subprocess.Popen([sys.executable, '-c', CHILD, mode, str(lease_file), str(barrier), namespace],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        deadline = time.monotonic() + 45
        while not barrier.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert barrier.exists(), 'Child did not reach the instrumented real boundary'
        process.kill()
        _, stderr = process.communicate(timeout=15)
        assert process.returncode != 0, stderr.decode('utf-8')
        return {'pid': process.pid, 'exit_code': process.returncode, 'boundary': mode}
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=15)


def test_real_process_kill_matrix_preserves_state_notice_and_one_receiver_effect(isolated_pgstore, tmp_path):
    workflow = Workflow(isolated_pgstore, organization())
    task = workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'real-process-probe', lease_seconds=600)
    lease_file = tmp_path / '실제 프로세스 경로.json'
    lease_file.write_text(json.dumps(lease), encoding='utf-8')
    namespace = 'notice-kill-' + uuid4().hex
    bus = RedisBus(redis_url(), namespace)
    bus.client.ping()
    env = dict(os.environ, NOTICE_TEST_DATABASE=isolated_pgstore.dsn, NOTICE_TEST_REDIS=redis_url(), PYTHONIOENCODING='utf-8')
    observations = []
    try:
        observations.append(kill_at('before_commit', lease_file, tmp_path / 'before', namespace, env))
        with isolated_pgstore.transaction() as tx:
            assert tx.get('tasks', task['id'])['status'] == 'running'
            assert not tx.scan('execution_failures') and not tx.scan('execution_notices') and not tx.scan('outbox')
        observations.append(kill_at('after_commit', lease_file, tmp_path / 'committed', namespace, env))
        with isolated_pgstore.transaction() as tx:
            assert tx.get('tasks', task['id'])['status'] == 'retry'
            assert len(tx.scan('execution_failures')) == len(tx.scan('execution_notices')) == len(tx.scan('outbox')) == 1
            notice = tx.scan('execution_notices')[0]
            assert 'Controlled child failure' not in json.dumps(notice['message'])
            before = tx.records()
        workflow.fail(lease, 'Controlled child failure')
        with isolated_pgstore.transaction() as tx:
            assert tx.records() == before
        observations.append(kill_at('after_publish', lease_file, tmp_path / 'published', namespace, env))
        with isolated_pgstore.transaction() as tx:
            assert tx.scan('outbox')[0]['sent'] is False
            assert tx.scan('outbox_delivery')[0]['status'] == 'publishing'
        assert bus.client.xlen(bus.stream('lead:improvement')) == 1
        assert Harness(isolated_pgstore, organization()).flush_outbox(bus)['published'] == 1
        assert bus.client.xlen(bus.stream('lead:improvement')) == 2
        observations.append(kill_at('after_consume', lease_file, tmp_path / 'consumed', namespace, env))
        pending = bus.client.xpending_range(bus.stream('lead:improvement'), 'workers', '-', '+', 10)
        assert len(pending) == 1 and pending[0]['consumer'] == 'doomed-consumer'
        for _ in range(2):
            entry, fields = bus.receive('lead:improvement', 'recovery-consumer', idle_ms=0)
            assert workflow.handle(bus.decode(fields))['authority'] == 'informational_only'
            bus.ack('lead:improvement', entry)
        with isolated_pgstore.transaction() as tx:
            assert len(tx.scan('workflow_inbox')) == 1 and len(tx.scan('tasks')) == 1
            assert not tx.scan('decisions_pending') and not tx.scan('releases')
        assert bus.client.xpending(bus.stream('lead:improvement'), 'workers')['pending'] == 0
        evidence = {'processes': observations, 'scope': 'Real PG/Redis and killed child processes, no model execution',
                    'redis_copies': 2, 'receiver_effects': 1, 'task_id': task['id'], 'notice_id': notice['id'],
                    'stream_entries': [{'entry_id': entry, 'message_id': bus.decode(fields)['message_id']}
                                       for entry, fields in bus.client.xrange(bus.stream('lead:improvement'))],
                    'reclaimed_from': pending[0]['consumer']}
        if directory := os.environ.get('ZEUS_NOTICE_TEST_EVIDENCE'):
            Path(directory).mkdir(parents=True, exist_ok=True)
            (Path(directory) / ('kill-matrix-' + uuid4().hex + '.json')).write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    finally:
        keys = list(bus.client.scan_iter(match=namespace + ':*'))
        if keys:
            bus.client.delete(*keys)
