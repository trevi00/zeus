"""Ported SOURCE M7 suite `tests/test_retry_state.py` (e38aa722) run against the S8 target.

Every assertion is M7's, unchanged. Adaptations, all construction/import/patch-target (each is named in the `m7_executor` shim docstring, the P9 additions included): `Executor`, `Harness` (the carrier `m7_executor.Service`) and `organization` come from the shims, every other M7 `codex_harness.adapters|application|domain` name from its target home (`kernel`, `storage`, `execution`, `research`, `host_os`, `evidence`, `context`, `coordination`, `review`), and the patch target `codex_harness.adapters.executor.AppServer` is `m7_executor.AppServer`. The child process of the real-PostgreSQL test imports `PostgresStore` from `storage.adapters.postgres_store` and `Workflow`/`organization` from `m7_coordination` (its PYTHONPATH is this directory); that test needs a disposable PostgreSQL (`ZEUS_TEST_DSN`) and skips without one, so its child script was import-checked only. `executor._fail_task` is RunTask's.
"""
import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest
from m7_coordination import Workflow, organization
from m7_executor import Executor
from m7_executor import Service as Harness
from test_workflow import assignment

from codex_harness.kernel.errors import ContractError
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore


@pytest.fixture(params=['memory', 'postgres'])
def workflow(request):
    store = MemoryStore() if request.param == 'memory' else request.getfixturevalue('isolated_pgstore')
    return Workflow(store, organization())


def test_failure_redelivery_is_read_only_and_keeps_context_and_old_evidence(workflow):
    task = workflow.submit(assignment())
    context = {'project_id': 'project-1', 'retrospective': {'seen': 3, 'target': 5, 'ref': 'retained-observation'}}
    with workflow.store.transaction() as tx:
        current = tx.get('tasks', task['id'])
        tx.put('tasks', task['id'], {**current, **context})
    lease = workflow.claim('worker:implementation', 'first')
    evidence = {'kind': 'runtime-failure', 'ref': 'first-attempt-observation'}
    failed = workflow.fail(lease, 'Invalid JSON', failure=evidence)
    with workflow.store.transaction() as tx:
        before = tx.records()
    assert workflow.fail(lease, 'Invalid JSON', failure=evidence) == failed
    with workflow.store.transaction() as tx:
        assert tx.records() == before
    resumed = Workflow(workflow.store, workflow.org).claim('worker:implementation', 'after-restart')
    assert resumed['id'] == task['id'] and resumed['attempt'] == 2
    assert all(resumed[k] == v for k, v in context.items())
    with pytest.raises(ContractError, match='Stale failure retry'):
        workflow.fail(lease, 'Invalid JSON', failure=evidence)
    latest = workflow.fail(resumed, 'Empty output')
    assert latest['failure'] is None
    assert latest['attempt_outcomes'][0]['failure'] == evidence
    assert len(latest['attempt_outcomes']) == 2


def test_failure_receipt_and_state_rollback_together(workflow):
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    with pytest.raises(OSError):
        with workflow.store.transaction() as tx:
            workflow.fail(lease, 'Invalid JSON', transaction=tx)
            raise OSError('Commit unavailable')
    with workflow.store.transaction() as tx:
        assert not tx.scan('execution_failures')
        assert tx.get('tasks', lease['id'])['status'] == 'running'
    assert workflow.fail(lease, 'Invalid JSON')['status'] == 'retry'


def test_bound_budget_cannot_be_raised_after_restart_and_conflict_does_not_starve_other_task(workflow):
    first = workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'first', max_attempts=1)
    workflow.fail(lease, 'Malformed result')
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', first['id'])
        # The assertion below observes a conflict only if this row is inspected
        # before the healthy sibling. Same-clock UUID order is tested separately.
        row['created_at'] = '2000-01-01T00:00:00+00:00'
        tx.put('tasks', first['id'], row)
    second = workflow.submit(assignment())
    fresh = Workflow(workflow.store, workflow.org)
    next_lease = fresh.claim('worker:implementation', 'new-process', max_attempts=2)
    assert next_lease['id'] == second['id']
    fresh.fail(next_lease, 'Not retryable', retryable=False)
    assert fresh.claim('worker:implementation', 'new-process') is None
    with workflow.store.transaction() as tx:
        original = tx.get('tasks', first['id'])
        assert original['retry_budget']['max_attempts'] == original['attempt'] == 1
        assert original['status'] == 'failed' and original['error'] == 'attempt budget exhausted'
        assert len([r for r in tx.scan('events') if r['type'] == 'execution.retry_budget_conflict']) == 1


