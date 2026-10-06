from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.measurements import Measurements
from codex_harness.domain.measurements import DEFINITIONS, evaluate

NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)


def task(key='one', status='succeeded', attempt=1, outcome='succeeded'):
    return {'id': key, 'status': status, 'attempt': attempt,
            'created_at': (NOW - timedelta(hours=1)).isoformat(),
            'attempt_outcomes': [{'attempt': 1, 'status': outcome,
                                  'at': (NOW - timedelta(minutes=1)).isoformat()}]}


def evidence(*rows):
    return {'tasks': list(rows), 'decisions': [], 'observed_at': NOW.isoformat()}


def test_retries_do_not_improve_first_attempt_denominator():
    data = evidence(task(), task('retry', attempt=2, outcome='failed'),
                    task('cancel', 'cancelled', 0), task('expired', 'expired', 0))
    data['tasks'][2]['attempt_outcomes'] = []
    data['tasks'][3]['attempt_outcomes'] = []
    first, terminal = [evaluate(d, data, NOW) for d in DEFINITIONS[:2]]
    assert (first.numerator, first.denominator, first.value) == (1, 2, .5)
    assert (terminal.numerator, terminal.denominator, terminal.value) == (2, 4, .5)
    assert first.status == terminal.status == 'unknown'
    assert first.observational


@pytest.mark.parametrize('offset,reason', [(121, 'stale'), (-1, 'future-dated')])
def test_freshness(offset, reason):
    data = evidence(task())
    data['observed_at'] = (NOW - timedelta(seconds=offset)).isoformat()
    for definition in DEFINITIONS:
        result = evaluate(definition, data, NOW)
        assert result.status == 'unknown' and reason in result.reason
        assert result.value is None


def test_missing_invalid_zero_insufficient_and_legacy():
    for data in (None, {}, evidence(), evidence(task(), task())):
        assert evaluate(DEFINITIONS[0], data, NOW).value is None
    insufficient = evaluate(replace(DEFINITIONS[0], minimum_samples=2), evidence(task()), NOW)
    assert insufficient.value is None and insufficient.sample_count == 1
    row = task(attempt=2)
    row.pop('attempt_outcomes')
    assert 'missing attempt history' in evaluate(DEFINITIONS[0], evidence(row), NOW).reason
    row = task()
    row['created_at'] = 'not-a-time'
    assert evaluate(DEFINITIONS[1], evidence(row), NOW).reason == 'invalid evidence'


def test_capacity_counts_decisions_and_excludes_expired_leases():
    data = evidence()
    for i in range(3):
        data['decisions'].append({'id': str(i), 'status': 'running',
                                 'lease_until': (NOW + timedelta(seconds=1)).isoformat()})
    result = evaluate(DEFINITIONS[2], data, NOW)
    assert result.value == 3 and result.status == 'fail'
    data['decisions'][0]['lease_until'] = NOW.isoformat()
    assert evaluate(DEFINITIONS[2], data, NOW).status == 'pass'
    assert evaluate(DEFINITIONS[2], evidence(), NOW).value == 0
    data['decisions'][0]['lease_until'] = None
    assert evaluate(DEFINITIONS[2], data, NOW).status == 'unknown'


def test_observations_reproduce_and_retain_original_inputs(tmp_path):
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    with store.transaction() as tx:
        tx.put('tasks', 'one', task())
    results = Measurements(store, artifacts).collect('a' * 40, NOW)
    snapshot = artifacts.document(results[0]['evidence_refs'][0])
    assert evaluate(DEFINITIONS[0], snapshot, NOW).value == 1
    with store.transaction() as tx:
        tx.put('tasks', 'one', task(status='failed'))
        assert len(tx.scan('metric_observations')) == 3
    assert artifacts.document(results[0]['evidence_refs'][0]) == snapshot
    assert all(r['promotion_approval'] is False for r in results)


def test_attempt_failures_survive_retry_and_are_not_duplicated():
    from codex_harness.application.workflow import Workflow
    row = task(status='running')
    row['attempt_outcomes'] = []
    Workflow._attempt_outcome(row, 'failed', NOW.isoformat(), 'failure evidence')
    Workflow._attempt_outcome(row, 'failed', NOW.isoformat())
    row['attempt'] = 2
    Workflow._attempt_outcome(row, 'succeeded', NOW.isoformat())
    assert [r['status'] for r in row['attempt_outcomes']] == ['failed', 'succeeded']
    assert row['attempt_outcomes'][0]['error'] == 'failure evidence'


