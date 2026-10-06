"""FA-021: calibration evaluates unique executions and an approval certifies one exact change once
(INV-THRESHOLD-APPROVAL-001).

The upstream calibration applied 999 with a flag that said 4, kept proposing from the default
after 999 was effective, read NaN back as policy, scored a value that admitted nothing as
precision 1 and accepted it, and counted unclassified failures as success.
"""
import copy
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from test_threshold_collection import policy_repo as source_policy_repo  # noqa: F401
from test_threshold_reviews import policy_repo, runtime, setup_review  # noqa: F401

from codex_harness.application.threshold_approvals import (
    BUCKET,
    EVENTS,
    ThresholdApprovals,
    parse_applied_policy,
)
from codex_harness.domain.model import ContractError
from codex_harness.domain.threshold_proposals import propose_threshold_changes, unique_events
from codex_harness.domain.threshold_replay import admitted_entries, evaluate_threshold_change

NAME = 'skill_match.FULL_BODY_MIN_SCORE'
T0 = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def corpus(scores=(3, 5), count=40, identified=False):
    return [{**({'id': f'obs-{i}'} if identified else {}), 'at': f'2026-01-01T00:00:{i:02d}Z',
             'top': [{'score': s, 'body_chars': 500} for s in scores]} for i in range(count)]


def propose(events, current=3):
    return propose_threshold_changes(events_by_source={'skill-match': events}, current_values={NAME: current},
                                     policy_revision='a' * 40)


def test_duplicates_audit_rows_and_unscored_events_are_not_additional_executions():
    base = corpus(identified=True)
    duplicated = base + copy.deepcopy(base[:15]) + [{'id': 'obs-0', 'at': base[0]['at'], 'top': [{'score': 9}]}]
    unique, counts = unique_events(duplicated)
    assert len(unique) == 40 and counts == {'events': 56, 'invalid': 0, 'unidentified': 0, 'duplicates': 16,
                                            'unscored': 0, 'unique': 40}
    assert unique[0]['top'][0]['score'] == 3, 'the first observation of an id is the record; a re-collection is not'
    proposal, = propose(duplicated)
    assert proposal['sample_size'] == 40 and proposal['denominator'] == counts
    assert proposal['evaluation_scope']['first_at'] == '2026-01-01T00:00:00+00:00'
    assert proposal['evaluation_scope']['last_at'] == '2026-01-01T00:00:39+00:00'
    assert proposal['evaluation_scope']['policy_revision'] == 'a' * 40
    assert proposal['unique_corpus_hash'] != proposal['corpus_hash']
    assert propose(base)[0]['unique_corpus_hash'] == proposal['unique_corpus_hash']
    unscored = corpus() + [{'at': '2026-01-01T00:01:00Z', 'top': [{'path': 'x'}]}, 'audit-row', None]
    unique, counts = unique_events(unscored)
    assert (counts['invalid'], counts['unscored'], counts['unidentified'], counts['unique']) == (2, 1, 41, 41)


def test_a_value_that_admits_nothing_is_never_an_improvement():
    everything_at_three = corpus(scores=(3,))
    assert admitted_entries(everything_at_three, 4) == 0
    gate = evaluate_threshold_change(events=everything_at_three, old_value=3, proposed_value=4,
                                     holdout_boundary='2026-01-01T00:00:28Z')
    assert not gate.accept and gate.reason == 'empty_admission'
    proposal, = propose(everything_at_three)
    raise_candidate = next(c for c in proposal['alternatives'] if c['value'] == 4)
    assert raise_candidate['report']['gate']['reason'] == 'empty_admission'
    assert proposal['suggested'] != 4, 'the vacuous precision of 1.0 cannot be the chosen change'
    for partition in proposal['report']['partitions'].values():
        assert partition['proposed_admitted_entries'] > 0


def assessed(policy_repo, tmp_path, monkeypatch):  # noqa: F811
    executor, reviews, request = setup_review(policy_repo, tmp_path)
    monkeypatch.setattr(executor, '_run', runtime(executor, []))
    assert executor.decide_one('lead:improvement')['status'] == 'succeeded'
    assert executor.decide_one('conductor')['status'] == 'succeeded'
    with executor.service.store.transaction() as tx:
        request = tx.get('threshold_review_requests', request['id'])
        proposal = tx.get('threshold_proposals', request['row_id'])['proposal']
    assert request['status'] == 'assessed'
    return executor, request, proposal


