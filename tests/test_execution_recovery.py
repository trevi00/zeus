import json
import os
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from test_workflow import assignment

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.execution_recovery import ExecutionRecovery
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, canonical, digest


@pytest.fixture(params=['memory', 'postgres'])
def workflow(request):
    store = MemoryStore() if request.param == 'memory' else request.getfixturevalue('isolated_pgstore')
    return Workflow(store, organization())


@pytest.fixture
def recovery(workflow, tmp_path):
    return ExecutionRecovery(workflow.store, workflow.org, FileArtifacts(tmp_path / 'artifacts'))


def exhausted(workflow):
    task = workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner', max_attempts=1)
    workflow.fail(lease, 'Actual failure API input')
    assert workflow.claim('worker:implementation', 'after-failure') is None
    return task, lease


def prepare(recovery, task_id, **kwargs):
    ref = recovery.artifacts.put('Operator recovery rationale test fixture', 'unit-test')['ref']
    return recovery.prepare('tasks', task_id, **{'operation': 'resume', 'max_attempts': 2,
        'deadline': None, 'reason': 'Investigated transient failure', 'operator': 'test-operator',
        'evidence_refs': [ref], **kwargs})


def test_recovery_preserves_history_fences_replay_and_does_not_spend_attempt(workflow, recovery):
    task, lease = exhausted(workflow)
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        row.update(project_context={'id': 'same-project'}, retrospective={'seen': 3, 'target': 5})
        tx.put('tasks', task['id'], row)
    packet = prepare(recovery, task['id'])
    recovered = recovery.apply(packet)
    row = recovered['execution']
    assert row['attempt'] == 1 and row['generation'] == 2 and row['retry_budget']['version'] == 2
    assert row['message'] == task['message'] and row['input_hash'] == task['input_hash']
    assert row['retrospective'] == {'seen': 3, 'target': 5}
    assert row['attempt_outcomes'] == packet['previous']['attempt_outcomes']
    with workflow.store.transaction() as tx:
        before = tx.records()
    assert recovery.apply(packet)['replayed'] is True
    with workflow.store.transaction() as tx:
        assert tx.records() == before
    with pytest.raises(ContractError, match='Stale'):
        workflow.fail(lease, 'Actual failure API input')
    next_lease = workflow.claim('worker:implementation', 'recovered-process')
    assert next_lease['attempt'] == 2 and next_lease['generation'] == 3
    with pytest.raises(ContractError, match='Stale'):
        recovery.apply(packet)


def test_unknown_legacy_budget_is_explicitly_migrated_without_invented_history(workflow, recovery):
    task = workflow.submit(assignment())
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        row.update(attempt=2, generation=2, status='retry')
        tx.put('tasks', task['id'], row)
    assert workflow.claim('worker:implementation', 'upgrade') is None
    packet = prepare(recovery, task['id'], operation='migrate', max_attempts=3)
    result = recovery.apply(packet)['execution']
    assert result['attempt'] == 2 and 'attempt_outcomes' not in result
    assert result['retry_budget']['version'] == 1 and result['retry_budget']['origin'] == 'migrate'
    assert workflow.claim('worker:implementation', 'resumed')['attempt'] == 3


@pytest.mark.parametrize('state', ['running', 'succeeded', 'cancelled', 'superseded', 'queued', 'blocked'])
def test_recovery_cannot_change_unrelated_states(workflow, recovery, state):
    task, _ = exhausted(workflow)
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        row['status'] = state
        tx.put('tasks', task['id'], row)
        before = tx.records()
    with pytest.raises(ContractError):
        prepare(recovery, task['id'])
    with workflow.store.transaction() as tx:
        assert before == tx.records()


@pytest.mark.parametrize('changes', [{'max_attempts': True}, {'max_attempts': 1},
    {'max_attempts': float('inf')}, {'reason': ''}, {'operator': ''}, {'actor': 'worker:implementation'},
    {'deadline': '2026-01-01T00:00:00'}, {'deadline': '2000-01-01T00:00:00+00:00'}])
def test_invalid_recovery_proposal_is_read_only(workflow, recovery, changes):
    task, _ = exhausted(workflow)
    with workflow.store.transaction() as tx:
        before = tx.records()
    with pytest.raises(ContractError):
        prepare(recovery, task['id'], **changes)
    with workflow.store.transaction() as tx:
        assert before == tx.records()


def test_stale_snapshot_and_expired_packet_are_rejected(workflow, recovery):
    task, _ = exhausted(workflow)
    packet = prepare(recovery, task['id'])
    expired = deepcopy(packet)
    expired.update(issued_at='2000-01-01T00:00:00+00:00', expires_at='2000-01-01T00:01:00+00:00')
    with pytest.raises(ContractError, match='expired'):
        recovery.apply(expired)
    workflow.cancel(task['id'], 'conductor', 'Operator cancelled while reviewing')
    with pytest.raises(ContractError):
        recovery.apply(packet)
    with workflow.store.transaction() as tx:
        assert not tx.scan('execution_recoveries')


