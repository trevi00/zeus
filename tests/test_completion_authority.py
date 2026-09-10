"""FA-018: a completion verdict is authority only when bound to the execution it judged (INV-COMPLETION-001).

The upstream selector stored any event with a verdict string and a caller timestamp and picked
approved records by time alone. Here the schema is closed, bindings are checked against the
PostgreSQL-owned task row, order is recording order, and every degraded ledger state is named.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from test_workflow import assignment

from codex_harness.adapters.store import MemoryStore, PostgresStore
from codex_harness.application.completion import BUCKET, REJECTIONS, STATES, CompletionAuthority
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError

SPEC = 'a' * 40
OTHER_SPEC = 'd' * 40
ARTIFACT = 'sha256:' + 'b' * 64
OTHER_ARTIFACT = 'sha256:' + 'e' * 64
RECEIPT = 'c' * 64


def backend_store(backend, request):
    return MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')


def running_task(store):
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    return workflow, workflow.claim('worker:implementation', 'owner-1')


def verdict(task, **over):
    target = {'task_id': task['id'], 'generation': task['generation'], 'attempt': task['attempt']}
    base = {'schema_version': 1, 'event': 'completion.verdict', 'verdict': 'approved', 'target': target,
            'spec_revision': SPEC, 'evaluation_artifact': ARTIFACT,
            'runner_receipt': {'id': 'run-1', 'digest': RECEIPT, **target},
            'reviewer': {'actor': 'lead:qa', 'kind': 'model'},
            'scenarios': {'expected': ['login', 'checkout'], 'passed': ['login', 'checkout'], 'excluded': []},
            'observed_at': datetime.now(timezone.utc).isoformat()}
    return {**base, **over}


def inspect(authority, task, spec=SPEC, artifact=ARTIFACT):
    return authority.inspect(task['id'], spec_revision=spec, evaluation_artifact=artifact)


FUTURE = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
MALFORMED = [
    ('schema null', {'schema_version': None}, 'schema_version'),
    ('schema unknown', {'schema_version': 2}, 'schema_version'),
    ('schema text', {'schema_version': '1'}, 'schema_version'),
    ('unrelated event', {'event': 'unrelated'}, 'event'),
    ('verdict list', {'verdict': ['approved']}, 'verdict'),
    ('verdict false text', {'verdict': 'false'}, 'verdict'),
    ('completeness false text', {'completeness': 'false'}, 'exactly'),
    ('caller cross_target flag', {'cross_target': True}, 'exactly'),
    ('nan timestamp', {'observed_at': float('nan')}, 'observed_at'),
    ('numeric timestamp', {'observed_at': 200}, 'observed_at'),
    ('naive timestamp', {'observed_at': '2026-09-10T00:00:00'}, 'timezone'),
    ('future timestamp', {'observed_at': FUTURE}, 'future'),
    ('generation text', {'target': {'task_id': 'x', 'generation': '1', 'attempt': 1}}, 'generation'),
    ('generation bool', {'target': {'task_id': 'x', 'generation': True, 'attempt': 1}}, 'generation'),
    ('spec short', {'spec_revision': 'abc'}, 'spec_revision'),
    ('artifact bare', {'evaluation_artifact': 'b' * 64}, 'evaluation_artifact'),
    ('reviewer empty', {'reviewer': {'actor': ' ', 'kind': 'model'}}, 'reviewer.actor'),
    ('reviewer kind', {'reviewer': {'actor': 'lead:qa', 'kind': 'caller'}}, 'reviewer.kind'),
    ('duplicate scenario', {'scenarios': {'expected': ['a', 'a'], 'passed': ['a'], 'excluded': []}}, 'repeat'),
    ('passed outside expected', {'scenarios': {'expected': ['a'], 'passed': ['b'], 'excluded': []}}, 'subset'),
    ('exclusion unapproved', {'scenarios': {'expected': ['a'], 'passed': [], 'excluded': [{'id': 'a'}]}}, 'exactly'),
]


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_malformed_records_are_rejected_and_logged(backend, request):
    store = backend_store(backend, request)
    _, task = running_task(store)
    authority = CompletionAuthority(store)
    for name, mutation, match in MALFORMED:
        record = verdict(task, **mutation)
        for _ in range(2):  # the same malformed record replayed lands on the same notice
            with pytest.raises(ContractError, match='Completion verdict rejected.*' + match):
                authority.record(record)
    cross = verdict(task)
    cross['runner_receipt'] = {**cross['runner_receipt'], 'task_id': 'someone-else'}
    with pytest.raises(ContractError, match='different execution'):
        authority.record(cross)
    with store.transaction() as tx:
        assert tx.scan(BUCKET) == [], 'nothing malformed enters the verdict ledger'
        rejections = tx.scan(REJECTIONS)
    # Every distinct refusal is one structured notice; replays did not add rows.
    assert len(rejections) == len(MALFORMED) + 1
    assert all(r['reason'].startswith('Completion verdict rejected') and r['task_id'] in {task['id'], 'x'}
               for r in rejections)
    assert inspect(authority, task)['state'] == 'rejected_only'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_worker_success_is_not_completion_authority(backend, request):
    store = backend_store(backend, request)
    workflow, task = running_task(store)
    authority = CompletionAuthority(store)
    assert inspect(authority, task)['state'] == 'not_evaluated'
    assert workflow.complete(task, {'summary': 'self-reported'})['status'] == 'succeeded'
    report = inspect(authority, task)
    assert (report['state'], report['authority'], report['verdicts']) == ('not_evaluated', False, 0)
    with pytest.raises(ContractError, match='No completion authority: not_evaluated'):
        authority.require_authority(task['id'], spec_revision=SPEC, evaluation_artifact=ARTIFACT)
    assert authority.inspect('no-such-task', spec_revision=SPEC, evaluation_artifact=ARTIFACT)['state'] == 'no_ledger'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_verdict_binds_execution_spec_artifact_and_receipt(backend, request):
    store = backend_store(backend, request)
    workflow, task = running_task(store)
    authority = CompletionAuthority(store)
    behind = verdict(task, target={**verdict(task)['target'], 'generation': task['generation'] + 1})
    behind['runner_receipt'] = {**behind['runner_receipt'], 'generation': task['generation'] + 1}
    with pytest.raises(ContractError, match='different execution than the current one'):
        authority.record(behind)
    recorded = authority.record(verdict(task))
    assert recorded['changed'] and recorded['sequence'] == 1
    assert inspect(authority, task)['state'] == 'not_succeeded', 'approved before the worker finished'
    workflow.complete(task, {'summary': 'done'})
    report = inspect(authority, task)
    assert report['state'] == 'authoritative' and report['authority'] and report['latest']['verdict'] == 'approved'
    assert authority.require_authority(task['id'], spec_revision=SPEC, evaluation_artifact=ARTIFACT)['authority']
    # The same approved record proves nothing about another spec or another evaluation artifact.
    assert inspect(authority, task, spec=OTHER_SPEC)['state'] == 'stale'
    assert inspect(authority, task, artifact=OTHER_ARTIFACT)['state'] == 'stale'
    # Same scenario text under a different spec is a different verdict identity.
    other = authority.record(verdict(task, spec_revision=OTHER_SPEC))
    assert other['changed'] and other['id'] != recorded['id'] and other['sequence'] == 2
    assert inspect(authority, task)['latest']['id'] == recorded['id']


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_reclaimed_execution_makes_old_verdicts_stale(backend, request):
    store = backend_store(backend, request)
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    first = workflow.claim('worker:implementation', 'owner-1', lease_seconds=1)
    authority = CompletionAuthority(store)
    authority.record(verdict(first))
    time.sleep(1.2)
    second = workflow.claim('worker:implementation', 'owner-2', lease_seconds=60)
    assert second['generation'] == 2 and second['attempt'] == 2
    workflow.complete(second, {'summary': 'second attempt'})
    report = inspect(authority, second)
    assert (report['state'], report['authority'], report['verdicts']) == ('stale', False, 1)
    assert authority.record(verdict(first))['changed'] is False, 'the recorded gen1 verdict replays idempotently'
    with pytest.raises(ContractError, match='different execution than the current one'):
        authority.record(verdict(first, reviewer={'actor': 'late-reviewer', 'kind': 'human'}))
    authority.record(verdict(second))
    assert inspect(authority, second)['state'] == 'authoritative'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_recording_order_not_observed_time_selects_the_verdict(backend, request):
    store = backend_store(backend, request)
    workflow, task = running_task(store)
    workflow.complete(task, {'summary': 'done'})
    authority = CompletionAuthority(store)
    base = datetime.now(timezone.utc)
    approved = verdict(task, observed_at=(base + timedelta(seconds=10)).isoformat())
    rejected = verdict(task, verdict='iterate', observed_at=base.isoformat(),
                       reviewer={'actor': 'conductor', 'kind': 'human'})
    authority.record(approved)
    assert inspect(authority, task)['state'] == 'authoritative'
    authority.record(rejected)  # collected later, observed earlier: still the current verdict
    assert inspect(authority, task)['state'] == 'not_approved'
    replay = authority.record({**approved, 'observed_at': (base + timedelta(seconds=30)).isoformat()})
    assert replay == {'id': replay['id'], 'changed': False, 'sequence': 1}
    assert inspect(authority, task)['state'] == 'not_approved', 'an old acceptance never outranks the rejection'
    same_second = verdict(task, observed_at=base.isoformat(), reviewer={'actor': 'lead:qa2', 'kind': 'model'})
    authority.record(same_second)
    assert inspect(authority, task)['latest']['sequence'] == 3
    assert inspect(authority, task)['state'] == 'authoritative'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_scenario_denominator_is_explicit(backend, request):
    store = backend_store(backend, request)
    workflow, task = running_task(store)
    workflow.complete(task, {'summary': 'done'})
    authority = CompletionAuthority(store)
    empty = {'expected': [], 'passed': [], 'excluded': []}
    authority.record(verdict(task, scenarios=empty))
    assert inspect(authority, task)['state'] == 'incomplete', 'an empty denominator is not a full pass'
    partial = {'expected': ['login', 'checkout'], 'passed': ['login'], 'excluded': []}
    authority.record(verdict(task, scenarios=partial))
    assert inspect(authority, task)['state'] == 'incomplete'
    excluded = {'expected': ['login', 'checkout'], 'passed': ['login'],
                'excluded': [{'id': 'checkout', 'approved_by': 'human:owner', 'revision': OTHER_SPEC,
                              'reason': 'payment sandbox unavailable this round'}]}
    authority.record(verdict(task, scenarios=excluded))
    report = inspect(authority, task)
    assert report['state'] == 'authoritative' and report['latest']['complete']


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_duplicate_and_concurrent_records_do_not_inflate(backend, request):
    store = backend_store(backend, request)
    workflow, task = running_task(store)
    workflow.complete(task, {'summary': 'done'})
    authority = CompletionAuthority(store)
    record = verdict(task)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(authority.record, [record] * 8))
    assert sum(r['changed'] for r in results) == 1 and {r['sequence'] for r in results} == {1}
    report = inspect(authority, task)
    assert report['verdicts'] == 1 and report['state'] == 'authoritative'
    with pytest.raises(ContractError, match='identity reused'):
        with store.transaction() as tx:
            row = tx.get(BUCKET, results[0]['id'])
            tx.put(BUCKET, row['id'], {**row, 'verdict': 'iterate'})
        authority.record(record)


def test_memory_corruption_is_a_named_state():
    store = MemoryStore()
    workflow, task = running_task(store)
    workflow.complete(task, {'summary': 'done'})
    authority = CompletionAuthority(store)
    first = authority.record(verdict(task))['id']
    store.data[BUCKET, first]['verdict'] = 'false'
    assert inspect(authority, task)['state'] == 'corrupt'
    authority.record(verdict(task, reviewer={'actor': 'lead:qa2', 'kind': 'model'}))
    report = inspect(authority, task)
    assert (report['state'], report['authority'], report['corrupt']) == ('partially_corrupt', False, 1)


def test_postgres_corruption_and_unreachable_store_are_distinct(isolated_pgstore):
    store = isolated_pgstore
    workflow, task = running_task(store)
    workflow.complete(task, {'summary': 'done'})
    authority = CompletionAuthority(store)
    first = authority.record(verdict(task))['id']
    assert inspect(authority, task)['state'] == 'authoritative'
    with psycopg.connect(store.dsn) as conn:
        conn.execute("UPDATE documents SET body = body || '{\"observed_at\": 200}' WHERE bucket=%s AND id=%s",
                     (BUCKET, first))
    report = inspect(authority, task)
    assert (report['state'], report['authority'], report['corrupt']) == ('corrupt', False, 1)
    authority.record(verdict(task, reviewer={'actor': 'lead:qa2', 'kind': 'model'}))
    assert inspect(authority, task)['state'] == 'partially_corrupt'
    with psycopg.connect(store.dsn) as conn:
        conn.execute("UPDATE documents SET body = body - 'reviewer' WHERE bucket=%s AND id=%s", (BUCKET, first))
    assert inspect(authority, task)['state'] == 'partially_corrupt'
    unreachable = CompletionAuthority(PostgresStore('postgresql://127.0.0.1:1/zeus?connect_timeout=1'))
    report = unreachable.inspect(task['id'], spec_revision=SPEC, evaluation_artifact=ARTIFACT)
    assert report['state'] == 'unreadable' and not report['authority'] and report['reason']
    with pytest.raises(ContractError, match='No completion authority: unreadable'):
        unreachable.require_authority(task['id'], spec_revision=SPEC, evaluation_artifact=ARTIFACT)


def test_every_named_state_is_reachable():
    # The classification is the contract; a state that no test reaches is a state no consumer can trust.
    reached = {'unreadable', 'no_ledger', 'corrupt', 'partially_corrupt', 'rejected_only', 'not_evaluated',
               'stale', 'not_approved', 'incomplete', 'not_succeeded', 'authoritative'}
    assert reached == set(STATES)