def change(proposal, **over):
    document = {'previous_revision': proposal['policy_revision'], 'previous_values': {NAME: proposal['current']},
                'revision': 'c' * 40, 'values': {NAME: proposal['suggested']}, 'environment': 'staging'}
    document.update(over)
    return document


def test_issue_binds_the_exact_assessed_change(policy_repo, tmp_path, monkeypatch):  # noqa: F811
    executor, _, _ = setup_review(policy_repo, tmp_path)[0], None, None
    approvals = ThresholdApprovals(executor.service.store, executor.artifacts)
    with executor.service.store.transaction() as tx:
        pending = tx.scan('threshold_review_requests')[0]
    with pytest.raises(ContractError, match='Assessed threshold review required'):
        approvals.issue(pending['id'], actor='conductor', environment='staging', ttl_seconds=3600)
    executor, request, proposal = assessed(policy_repo, tmp_path, monkeypatch)
    approvals = ThresholdApprovals(executor.service.store, executor.artifacts)
    with pytest.raises(ContractError, match='Only the conductor issues'):
        approvals.issue(request['id'], actor='lead:improvement', environment='staging', ttl_seconds=3600)
    for bad in ({'environment': 'Staging'}, {'ttl_seconds': 0}, {'ttl_seconds': 31 * 24 * 3600}, {'ttl_seconds': True}):
        with pytest.raises(ContractError):
            approvals.issue(request['id'], **{'actor': 'conductor', 'environment': 'staging', 'ttl_seconds': 3600, **bad})
    approval = approvals.issue(request['id'], actor='conductor', environment='staging', ttl_seconds=3600, now=T0)
    assert approval['status'] == 'issued' and approval['name'] == NAME
    assert (approval['current'], approval['proposed']) == (proposal['current'], proposal['suggested']) == (3, 4)
    assert approval['policy_revision'] == proposal['policy_revision'] and approval['corpus_hash'] == proposal['corpus_hash']
    assert [r['actor'] for r in approval['reviews']] == ['lead:improvement', 'conductor']
    assert approval['expires_at'] == (T0 + timedelta(seconds=3600)).isoformat() and approval['request_binding'] == request['binding']
    assert approvals.issue(request['id'], actor='conductor', environment='staging', ttl_seconds=60, now=T0) == approval
    assert approvals.issue(request['id'], actor='conductor', environment='prod', ttl_seconds=60, now=T0)['id'] != approval['id']
    assert approvals.inspect(approval['id'], now=T0)['state'] == 'issued'


def test_consume_certifies_exactly_one_matching_change(policy_repo, tmp_path, monkeypatch):  # noqa: F811
    executor, request, proposal = assessed(policy_repo, tmp_path, monkeypatch)
    approvals = ThresholdApprovals(executor.service.store, executor.artifacts)
    approval = approvals.issue(request['id'], actor='conductor', environment='staging', ttl_seconds=3600, now=T0)
    refused = [
        (change(proposal, values={NAME: 999}), 'applied value differs'),
        (change(proposal, values={NAME: 4.0}), 'type differs'),
        (change(proposal, previous_values={NAME: 2}), 'previous value differs'),
        (change(proposal, previous_revision='d' * 40), 'previous policy revision differs'),
        (change(proposal, environment='prod'), 'environment differs'),
        (change(proposal, revision=proposal['policy_revision']), 'equals the previous revision'),
        (change(proposal, values={NAME: 4, 'skill_telemetry_audit.FP_THIN_RATE': 0.9},
                previous_values={NAME: 3, 'skill_telemetry_audit.FP_THIN_RATE': 0.8}), 'touches other thresholds'),
    ]
    for document, match in refused:
        with pytest.raises(ContractError, match=match):
            approvals.consume(approval['id'], document, now=T0 + timedelta(minutes=1))
    with pytest.raises(ContractError, match='approval expired'):
        approvals.consume(approval['id'], change(proposal), now=T0 + timedelta(hours=2))
    for malformed in ({'values': {NAME: float('nan')}}, {'values': {NAME: True}}, {'values': {'unknown.NAME': 4}},
                      {'revision': 'HEAD'}, {'environment': 'Staging'}, {'previous_values': 'none'}):
        with pytest.raises(ContractError):
            approvals.consume(approval['id'], change(proposal, **malformed), now=T0 + timedelta(minutes=1))
    assert approvals.inspect(approval['id'], now=T0 + timedelta(minutes=1))['state'] == 'issued', 'refusals consume nothing'
    consumed = approvals.consume(approval['id'], change(proposal), now=T0 + timedelta(minutes=2))
    assert consumed['status'] == 'consumed' and consumed['application'] == {
        'revision': 'c' * 40, 'generation': 1, 'environment': 'staging', 'at': (T0 + timedelta(minutes=2)).isoformat()}
    with pytest.raises(ContractError, match='approval is consumed'):
        approvals.consume(approval['id'], change(proposal), now=T0 + timedelta(minutes=3))
    with pytest.raises(ContractError, match='Only an issued approval can be revoked'):
        approvals.revoke(approval['id'], actor='conductor', reason='too late')
    with executor.service.store.transaction() as tx:
        events = sorted(tx.scan(EVENTS), key=lambda e: e['sequence'])
    kinds = [e['kind'] for e in events]
    assert kinds[0] == 'issued' and kinds.count('consumed') == 1 and kinds.count('refused') == len(refused) + 2
    assert kinds[-1] == 'refused' and events[-1]['reason'] == 'approval is consumed'
    assert approvals.inspect(approval['id'])['state'] == 'consumed'


