import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_workflow import assignment

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.audit_gate import binding
from codex_harness.application.decision_recovery import release_review_policy
from codex_harness.application.execution_recovery import ExecutionRecovery
from codex_harness.application.releases import Releases
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, digest, envelope


@pytest.fixture(params=['memory', 'postgres'])
def system(request, tmp_path):
    store = MemoryStore() if request.param == 'memory' else request.getfixturevalue('isolated_pgstore')
    service = Harness(store, organization())
    executor = Executor(service, SimpleNamespace(repository=tmp_path), FileArtifacts(tmp_path / 'artifacts'))
    return executor, ExecutionRecovery(store, service.org, executor.artifacts)


def exhaust(executor, decision_id):
    with executor.service.store.transaction() as tx:
        row = tx.get('decisions_pending', decision_id)
        row.update(status='failed', error='attempt budget exhausted', attempt=1, generation=1,
                   retry_budget={'version': 1, 'max_attempts': 1})
        tx.put('decisions_pending', decision_id, row)
    return row


def resume(recovery, row, operation='resume'):
    ref = recovery.artifacts.put('Explicit isolated test recovery rationale', 'test')['ref']
    packet = recovery.prepare('decisions_pending', row['id'], operation=operation, max_attempts=2,
        deadline=None, reason='Additional reviewed attempt', operator='isolated-test', evidence_refs=[ref])
    return recovery.apply(packet)['execution']


