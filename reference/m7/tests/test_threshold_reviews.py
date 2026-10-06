import pytest
from test_threshold_collection import events
from test_threshold_collection import policy_repo as source_policy_repo

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.store import MemoryStore
from codex_harness.adapters.threshold_policy import current_policy
from codex_harness.application.service import Harness
from codex_harness.application.threshold_proposals import ThresholdProposals
from codex_harness.application.threshold_reviews import ThresholdReviews
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, canonical, digest


@pytest.fixture
def policy_repo(tmp_path):
    return source_policy_repo.__wrapped__(tmp_path)


def setup_review(policy_repo, tmp_path):
    _, git = policy_repo
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    with store.transaction() as tx:
        tx.put('skill_history', 'project', {'events': events()})
    run = ThresholdProposals(store, artifacts, lambda: current_policy(git)).collect('project')
    executor = Executor(Harness(store, organization()), git, artifacts)
    reviews = ThresholdReviews(executor.workflow, artifacts)
    request = reviews.request(run['proposals'][0]['id'])
    assert reviews.request(run['proposals'][0]['id']) == request
    return executor, reviews, request


def runtime(executor, calls, *, accepted=True, blocked=False, wrong_actor=False, intervene=None,
            inspection_blocked=False, interrupted=False, spoof_blockage=False):
    def run(actor, key, objective, evidence, cwd, schema, read_only, **kwargs):
        assert read_only and kwargs['stage'] == 'threshold_review'
        calls.append((actor, evidence))
        answer = {'accepted': accepted, 'reason': 'fixture assessment', 'blocked': blocked,
                  'risks': [], 'sre_assessment': 'fixture', 'arc42_assessment': 'fixture'}
        source = executor.artifacts.put(canonical(evidence), 'fixture-input')
        packet = executor.artifacts.put(canonical({'agent_id': 'wrong' if wrong_actor else actor,
            'task_id': key, 'required': {'external_context': {'ref': source['ref']}}}), 'fixture-context')
        revision = executor.git._git('rev-parse', 'HEAD', cwd=cwd)
        receipt = executor.artifacts.put(canonical({'answer': answer, 'context_ref': packet['ref'],
            'inspection_blocked': inspection_blocked, 'interrupted': interrupted,
            'research_binding': {'stage': 'threshold_review', 'evidence_ref': 'sha256:' + digest(evidence),
                                 'basis_revision': revision}}), 'fixture-execution')
        if intervene:
            intervene(kwargs['lease'])
        result = {**answer, 'execution_ref': receipt['ref'], 'basis_revision': revision}
        if inspection_blocked or spoof_blockage:
            result.update(accepted=False, inspection_blocked=True)
        return result
    return run


def test_executor_orders_independent_assessments_without_dispatch_or_activation(policy_repo, tmp_path, monkeypatch):
    executor, _, request = setup_review(policy_repo, tmp_path)
    calls = []
    monkeypatch.setattr(executor, '_run', runtime(executor, calls))
    assert executor.decide_one('conductor') is None
    assert executor.decide_one('lead:improvement')['status'] == 'succeeded'
    assert executor.decide_one('conductor')['status'] == 'succeeded'
    assert [actor for actor, _ in calls] == ['lead:improvement', 'conductor']
    assert calls[1][1]['review']['prior_reviews'][0]['actor'] == 'lead:improvement'
    with executor.service.store.transaction() as tx:
        finished = tx.get('threshold_review_requests', request['id'])
        assert finished['status'] == 'assessed' and not finished['activation_ready']
        assert len(finished['reviews']) == 2
        assert not tx.scan('outbox') and not tx.scan('releases') and not tx.scan('deployment')
    assert executor.decide_one('conductor') is None


@pytest.mark.parametrize('blocked', [False, True])
def test_rejection_or_blockage_cannot_queue_conductor(policy_repo, tmp_path, monkeypatch, blocked):
    executor, _, request = setup_review(policy_repo, tmp_path)
    monkeypatch.setattr(executor, '_run', runtime(executor, [], accepted=False, blocked=blocked))
    executor.decide_one('lead:improvement')
    assert executor.decide_one('conductor') is None
    with executor.service.store.transaction() as tx:
        assert tx.get('threshold_review_requests', request['id'])['status'] == ('blocked' if blocked else 'rejected')