def test_expired_task_retains_original_message_and_uses_new_deadline(workflow, recovery):
    task, _ = exhausted(workflow)
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        row.update(status='expired', error='deadline exceeded', execution_deadline='2000-01-01T00:00:00+00:00')
        tx.put('tasks', task['id'], row)
    with pytest.raises(ContractError, match='cannot be removed'):
        prepare(recovery, task['id'])
    due = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    packet = prepare(recovery, task['id'], deadline=due)
    recovery.apply(packet)
    lease = workflow.claim('worker:implementation', 'new-deadline')
    assert lease['execution_deadline'] == due and lease['input_hash'] == digest(task['message'])


def test_missing_evidence_and_wrong_role_cannot_apply(workflow, recovery):
    task, _ = exhausted(workflow)
    packet = prepare(recovery, task['id'])
    with pytest.raises(ContractError):
        recovery.apply(packet, actor='worker:implementation')
    key = packet['evidence_refs'][0].split(':')[1]
    (recovery.artifacts.root / (key + '.txt')).unlink()
    with pytest.raises(ContractError, match='evidence unavailable'):
        recovery.apply(packet)
    with workflow.store.transaction() as tx:
        assert not tx.scan('execution_recoveries')


def test_recovery_state_and_receipt_rollback_together(workflow, recovery):
    task, _ = exhausted(workflow)
    packet = prepare(recovery, task['id'])
    original = recovery.store

    class FailedEventWrite:
        @contextmanager
        def transaction(self):
            with original.transaction() as tx:
                class Transaction:
                    def get(self, *args):
                        return tx.get(*args)

                    def put(self, bucket, key, body):
                        if bucket == 'events':
                            raise OSError('Injected last-write failure in real transaction')
                        tx.put(bucket, key, body)
                yield Transaction()

    with original.transaction() as tx:
        before = tx.records()
    recovery.store = FailedEventWrite()
    with pytest.raises(OSError):
        recovery.apply(packet)
    with original.transaction() as tx:
        assert tx.records() == before
    recovery.store = original
    assert recovery.apply(packet)['replayed'] is False


def test_decision_and_threshold_request_recovery_are_atomic_and_replay_bound(workflow, recovery):
    actor, request_id = 'conductor', 'test-threshold-request'
    decision_id = digest([request_id, actor])
    decision = {'id': decision_id, 'actor': actor, 'phase': 'threshold_review',
        'input': {'request_id': request_id}, 'status': 'failed', 'attempt': 2, 'generation': 2,
        'retry_budget': {'version': 1, 'max_attempts': 2}, 'error': 'attempt budget exhausted'}
    request = {'id': request_id, 'status': 'failed', 'failure': 'decision_attempt_budget_exhausted',
               'failed_decision': decision_id, 'reviews': ['prior-lead-review']}
    proposal = {'id': 'fixture-proposal'}
    ref = recovery.artifacts.put(canonical({'project_key': 'test-project', 'proposals': [proposal]}), 'unit-test')['ref']
    run_id = digest(['test-project', ref])
    record = {'id': digest([run_id, proposal['id']]), 'run_id': run_id, 'evidence_ref': ref,
              'proposal': proposal, 'project_key': 'test-project', 'status': 'calculated',
              'activation_ready': False, 'activation_blockers': ['native_task_success_and_release_review_required']}
    request.update(row_id=record['id'], binding=digest(record))
    with workflow.store.transaction() as tx:
        tx.put('threshold_proposals', record['id'], record)
        tx.put('threshold_proposal_runs', run_id, {'activation_ready': False, 'proposals': [record]})
        tx.put('decisions_pending', decision_id, decision)
        tx.put('threshold_review_requests', request_id, request)
    ref = recovery.artifacts.put('Threshold recovery evidence fixture', 'unit-test')['ref']
    packet = recovery.prepare('decisions_pending', decision_id, operation='resume', max_attempts=3,
        deadline=None, reason='Explicit additional attempt', operator='local-test', evidence_refs=[ref])
    assert recovery.apply(packet)['execution']['attempt'] == 2
    assert recovery.apply(packet)['replayed'] is True
    with workflow.store.transaction() as tx:
        recovery.validate_decision(tx, tx.get('decisions_pending', decision_id))
        row = tx.get('threshold_review_requests', request_id)
        assert row['status'] == 'awaiting_conductor' and row['reviews'] == request['reviews']
        receipt = tx.get('execution_recoveries', digest(packet))
        assert receipt['previous_related']['request'] == request
        row['reviews'].append('independent-lifecycle-change')
        tx.put('threshold_review_requests', request_id, row)
    with pytest.raises(ContractError, match='Stale'):
        recovery.apply(packet)