def test_workflow_retry_history_is_fenced_and_cancellation_authorized():
    from codex_harness.application.workflow import Workflow
    from codex_harness.bootstrap import organization
    from codex_harness.domain.model import ContractError, envelope
    store = MemoryStore()
    workflow = Workflow(store, organization())
    message = envelope('task.assign', 'lead:improvement', 'worker:implementation',
                       'implement', {'objective': 'fixture'}, 'test')
    workflow.submit(message)
    first = workflow.claim('worker:implementation', 'first')
    workflow.fail(first, 'original failure')
    second = workflow.claim('worker:implementation', 'second')
    with pytest.raises(ContractError):
        workflow.fail(first, 'stale overwrite')
    with pytest.raises(ContractError):
        workflow.cancel(second['id'], 'worker:github', 'unauthorized')
    workflow.complete(second, {'summary': 'recovered'})
    with store.transaction() as tx:
        row = tx.get('tasks', first['id'])
    assert row['status'] == 'succeeded'
    assert [(r['attempt'], r['status']) for r in row['attempt_outcomes']] == [(1, 'failed'), (2, 'succeeded')]
    assert row['attempt_outcomes'][0]['error'] == 'original failure'


def test_monitor_reads_persisted_measurements_without_evaluating_or_writing(monkeypatch, tmp_path):
    """Producer/consumer seam: Measurements.collect persists rows and evidence; the monitor only
    reads them back. An empty store yields no measurements, never fabricated evaluations."""
    from copy import deepcopy
    from types import SimpleNamespace

    from codex_harness.adapters import monitoring
    from codex_harness.adapters.monitoring import read_only
    from codex_harness.bootstrap import organization
    store, artifacts_root = MemoryStore(), tmp_path / 'artifacts'
    artifacts = FileArtifacts(str(artifacts_root))
    # Injected fault (fixture): the monitor must not run git or any other process for measurements.
    monkeypatch.setattr(monitoring, 'run_process',
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError('monitor ran a process')))
    monkeypatch.setattr(monitoring, 'docker_facts', lambda repository, containers=None: [])
    monkeypatch.setattr(monitoring, 'redis_facts', lambda url, agents: [])
    service, reader = read_only(SimpleNamespace(store=store, org=organization()), artifacts)

    empty = monitoring.collect(service, reader, '.', '')['sources']['database']
    assert empty['status'] == 'ok' and empty['data']['measurements'] == []
    assert store.data == {} and list(artifacts_root.iterdir()) == []

    produced = Measurements(store, artifacts).collect('a' * 40, NOW)
    before, files = deepcopy(store.data), sorted(artifacts_root.iterdir())
    assert len(files) == 2  # one evidence body plus its receipt, written by the use case only
    for _ in range(2):
        database = monitoring.collect(service, reader, '.', '')['sources']['database']
    assert database['status'] == 'ok'
    measurements = database['data']['measurements']
    assert [m['metric_id'] for m in measurements] == sorted(d.metric_id for d in DEFINITIONS)
    assert all(m['source'] == 'persisted_observation' for m in measurements)
    assert all(m['observed_at'] == NOW.isoformat() and m['age_seconds'] > 120 for m in measurements)
    assert all(m['promotion_approval'] is False for m in measurements)
    capacity = next(m for m in measurements if m['metric_id'] == 'active_execution_capacity')
    assert capacity['value'] == 0 and capacity['evidence_refs'] == produced[2]['evidence_refs']
    assert reader.document(capacity['evidence_refs'][0])['observed_at'] == NOW.isoformat()
    assert store.data == before
    with store.transaction() as tx:
        assert len(tx.scan('metric_observations')) == 3
    assert sorted(artifacts_root.iterdir()) == files


@pytest.mark.parametrize('change', [
    {'created_at': (NOW + timedelta(seconds=1)).isoformat()},
    {'completed_at': (NOW + timedelta(seconds=1)).isoformat()},
    {'attempt': True},
    {'attempt': 0},
    {'status': 'made_up'},
])
def test_invalid_task_population_never_yields_a_ratio(change):
    row = task()
    row.update(change)
    for definition in DEFINITIONS[:2]:
        result = evaluate(definition, evidence(row), NOW)
        assert result.status == 'unknown' and result.value is None


def test_capacity_invalid_status_is_not_an_idle_snapshot():
    data = evidence({'id': 'bad', 'status': 'made_up'})
    assert evaluate(DEFINITIONS[2], data, NOW).value is None