@pytest.mark.parametrize('name,value', [('lease_seconds', True), ('lease_seconds', 0),
    ('lease_seconds', float('inf')), ('lease_seconds', 10**100), ('max_attempts', True),
    ('max_attempts', 1.5), ('max_attempts', float('nan')), ('max_attempts', float('inf')),
    ('now', datetime(2026, 1, 1))])
def test_invalid_execution_parameters_do_not_change_runtime(workflow, name, value):
    workflow.submit(assignment())
    with workflow.store.transaction() as tx:
        before = tx.records()
    with pytest.raises(ContractError):
        workflow.claim('worker:implementation', 'owner', **{name: value})
    with workflow.store.transaction() as tx:
        assert tx.records() == before


@pytest.mark.parametrize('deadline', [True, 1, float('nan'), 'NaN', '2026-01-01T00:00:00'])
def test_invalid_deadline_never_enters_queue(workflow, deadline):
    message = assignment()
    message['when']['deadline'] = deadline
    with pytest.raises(ContractError):
        workflow.submit(message)
    with workflow.store.transaction() as tx:
        assert not tx.scan('tasks')


def test_invalid_failure_evidence_does_not_commit(workflow):
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    with pytest.raises(ContractError, match='finite JSON'):
        workflow.fail(lease, 'Invalid observation', failure={'elapsed': float('nan')})
    with workflow.store.transaction() as tx:
        assert not tx.scan('execution_failures') and tx.get('tasks', lease['id'])['status'] == 'running'


def test_committed_failure_cannot_replay_after_cancellation(workflow):
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    workflow.fail(lease, 'Malformed')
    workflow.cancel(lease['id'], 'conductor', 'Operator cancellation')
    with pytest.raises(ContractError, match='Stale'):
        workflow.fail(lease, 'Malformed')


def test_real_pg_process_restart_preserves_failure_receipt_and_budget(isolated_pgstore, tmp_path):
    workflow = Workflow(isolated_pgstore, organization())
    task = workflow.submit(assignment())
    project = tmp_path / '프로젝트 경로'
    project.mkdir()
    lease_file = project / '실행.json'
    context = {'project_context': {'id': 'process-project', 'root': str(project)},
               'retrospective': {'observed': 3, 'target': 5, 'reference': 'isolated-context-fixture'}}
    with isolated_pgstore.transaction() as tx:
        row = tx.get('tasks', task['id'])
        tx.put('tasks', task['id'], {**row, **context})
    child = '''
import json,os,sys
from pathlib import Path
from codex_harness.storage.adapters.postgres_store import PostgresStore
from m7_coordination import Workflow, organization
w=Workflow(PostgresStore(os.environ['RETRY_TEST_DATABASE']),organization())
path=Path(sys.argv[2])
if sys.argv[1]=='claim':
    result=w.claim('worker:implementation','actual-child',max_attempts=int(sys.argv[3]))
    if result: path.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
else:
    lease=json.loads(path.read_text('utf-8'))
    try: json.loads('')
    except ValueError as error: result=w.fail(lease,type(error).__name__)
print(json.dumps(result,ensure_ascii=False))
'''
    env = dict(os.environ, RETRY_TEST_DATABASE=isolated_pgstore.dsn, PYTHONIOENCODING='utf-8',
               PYTHONPATH=os.path.dirname(__file__))
    results = []
    for mode, budget in [('claim', '1'), ('fail', '0'), ('fail', '0'), ('claim', '2')]:
        process = subprocess.run([sys.executable, '-c', child, mode, str(lease_file), budget],
                                 env=env, capture_output=True, check=True, timeout=30)
        results.append(json.loads(process.stdout))
    assert results[0]['id'] == task['id'] and results[1] == results[2] and results[3] is None
    assert all(results[1][k] == v for k, v in context.items())
    with isolated_pgstore.transaction() as tx:
        assert len(tx.scan('execution_failures')) == 1
        assert tx.get('tasks', task['id'])['attempt'] == 1
    assert json.loads(lease_file.read_text('utf-8'))['generation'] == 1


def test_decision_failure_receipt_is_scoped_to_its_aggregate(workflow):
    workflow.submit(assignment())
    task = workflow.claim('worker:implementation', 'owner')
    decision = {**deepcopy(task), '_bucket': 'decisions_pending'}
    with workflow.store.transaction() as tx:
        tx.put('decisions_pending', task['id'], {k: v for k, v in decision.items() if k != '_bucket'})
    workflow.fail(task, 'Same input')
    failed = workflow.fail(decision, 'Same input')
    assert workflow.fail(decision, 'Same input') == failed
    with workflow.store.transaction() as tx:
        assert len(tx.scan('execution_failures')) == 2


