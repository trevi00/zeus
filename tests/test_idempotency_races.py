"""FA-004: same-key check and write are one serialized transaction, in separate processes too.

The upstream probe put a barrier between `already_done` and the append and got two events for
one key. Here the same pause sits after the read inside Zeus transactions; the advisory lock is
the only thing that separates the shipped store from the unlocked failure control.
"""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from test_workflow import assignment

from codex_harness.adapters.store import MemoryStore, MemoryTransaction
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import envelope

PAUSE = 0.4


def incident(cause, occurrence):
    return envelope('incident.report', 'worker:implementation', 'lead:improvement', 'record_incident',
                    {'occurrence_id': occurrence, 'root_cause': cause, 'scope': 'race',
                     'evidence_refs': ['fixture:error']}, 'race-correlation')


CHILD = r'''
import json, os, sys, time
from pathlib import Path
from codex_harness.adapters import store as store_module
from codex_harness.adapters.store import PostgresStore, PostgresTransaction
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization

spec = json.loads(Path(sys.argv[1]).read_text('utf-8'))
pause = spec['pause']
rendezvous = Path(spec['rendezvous'])
racers = spec['racers']

def wait_for(count, prefix, timeout):
    deadline = time.monotonic() + timeout
    while len(list(rendezvous.glob(prefix + '-*'))) < count:
        if time.monotonic() > deadline:
            raise SystemExit('rendezvous timeout: ' + prefix)
        time.sleep(0.005)

original_scan = PostgresTransaction.scan
read_marked = False
def paused_scan(self, bucket):
    global read_marked
    rows = original_scan(self, bucket)
    if spec['unlocked'] and bucket == spec['rendezvous_bucket'] and not read_marked:
        # The upstream barrier, made explicit: every racer has finished this read before any
        # of them writes. Only meaningful without the advisory lock (with it, this would deadlock).
        read_marked = True
        (rendezvous / ('read-' + spec['index'])).write_text('read', encoding='utf-8')
        wait_for(racers, 'read', 20)
    time.sleep(pause)
    return rows
PostgresTransaction.scan = paused_scan
if spec['unlocked']:
    import contextlib, psycopg
    @contextlib.contextmanager
    def unlocked(self):
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            yield PostgresTransaction(conn)
    PostgresStore.transaction = unlocked
store = PostgresStore(spec['dsn'])
# Ready ACK: the parent releases the gate only after every racer has imported and reached it.
(rendezvous / ('ready-' + spec['index'])).write_text('ready', encoding='utf-8')
gate = Path(spec['gate'])
deadline = time.monotonic() + 60
while not gate.exists():
    if time.monotonic() > deadline:
        raise SystemExit('gate timeout')
    time.sleep(0.005)
if spec['operation'] == 'record_incident':
    result = Harness(store, organization()).record_incident(spec['message'])
elif spec['operation'] == 'submit':
    result = Workflow(store, organization()).submit(spec['message'])
elif spec['operation'] == 'claim':
    result = Workflow(store, organization()).claim('worker:implementation', spec['owner'])
else:
    result = Workflow(store, organization()).handle(spec['message'])
print(json.dumps(result, ensure_ascii=False))
'''


RENDEZVOUS_BUCKETS = {'record_incident': 'incidents', 'submit': 'tasks', 'claim': 'tasks', 'handle': 'workflow_inbox'}


def race(store, tmp_path, operation, specs, unlocked=False):
    """Start every racer on a ready ACK, not a fixed sleep; unlocked racers also rendezvous after
    their read so the interleaving is fixed by the test, not by the scheduler (review, PR #38)."""
    script = tmp_path / 'racer.py'
    script.write_text(CHILD, encoding='utf-8')
    run = uuid4().hex
    rendezvous = tmp_path / ('rendezvous-' + run)
    rendezvous.mkdir()
    gate = tmp_path / ('gate-' + run)
    children = []
    try:
        for index, spec in enumerate(specs):
            path = tmp_path / f'spec-{operation}-{run}-{index}.json'
            path.write_text(json.dumps({**spec, 'operation': operation, 'dsn': store.dsn, 'gate': str(gate),
                                        'pause': PAUSE, 'unlocked': unlocked, 'index': str(index),
                                        'racers': len(specs), 'rendezvous': str(rendezvous),
                                        'rendezvous_bucket': RENDEZVOUS_BUCKETS[operation]}), encoding='utf-8')
            children.append(subprocess.Popen([sys.executable, str(script), str(path)], stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, env=dict(os.environ, PYTHONIOENCODING='utf-8'),
                                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        deadline = time.monotonic() + 60
        while len(list(rendezvous.glob('ready-*'))) < len(specs):
            assert time.monotonic() < deadline, 'racers did not become ready'
            assert all(child.poll() is None for child in children), 'a racer exited before the gate'
            time.sleep(0.01)
        gate.write_text('go', encoding='utf-8')
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=90)
            assert child.returncode == 0, stderr.decode('utf-8', 'replace')
            results.append(json.loads(stdout))
        return results
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)