def test_wrong_receipt_identity_cannot_complete_review(policy_repo, tmp_path, monkeypatch):
    executor, _, request = setup_review(policy_repo, tmp_path)
    monkeypatch.setattr(executor, '_run', runtime(executor, [], wrong_actor=True))
    assert executor.decide_one('lead:improvement')['status'] == 'retry'
    with executor.service.store.transaction() as tx:
        assert tx.get('threshold_review_requests', request['id'])['reviews'] == []


@pytest.mark.parametrize('change', ['lease', 'record', 'policy'])
def test_changed_basis_or_lease_during_execution_cannot_commit(policy_repo, tmp_path, monkeypatch, change):
    executor, _, request = setup_review(policy_repo, tmp_path)
    def intervene(lease):
        if change == 'policy':
            root = executor.git.repository
            (root / 'changed.txt').write_text('new revision')
            executor.git._git('add', '.')
            executor.git._git('commit', '-qm', 'advance basis')
        else:
            with executor.service.store.transaction() as tx:
                if change == 'lease':
                    row = tx.get('decisions_pending', lease['id'])
                    row.update(owner='other', lease_owner='other', generation=row['generation'] + 1)
                    tx.put('decisions_pending', row['id'], row)
                else:
                    row = tx.get('threshold_proposals', request['row_id'])
                    row['activation_blockers'].append('changed')
                    tx.put('threshold_proposals', row['id'], row)
    monkeypatch.setattr(executor, '_run', runtime(executor, [], intervene=intervene))
    assert executor.decide_one('lead:improvement')['status'] == ('stale' if change == 'lease' else 'retry')
    with executor.service.store.transaction() as tx:
        assert tx.get('threshold_review_requests', request['id'])['reviews'] == []
        assert not any(row['actor'] == 'conductor' for row in tx.scan('decisions_pending'))


@pytest.mark.parametrize('options,status', [({'inspection_blocked': True}, 'blocked'),
    ({'inspection_blocked': True, 'interrupted': True}, 'blocked'),
    ({'interrupted': True}, 'retry'), ({'spoof_blockage': True}, 'retry')])
def test_execution_blockage_and_interruption_are_taken_from_receipt(policy_repo, tmp_path, monkeypatch, options, status):
    executor, _, request = setup_review(policy_repo, tmp_path)
    monkeypatch.setattr(executor, '_run', runtime(executor, [], **options))
    assert executor.decide_one('lead:improvement')['status'] == status
    assert executor.decide_one('conductor') is None
    with executor.service.store.transaction() as tx:
        state = tx.get('threshold_review_requests', request['id'])
        assert state['status'] == ('blocked' if status == 'blocked' else 'awaiting_lead')
        assert not state['activation_ready']


def test_conductor_rejection_and_terminal_request_idempotence(policy_repo, tmp_path, monkeypatch):
    executor, reviews, request = setup_review(policy_repo, tmp_path)
    monkeypatch.setattr(executor, '_run', runtime(executor, []))
    executor.decide_one('lead:improvement')
    monkeypatch.setattr(executor, '_run', runtime(executor, [], accepted=False))
    executor.decide_one('conductor')
    terminal = reviews.request(request['row_id'])
    assert terminal['status'] == 'rejected' and len(terminal['reviews']) == 2
    assert executor.decide_one('lead:improvement') is None


def test_attempt_exhaustion_is_visible_on_request(policy_repo, tmp_path):
    from codex_harness.domain.policy import POLICY

    executor, reviews, request = setup_review(policy_repo, tmp_path)
    with executor.service.store.transaction() as tx:
        decision, = tx.scan('decisions_pending')
        # Model an already-pinned budget; unknown legacy budgets require recovery.
        decision['retry_budget'] = {'max_attempts': POLICY.max_attempts, 'version': 1}
        decision['attempt'] = POLICY.max_attempts
        tx.put('decisions_pending', decision['id'], decision)
    assert executor.decide_one('lead:improvement') is None
    failed = reviews.request(request['row_id'])
    assert failed['status'] == 'failed' and failed['failure'] == 'decision_attempt_budget_exhausted'