def lease(executor, row):
    from codex_harness.application.execution_fence import advance as advance_fence
    with executor.service.store.transaction() as tx:
        current = tx.get('decisions_pending', row['id'])
        # A fixture claim advances the durable fence exactly as Executor.decide_one does.
        advance_fence(tx, 'decisions_pending', row['id'], current['generation'] + 1, 'fixture-owner')
        current.update(status='running', attempt=current['attempt'] + 1, generation=current['generation'] + 1,
                       lease_owner='fixture-owner', lease_until=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
        tx.put('decisions_pending', row['id'], current)
    return {**current, '_bucket': 'decisions_pending'}


def review_decision(executor, phase, policy=None):
    workflow = executor.workflow
    candidate = {'revision': 'a' * 40, 'base': 'b' * 40, 'tree': 'c' * 40, 'author': 'worker:implementation'}
    if phase == 'review_lead':
        task = workflow.submit(assignment())
        claimed = workflow.claim('worker:implementation', 'source')
        workflow.complete(claimed, {'candidate': candidate})
        with workflow.store.transaction() as tx:
            message = next(r['message'] for r in tx.scan('outbox') if r['message']['what']['details'].get('task_id') == task['id'])
    else:
        release = Releases(workflow.store, workflow.org).propose(candidate, policy or release_review_policy(candidate))
        Releases(workflow.store, workflow.org).review(release['id'], 'lead:improvement', candidate['revision'], True, 'fixture-lead-evidence')
        result = {'candidate': candidate, 'release_id': release['id']}
        message = envelope('review.result', 'lead:improvement', 'conductor', 'review',
                           {'decision_id': 'source-lead', 'result': result}, 'review-loop')
        with workflow.store.transaction() as tx:
            tx.put('decisions_pending', 'source-lead', {'id': 'source-lead', 'actor': 'lead:improvement',
                   'status': 'succeeded', 'result': result})
    workflow.handle(message)
    return exhaust(executor, message['message_id'])


@pytest.mark.parametrize('phase', ['review_lead', 'review_conductor'])
def test_review_recovery_commits_once_and_does_not_reject_its_own_effects(system, phase):
    executor, recovery = system
    row = resume(recovery, review_decision(executor, phase))
    current = lease(executor, row)
    result = {'accepted': True, 'reason': 'Fixture verdict; not live model acceptance', 'execution_ref': 'fixture-execution'}
    committed = executor._commit_decision(current, current['actor'], phase, current['input'], result, current)
    assert committed['status'] == 'succeeded'
    with executor.service.store.transaction() as tx:
        releases = tx.scan('releases')
        assert len(releases) == 1
        assert len([r for r in releases[0]['reviews'] if r['actor'] == row['actor']]) == 1
    with pytest.raises(ContractError, match='Stale or expired task execution'):
        executor._commit_decision(current, current['actor'], phase, current['input'], result, current)


@pytest.mark.parametrize('phase', ['review_lead', 'review_conductor'])
@pytest.mark.parametrize('when', ['before_claim', 'before_commit'])
def test_changed_loop_blocks_recovered_review_without_release_effects(system, phase, when):
    executor, recovery = system
    row = resume(recovery, review_decision(executor, phase))
    current = lease(executor, row) if when == 'before_commit' else None
    with executor.service.store.transaction() as tx:
        tx.put('improvement_loops', row['message']['correlation_id'], {'status': 'stagnated'})
        before = tx.scan('releases')
    if when == 'before_claim':
        assert executor.decide_one(row['actor']) is None
    else:
        with pytest.raises(ContractError):
            executor._commit_decision(current, row['actor'], phase, row['input'],
                {'accepted': True, 'execution_ref': 'fixture', 'reason': 'fixture'}, current)
    with executor.service.store.transaction() as tx:
        assert tx.scan('releases') == before and not tx.scan('release_queue')
        if when == 'before_claim':
            blocked = tx.get('decisions_pending', row['id'])
            assert blocked['attempt'] == 1 and blocked['error'] == 'RecoveryContextChanged'


def test_historical_diagnosis_survives_source_retry_but_not_recorded_occurrence(system):
    executor, recovery = system
    executor.workflow.submit(assignment())
    task = executor.workflow.claim('worker:implementation', 'original')
    executor._fail_task(task, 'worker:implementation', ValueError('Observed parse failure fixture'))
    with executor.service.store.transaction() as tx:
        decision = tx.scan('decisions_pending')[0]
    row = resume(recovery, exhaust(executor, decision['id']))
    executor.workflow.claim('worker:implementation', 'later-source-attempt')
    with executor.service.store.transaction() as tx:
        recovery.validate_decision(tx, row)
        tx.put('incidents', row['input']['occurrence_id'], {'already': 'recorded'})
    assert executor.decide_one(row['actor']) is None
    with executor.service.store.transaction() as tx:
        assert tx.get('decisions_pending', row['id'])['attempt'] == 1


def test_audit_binding_checks_active_evaluator_and_prior_reviews(system):
    executor, recovery = system
    proposal = {'author': 'worker:research'}
    with executor.service.store.transaction() as tx:
        tx.put('research_audits', 'audit', {'id': 'audit', 'fixture': 'not a complete source audit'})
        tx.put('deployment', 'active', {'release_id': 'active', 'revision': 'a' * 40})
        tx.put('releases', 'active', {'status': 'active', 'policy_hash': 'incumbent-policy'})
        bound = binding(tx, 'audit', proposal)
        key = digest({'binding': bound, 'actor': 'lead:research'})
        tx.put('decisions_pending', key, {'id': key, 'phase': 'audit_review', 'actor': 'lead:research',
            'input': {'audit_id': 'audit', 'proposal': proposal, 'binding': bound}})
    row = resume(recovery, exhaust(executor, key))
    with executor.service.store.transaction() as tx:
        recovery.validate_decision(tx, row)
        # A new inspection unrelated to audited path receipts does not alter the binding.
        tx.put('research_receipts', 'new-inspection', {'audit_id': 'audit'})
        recovery.validate_decision(tx, row)
        tx.put('research_control', 'graph', {'revision': 'changed'})
    assert executor.decide_one(row['actor']) is None
    with executor.service.store.transaction() as tx:
        assert not tx.scan('research_reviews') and tx.get('decisions_pending', key)['attempt'] == 1


@pytest.mark.parametrize('phase', ['research_lead', 'proposal'])
def test_recovery_never_unlocks_deferred_legacy_research(system, phase):
    executor, recovery = system
    with executor.service.store.transaction() as tx:
        tx.put('decisions_pending', 'legacy', {'id': 'legacy', 'phase': phase, 'actor': 'conductor', 'input': {}})
    with pytest.raises(ContractError, match='Research adoption deferred'):
        resume(recovery, exhaust(executor, 'legacy'))


def test_recovery_receipt_corruption_cannot_abort_the_claim_loop(system):
    executor, recovery = system
    row = resume(recovery, review_decision(executor, 'review_lead'))
    with executor.service.store.transaction() as tx:
        tx.put('execution_recoveries', row['recovery_receipt'], {'packet': None})
    assert executor.decide_one(row['actor']) is None


def test_recovered_review_cannot_commit_a_different_candidate(system):
    executor, recovery = system
    row = resume(recovery, review_decision(executor, 'review_lead'))
    current = lease(executor, row)
    data = {**row['input'], 'candidate': {**row['input']['candidate'], 'revision': 'd' * 40}}
    with pytest.raises(ContractError, match='effect input changed'):
        executor._commit_decision(current, row['actor'], row['phase'], data,
            {'accepted': True, 'reason': 'fixture', 'execution_ref': 'fixture'}, current)
    with executor.service.store.transaction() as tx:
        assert not tx.scan('releases')


def test_missing_recovery_pointer_does_not_bypass_context_validation(system):
    executor, recovery = system
    row = resume(recovery, review_decision(executor, 'review_lead'))
    with executor.service.store.transaction() as tx:
        current = tx.get('decisions_pending', row['id'])
        current.pop('recovery_receipt')
        tx.put('decisions_pending', row['id'], current)
    assert executor.decide_one(row['actor']) is None
    with executor.service.store.transaction() as tx:
        assert tx.get('decisions_pending', row['id'])['error'] == 'RecoveryContextChanged'


def test_conductor_recovery_preserves_original_release_policy(system):
    executor, recovery = system
    policy = {'checks': ['tests', 'custom-incumbent-check'], 'revision': 'b' * 40, 'version': 'custom-v2'}
    row = resume(recovery, review_decision(executor, 'review_conductor', policy))
    with executor.service.store.transaction() as tx:
        recovery.validate_decision(tx, row)
        assert tx.get('releases', row['input']['release_id'])['policy'] == policy


def test_unrelated_source_and_release_annotations_do_not_invalidate_recovery(system):
    executor, recovery = system
    row = resume(recovery, review_decision(executor, 'review_conductor'))
    with executor.service.store.transaction() as tx:
        source = tx.get('decisions_pending', 'source-lead')
        source['archive_note'] = 'Unrelated annotation'
        tx.put('decisions_pending', 'source-lead', source)
        release = tx.get('releases', row['input']['release_id'])
        release['archive_note'] = 'Unrelated annotation'
        tx.put('releases', release['id'], release)
        recovery.validate_decision(tx, row)


def test_release_already_queued_blocks_recovery_before_attempt(system):
    executor, recovery = system
    row = resume(recovery, review_decision(executor, 'review_conductor'))
    with executor.service.store.transaction() as tx:
        tx.put('release_queue', row['input']['release_id'], {'status': 'queued'})
    assert executor.decide_one(row['actor']) is None
    with executor.service.store.transaction() as tx:
        assert tx.get('decisions_pending', row['id'])['attempt'] == 1


def test_real_cli_recovery_then_new_process_rejects_changed_review_context(isolated_pgstore, tmp_path):
    service = Harness(isolated_pgstore, organization())
    runtime = tmp_path / '의사결정 복구'
    artifacts = FileArtifacts(runtime / 'artifacts')
    executor = Executor(service, SimpleNamespace(repository=tmp_path), artifacts)
    row = review_decision(executor, 'review_conductor')
    ref = artifacts.put('Real process recovery test rationale, not human approval', 'test')['ref']
    packet = tmp_path / 'review recovery.json'
    env = dict(os.environ, ZEUS_DATABASE_URL=isolated_pgstore.dsn, HARNESS_DATABASE_URL=isolated_pgstore.dsn,
               ZEUS_RUNTIME_DIR=str(runtime), HARNESS_RUNTIME_DIR=str(runtime), PYTHONIOENCODING='utf-8')
    prepare = ['prepare', row['id'], '--bucket', 'decisions_pending', '--operation', 'resume',
               '--max-attempts', '2', '--reason', 'Additional review', '--operator', 'isolated-process',
               '--evidence', ref, '--output', str(packet)]
    for args in (prepare, ['apply', '--packet', str(packet)]):
        result = subprocess.run([sys.executable, '-m', 'zeus', 'execution-recovery', *args],
                                env=env, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr.decode('utf-8')
    with isolated_pgstore.transaction() as tx:
        tx.put('release_queue', row['input']['release_id'], {'status': 'queued'})
    child = '''
import json,sys
from types import SimpleNamespace
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.configuration import runtime_dir
from codex_harness.bootstrap import build
e=Executor(build(),SimpleNamespace(repository=sys.argv[1]),FileArtifacts(runtime_dir()/'artifacts'))
print(json.dumps(e.decide_one('conductor')))
'''
    result = subprocess.run([sys.executable, '-c', child, str(tmp_path)], env=env, capture_output=True, timeout=30)
    assert result.returncode == 0 and json.loads(result.stdout) is None
    with isolated_pgstore.transaction() as tx:
        current = tx.get('decisions_pending', row['id'])
        assert current['attempt'] == 1 and current['status'] == 'blocked' and current['error'] == 'RecoveryContextChanged'
        assert not tx.scan('execution_failures')


def test_context_drift_can_be_explicitly_recovered_when_native_state_remains_eligible(system):
    executor, recovery = system
    row = resume(recovery, review_decision(executor, 'review_lead'))
    with executor.service.store.transaction() as tx:
        tx.put('improvement_loops', row['message']['correlation_id'],
               {'status': 'reworking', 'reworks': 1, 'rejected_trees': ['different-tree']})
    assert executor.decide_one(row['actor']) is None
    repaired = resume(recovery, row, operation='repair')
    assert repaired['recovery_sequence'] == 2 and repaired['attempt'] == 1
    with executor.service.store.transaction() as tx:
        recovery.validate_decision(tx, repaired)


def test_repair_cannot_reopen_an_already_queued_release(system):
    executor, recovery = system
    row = resume(recovery, review_decision(executor, 'review_conductor'))
    with executor.service.store.transaction() as tx:
        tx.put('release_queue', row['input']['release_id'], {'status': 'queued'})
    assert executor.decide_one(row['actor']) is None
    with pytest.raises(ContractError, match='already queued'):
        resume(recovery, row, operation='repair')