def test_real_pg_cli_prepare_apply_replay_and_process_restart(isolated_pgstore, tmp_path):
    workflow = Workflow(isolated_pgstore, organization())
    task, _ = exhausted(workflow)
    runtime = tmp_path / '복구 환경'
    ref = FileArtifacts(runtime / 'artifacts').put('Real CLI recovery test evidence; not human acceptance', 'test')['ref']
    packet = tmp_path / '복구 명령.json'
    env = dict(os.environ, ZEUS_DATABASE_URL=isolated_pgstore.dsn, HARNESS_DATABASE_URL=isolated_pgstore.dsn,
               ZEUS_RUNTIME_DIR=str(runtime), HARNESS_RUNTIME_DIR=str(runtime), PYTHONIOENCODING='utf-8')

    def run(args, expected=0):
        result = subprocess.run([sys.executable, '-m', 'zeus', 'execution-recovery', *args],
                                env=env, capture_output=True, timeout=30)
        assert result.returncode == expected, result.stderr.decode('utf-8')
        return json.loads(result.stdout)

    result = run(['prepare', task['id'], '--operation', 'resume', '--max-attempts', '2',
                  '--operator', 'isolated-process', '--reason', 'Verified recovery API',
                  '--evidence', ref, '--output', str(packet)])
    assert result['applied'] is False
    first = run(['apply', '--packet', str(packet)])
    replay = run(['apply', '--packet', str(packet)])
    assert not first['replayed'] and replay['replayed'] and first['execution'] == replay['execution']
    assert Workflow(isolated_pgstore, organization()).claim('worker:implementation', 'after-cli')['attempt'] == 2
    result = subprocess.run([sys.executable, '-m', 'zeus', 'execution-recovery', 'apply', '--packet', str(packet)],
                            env=env, capture_output=True, timeout=30)
    assert result.returncode != 0 and b'Stale' in result.stdout + result.stderr


def test_deadline_expired_before_first_claim_can_resume_with_explicit_first_budget(workflow, recovery):
    message = assignment()
    message['when']['deadline'] = '2000-01-01T00:00:00+00:00'
    task = workflow.submit(message)
    assert workflow.claim('worker:implementation', 'late-worker') is None
    packet = prepare(recovery, task['id'], max_attempts=1,
                     deadline=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    assert packet['previous']['status'] == 'expired' and 'retry_budget' not in packet['previous']
    recovery.apply(packet)
    lease = workflow.claim('worker:implementation', 'resumed')
    assert lease['attempt'] == 1 and lease['input_hash'] == digest(message)


@pytest.mark.parametrize('error,budget', [('InvalidRetryBudget', []),
    ('InvalidRetryBudget', {'version': 'invalid'}), ('InvalidExecutionDeadline', {'version': 2, 'max_attempts': 4})])
def test_explicit_repair_preserves_corrupt_source_and_does_not_reset_attempts(workflow, recovery, error, budget):
    task, _ = exhausted(workflow)
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        row.update(status='blocked', error=error, retry_budget=budget)
        tx.put('tasks', task['id'], row)
    packet = prepare(recovery, task['id'], operation='repair')
    result = recovery.apply(packet)
    assert result['execution']['attempt'] == 1 and result['execution']['retry_budget']['origin'] == 'repair'
    with workflow.store.transaction() as tx:
        receipt = tx.get('execution_recoveries', result['receipt_id'])
        assert receipt['previous']['retry_budget'] == budget and receipt['previous']['error'] == error


def test_unhandled_decision_phase_is_explicitly_rejected(workflow, recovery):
    with workflow.store.transaction() as tx:
        tx.put('decisions_pending', 'decision', {'id': 'decision', 'phase': 'unknown_phase',
            'actor': 'conductor', 'input': {}, 'attempt': 1, 'generation': 1, 'status': 'failed',
            'error': 'attempt budget exhausted', 'retry_budget': {'version': 1, 'max_attempts': 1}})
    ref = recovery.artifacts.put('Evidence fixture', 'test')['ref']
    with pytest.raises(ContractError, match='coupling handler'):
        recovery.prepare('decisions_pending', 'decision', operation='resume', max_attempts=2,
                         deadline=None, reason='Explicit recovery', evidence_refs=[ref], operator='test')


@pytest.mark.parametrize('field', ['deadline', 'retry_budget'])
def test_corruption_claim_block_repair_and_claim_again(workflow, recovery, field):
    task = workflow.submit(assignment())
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        if field == 'deadline':
            row['message']['when']['deadline'] = 'not-a-time'
        else:
            row['retry_budget'] = []
        tx.put('tasks', task['id'], row)
    assert workflow.claim('worker:implementation', 'detect-corruption') is None
    packet = prepare(recovery, task['id'], operation='repair', max_attempts=1,
                     deadline=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    recovery.apply(packet)
    lease = workflow.claim('worker:implementation', 'after-repair')
    assert lease['attempt'] == 1 and lease['id'] == task['id']
    assert lease['message'] == packet['previous']['message']


@pytest.mark.parametrize('change', [{'id': 'other-task'}, {'message': {}},
    {'unknown': float('nan')}, {'unknown': 'x' * (1024 * 1024)}])
def test_prepare_rejects_invalid_or_unexportable_snapshot(workflow, recovery, change):
    if isinstance(change.get('unknown'), float) and not isinstance(workflow.store, MemoryStore):
        pytest.skip('PostgreSQL JSONB rejects NaN before an application snapshot exists')
    task, _ = exhausted(workflow)
    with workflow.store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        tx.put('tasks', task['id'], {**row, **change})
    with pytest.raises(ContractError):
        prepare(recovery, task['id'])