def test_receipt_from_previous_generation_is_not_reused(policy_repo, tmp_path, monkeypatch):
    executor, _, request = setup_review(policy_repo, tmp_path)
    cached = []
    def lose_lease(lease):
        with executor.service.store.transaction() as tx:
            current = tx.get('decisions_pending', lease['id'])
            current.update(status='retry', owner='replacement', lease_owner='replacement',
                           generation=current['generation'] + 1)
            tx.put('decisions_pending', current['id'], current)
    original = runtime(executor, [], intervene=lose_lease)
    def run(*args, **kwargs):
        if not cached:
            cached.append(original(*args, **kwargs))
        return cached[0]
    monkeypatch.setattr(executor, '_run', run)
    assert executor.decide_one('lead:improvement')['status'] == 'stale'
    assert executor.decide_one('lead:improvement')['status'] == 'retry'
    with executor.service.store.transaction() as tx:
        assert tx.get('threshold_review_requests', request['id'])['reviews'] == []


@pytest.mark.parametrize('override', [{'actor': 'conductor'}, {'_bucket': 'tasks'}])
def test_caller_cannot_change_lease_actor_or_aggregate(policy_repo, tmp_path, monkeypatch, override):
    executor, reviews, _ = setup_review(policy_repo, tmp_path)
    original = runtime(executor, [])
    def run(*args, **kwargs):
        with pytest.raises(ContractError):
            reviews.prepare({**kwargs['lease'], **override})
        return original(*args, **kwargs)
    monkeypatch.setattr(executor, '_run', run)
    assert executor.decide_one('lead:improvement')['status'] == 'succeeded'


def test_empty_execution_answer_cannot_satisfy_assessment(policy_repo, tmp_path, monkeypatch):
    executor, _, request = setup_review(policy_repo, tmp_path)
    original = runtime(executor, [])
    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        receipt = executor.artifacts.document(result['execution_ref'])
        receipt['answer'] = {}
        result['execution_ref'] = executor.artifacts.put(canonical(receipt), 'empty-fixture-answer')['ref']
        return result
    monkeypatch.setattr(executor, '_run', run)
    assert executor.decide_one('lead:improvement')['status'] == 'retry'
    with executor.service.store.transaction() as tx:
        assert tx.get('threshold_review_requests', request['id'])['reviews'] == []


def test_collection_run_membership_is_required(policy_repo, tmp_path):
    executor, reviews, request = setup_review(policy_repo, tmp_path)
    with executor.service.store.transaction() as tx:
        row = tx.get('threshold_proposals', request['row_id'])
        run = tx.get('threshold_proposal_runs', row['run_id'])
        run['proposals'] = []
        tx.put('threshold_proposal_runs', run['id'], run)
    with pytest.raises(ContractError, match='collection run'):
        reviews.request(request['row_id'])


def test_post_commit_error_does_not_rewrite_success(policy_repo, tmp_path, monkeypatch):
    executor, reviews, request = setup_review(policy_repo, tmp_path)
    monkeypatch.setattr(executor, '_run', runtime(executor, []))
    original = ThresholdReviews.complete
    def complete(self, *args):
        original(self, *args)
        raise OSError('lost commit acknowledgement')
    monkeypatch.setattr(ThresholdReviews, 'complete', complete)
    executor.decide_one('lead:improvement')
    with executor.service.store.transaction() as tx:
        lead = tx.get('decisions_pending', digest([request['id'], 'lead:improvement']))
        assert lead['status'] == 'succeeded'
        # A stale exhausted lead must not fail the conductor's pending stage.
        reviews.exhausted(tx, lead)
        assert tx.get('threshold_review_requests', request['id'])['status'] == 'awaiting_conductor'


def test_dirty_attempt_does_not_poison_retry_workspace(policy_repo, tmp_path, monkeypatch):
    from pathlib import Path

    executor, _, request = setup_review(policy_repo, tmp_path)
    original = runtime(executor, [])
    paths = []
    def run(*args, **kwargs):
        paths.append(args[4])
        result = original(*args, **kwargs)
        if len(paths) == 1:
            (Path(args[4]) / 'leftover.txt').write_text('failed attempt')
        return result
    monkeypatch.setattr(executor, '_run', run)
    assert executor.decide_one('lead:improvement')['status'] == 'retry'
    assert executor.decide_one('lead:improvement')['status'] == 'succeeded'
    assert paths[0] != paths[1]
    assert (Path(paths[0]) / 'leftover.txt').exists()
    with executor.service.store.transaction() as tx:
        assert tx.get('threshold_review_requests', request['id'])['status'] == 'awaiting_conductor'