def test_revocation_and_degraded_states(policy_repo, tmp_path, monkeypatch):  # noqa: F811
    executor, request, proposal = assessed(policy_repo, tmp_path, monkeypatch)
    store = executor.service.store
    approvals = ThresholdApprovals(store, executor.artifacts)
    approval = approvals.issue(request['id'], actor='conductor', environment='staging', ttl_seconds=60, now=T0)
    with pytest.raises(ContractError, match='Only a reviewer revokes'):
        approvals.revoke(approval['id'], actor='worker:implementation', reason='no')
    revoked = approvals.revoke(approval['id'], actor='lead:improvement', reason='a later rejection')
    assert revoked['status'] == 'revoked' and approvals.revoke(approval['id'], actor='conductor', reason='again') == revoked
    with pytest.raises(ContractError, match='approval is revoked'):
        approvals.consume(approval['id'], change(proposal), now=T0)
    assert approvals.inspect(approval['id'])['state'] == 'revoked'
    later = approvals.issue(request['id'], actor='conductor', environment='prod', ttl_seconds=60, now=T0)
    assert approvals.inspect(later['id'], now=T0 + timedelta(seconds=61))['state'] == 'expired'
    assert approvals.inspect('nope')['state'] == 'missing'
    store.data[BUCKET, later['id']]['proposed'] = math.nan
    assert approvals.inspect(later['id'])['state'] == 'corrupt'
    with pytest.raises(ContractError, match='Unknown threshold approval'):
        approvals.consume('nope', change(proposal))
    with pytest.raises(ContractError, match='Applied policy must carry'):
        parse_applied_policy({'revision': 'c' * 40})


def test_concurrent_consumers_on_postgres_get_one_certification(policy_repo, tmp_path, monkeypatch, isolated_pgstore):  # noqa: F811
    executor, request, proposal = assessed(policy_repo, tmp_path, monkeypatch)
    # The assessed rows are real outputs of the review chain; replay them into the isolated schema.
    with executor.service.store.transaction() as tx:
        records = tx.records()
    with isolated_pgstore.transaction() as tx:
        for record in records:
            tx.put(record['bucket'], record['id'], record['body'])
    approvals = ThresholdApprovals(isolated_pgstore, executor.artifacts)
    approval = approvals.issue(request['id'], actor='conductor', environment='staging', ttl_seconds=3600, now=T0)

    def attempt(index):
        try:
            return approvals.consume(approval['id'], change(proposal, revision=f'{index:040x}'[-40:].replace(' ', '0')),
                                     now=T0 + timedelta(minutes=1))
        except ContractError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(1, 9)))
    consumed = [r for r in results if isinstance(r, dict)]
    assert len(consumed) == 1 and all('approval is consumed' in r for r in results if isinstance(r, str))
    with isolated_pgstore.transaction() as tx:
        row = tx.get(BUCKET, approval['id'])
        refused = [e for e in tx.scan(EVENTS) if e['kind'] == 'refused']
    assert row['status'] == 'consumed' and row['application']['generation'] == 1 and len(refused) == 7