def test_legacy_attempt_does_not_invent_its_original_budget(workflow):
    task = workflow.submit(assignment())
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        tx.put('tasks', task['id'], {**row, 'attempt': 1, 'status': 'retry'})
    assert workflow.claim('worker:implementation', 'after-upgrade', max_attempts=99) is None
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        assert row['status'] == 'blocked' and row['error'] == 'UnverifiedLegacyRetryBudget'
        assert 'retry_budget' not in row and row['attempt'] == 1


def test_dependency_wait_does_not_pin_a_budget(workflow):
    dependency = workflow.submit(assignment(agent='worker:github'))
    message = assignment()
    message['when']['after'] = [dependency['id']]
    task = workflow.submit(message)
    assert workflow.claim('worker:implementation', 'early-observer', max_attempts=1) is None
    with workflow.store.transaction() as tx:
        assert 'retry_budget' not in tx.get('tasks', task['id'])
    lease = workflow.claim('worker:github', 'dependency-owner')
    workflow.complete(lease, {'summary': 'Dependency test complete'})
    claimed = workflow.claim('worker:implementation', 'actual-owner', max_attempts=2)
    assert claimed['retry_budget']['max_attempts'] == 2


@pytest.mark.parametrize('field,value', [('deadline', 'not-a-time'), ('deadline', '2026-01-01T00:00:00'),
                                       ('budget', []), ('budget', {'version': 1, 'max_attempts': True})])
def test_corrupted_stored_deadline_or_budget_does_not_starve_another_task(workflow, field, value):
    bad = workflow.submit(assignment())
    good = workflow.submit(assignment())
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', bad['id'])
        # Exercise the corrupt-row branch before the healthy claim, independently
        # of Windows clock resolution and random message-ID ordering on ties.
        row['created_at'] = '2000-01-01T00:00:00+00:00'
        if field == 'deadline':
            row['message']['when']['deadline'] = value
        else:
            row['retry_budget'] = value
        tx.put('tasks', bad['id'], row)
    claimed = workflow.claim('worker:implementation', 'owner')
    assert claimed['id'] == good['id']
    with workflow.store.transaction() as tx:
        assert tx.get('tasks', bad['id'])['status'] == 'blocked'
        assert any(e['type'] == 'execution.state_blocked' for e in tx.scan('events'))


@pytest.mark.parametrize('corrupt_first', [True, False])
def test_equal_creation_times_use_identity_and_eventually_isolate_corruption(workflow, corrupt_first):
    messages = [assignment(), assignment()]
    for i, message in enumerate(messages):
        message['message_id'] = f'00000000-0000-4000-8000-{i + 1:012d}'
        message['when']['created_at'] = '2026-01-01T00:00:00+00:00'
    tasks = [workflow.submit(message) for message in messages]
    bad, good = tasks if corrupt_first else tasks[::-1]
    with workflow.store.transaction() as tx:
        for task in tasks:
            row = tx.get('tasks', task['id'])
            row['created_at'] = '2026-01-01T00:00:00+00:00'
            tx.put('tasks', task['id'], row)
        row = tx.get('tasks', bad['id'])
        row['message']['when']['deadline'] = 'invalid'
        tx.put('tasks', bad['id'], row)
    lease = workflow.claim('worker:implementation', 'owner')
    assert lease['id'] == good['id']
    with workflow.store.transaction() as tx:
        assert tx.get('tasks', bad['id'])['status'] == ('blocked' if corrupt_first else 'queued')
    workflow.fail(lease, 'Finished test work', retryable=False)
    assert workflow.claim('worker:implementation', 'next-owner') is None
    with workflow.store.transaction() as tx:
        assert tx.get('tasks', bad['id'])['status'] == 'blocked'
        assert len([e for e in tx.scan('events') if e['type'] == 'execution.state_blocked']) == 1


def test_executor_failure_replay_does_not_rewrite_diagnosis_artifact(workflow, tmp_path, monkeypatch):
    artifacts = FileArtifacts(tmp_path / 'artifacts')
    executor = Executor(Harness(workflow.store, workflow.org), SimpleNamespace(repository=tmp_path), artifacts,
                        research=SimpleNamespace())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    error = RuntimeError('Actual failure callback test')
    result = executor._fail_task(lease, 'worker:implementation', error)
    assert result['status'] == 'retry'
    monkeypatch.setattr(artifacts, 'put', lambda *a, **k: pytest.fail('Replay rewrote artifact'))
    with workflow.store.transaction() as tx:
        before = tx.records()
    assert executor._fail_task(lease, 'worker:implementation', error) == result
    with workflow.store.transaction() as tx:
        assert tx.records() == before