def test_same_key_processes_serialize_on_postgres(isolated_pgstore, tmp_path):
    store = isolated_pgstore
    cause = 'race-cause-' + uuid4().hex[:8]
    strikes = [{'message': incident(cause, f'occurrence-{i}')} for i in range(4)]
    results = race(store, tmp_path, 'record_incident', strikes)
    assert sorted(r['occurrences'] for r in results) == [1, 2, 3, 4]
    assert sum(r['hook_created'] for r in results) == 1
    with store.transaction() as tx:
        assert len(tx.scan('hooks')) == 1 and len(tx.scan('outbox')) == 1 and len(tx.scan('incidents')) == 4
    task = assignment()
    submitted = race(store, tmp_path, 'submit', [{'message': task}] * 4)
    assert all(r == submitted[0] for r in submitted)
    claims = race(store, tmp_path, 'claim', [{'owner': f'owner-{i}'} for i in range(4)])
    assert sum(r is not None for r in claims) == 1
    with store.transaction() as tx:
        assert len(tx.scan('tasks')) == 1 and tx.get('tasks', task['message_id'])['attempt'] == 1
    if evidence := os.environ.get('ZEUS_RACE_EVIDENCE'):
        Path(evidence).write_text(json.dumps({
            'scope': 'Four interpreters per operation on an isolated PostgreSQL schema, file gate start, '
                     f'{PAUSE}s pause after every read inside the transaction; advisory lock present',
            'record_incident': results, 'submit_identical': all(r == submitted[0] for r in submitted),
            'claims': claims}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def test_unlocked_store_is_the_failure_control(isolated_pgstore, tmp_path):
    # Same racers, same pause, no advisory lock: every process reads before anyone writes, so
    # the second strike is lost even though the row upsert itself never duplicates a key.
    store = isolated_pgstore
    cause = 'race-cause-' + uuid4().hex[:8]
    strikes = [{'message': incident(cause, f'occurrence-{i}')} for i in range(4)]
    results = race(store, tmp_path, 'record_incident', strikes, unlocked=True)
    assert [r['occurrences'] for r in results] == [1, 1, 1, 1]
    assert sum(r['hook_created'] for r in results) == 0
    with store.transaction() as tx:
        assert len(tx.scan('incidents')) == 4 and tx.scan('hooks') == [] and tx.scan('outbox') == []
    if evidence := os.environ.get('ZEUS_RACE_EVIDENCE'):
        path = Path(evidence).with_name('unlocked-control.json')
        path.write_text(json.dumps({'scope': 'Same racers and pause without the advisory lock (probe-only patch)',
                                    'record_incident': results, 'lost_second_strike': True},
                                   ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


@pytest.mark.parametrize('operation', ['record_incident', 'claim'])
def test_memory_store_threads_serialize_with_the_same_pause(monkeypatch, operation):
    store = MemoryStore()
    original = MemoryTransaction.scan

    def paused(self, bucket):
        rows = original(self, bucket)
        time.sleep(PAUSE / 4)
        return rows
    monkeypatch.setattr(MemoryTransaction, 'scan', paused)
    if operation == 'record_incident':
        service = Harness(store, organization())
        cause = 'race-cause-' + uuid4().hex[:8]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(service.record_incident, [incident(cause, f'o-{i}') for i in range(4)]))
        assert sorted(r['occurrences'] for r in results) == [1, 2, 3, 4]
        assert sum(r['hook_created'] for r in results) == 1
    else:
        workflow = Workflow(store, organization())
        workflow.submit(assignment())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: workflow.claim('worker:implementation', f'owner-{i}'), range(4)))
        assert sum(r is not None for r in results) == 1
