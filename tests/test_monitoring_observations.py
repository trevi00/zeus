"""Observatory-001 projection: bounded sample, priority order, dedup, unknowns, local health."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from codex_harness.adapters import monitoring
from codex_harness.adapters.monitoring import read_only
from codex_harness.adapters.monitoring_observations import (
    BUCKET_LIMIT,
    ROW_LIMIT,
    local_facts,
    observation_facts,
    scan_bounded,
)
from codex_harness.adapters.observation_spool import SpoolDirectory
from codex_harness.adapters.store import MemoryStore
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError

NOW = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
CANARY = 'CANARY-5f1e2d3c4b5a69788796a5b4c3d2e1f0'


def event(event_id, category='development', severity='info', minutes=0, **extra):
    """Synthetic stored observation row (fixture shape of application.observations rows)."""
    row = {'event_id': event_id, 'event_type': f'{category}.fixture', 'category': category, 'severity': severity,
           'outcome': 'observed', 'observed_at': (NOW - timedelta(minutes=minutes)).isoformat(),
           'occurred_at': None, 'source': {'component': 'unit', 'host': 'h', 'pid': 1},
           'execution': {'kind': 'system', 'process_run_id': 'a' * 32, 'task_id': None, 'attempt': None},
           'evidence_refs': ['sha256:' + 'b' * 64], 'attributes': {'secret_prompt': 'password=' + CANARY},
           'payload_hash': 'x'}
    row.update(extra)
    return row


def test_priority_order_dedup_and_unknown_rows():
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put('observations', 'e1', event('e1', 'operations', 'info', record_kind='event', collected_at=NOW.isoformat()))
        tx.put('observations', 'e2', event('e2', 'development', 'critical', record_kind='event', collected_at=NOW.isoformat()))
        tx.put('observations', 'e3', event('e3', 'general', 'error', minutes=5, record_kind='event', collected_at=NOW.isoformat()))
        tx.put('observations', 'e4', event('e4', 'operations', 'error', minutes=1, record_kind='event', collected_at=NOW.isoformat()))
        tx.put('observations', 'e5', event('e5', 'operations', 'error', minutes=0, record_kind='event', collected_at=NOW.isoformat()))
        tx.put('observation_audit', 'e1', event('e1', 'operations', 'info'))  # duplicate of a collected row
        tx.put('observation_audit', 'a1', event('a1', 'general', 'debug', minutes=9))  # audit only
        tx.put('observation_audit', 'bad', event('bad', 'weird', 'loud', observed_at='not-a-time'))
        tx.put('observation_audit', 'naive', event('naive', 'general', 'warning', observed_at='2026-09-18T11:00:00'))
    facts = observation_facts(store, None, NOW)
    events = facts['events']
    assert [e['event_id'] for e in events['rows']] == ['e2', 'e4', 'e5', 'e3', 'naive', 'e1', 'a1', 'bad']
    assert events['total'] == 8 and events['record_kinds'] == {'both': 1, 'collected': 4, 'audit': 3}
    assert events['by_category'] == {'operations': 3, 'development': 1, 'general': 3, 'unknown': 1}
    assert events['unknown'] == {'severity': 1, 'category': 1, 'observed_at': 2}
    assert [e['event_id'] for e in events['high_severity']] == ['e2', 'e4', 'e5', 'e3']
    first = events['rows'][0]
    assert first['record_kind'] == 'collected' and first['collected_at'] == NOW.isoformat()
    assert 'attributes' not in first and CANARY not in str(facts)
    assert first['evidence_refs'] == ['sha256:' + 'b' * 64] and first['execution']['kind'] == 'system'
    merged = next(e for e in events['rows'] if e['event_id'] == 'e1')
    assert merged['record_kind'] == 'both'
    assert facts['labels']['general'] == '일반·디버깅'
    assert facts['sample']['truncated'] is False and facts['local']['status'] == 'unavailable'
    assert facts['local']['reason'] == 'runtime_not_configured'


def test_bounded_sample_reports_truncation_and_row_cap():
    store = MemoryStore()
    with store.transaction() as tx:
        for index in range(BUCKET_LIMIT + 3):
            tx.put('observations', f'r{index:05d}', event(f'r{index:05d}', 'general', 'debug', record_kind='event'))
    facts = observation_facts(store, None, NOW)
    bucket = facts['sample']['buckets']['observations']
    assert bucket == {'scanned': BUCKET_LIMIT, 'limit': BUCKET_LIMIT, 'truncated': True}
    assert facts['sample']['truncated'] is True and facts['events']['total'] == BUCKET_LIMIT
    assert len(facts['events']['rows']) == ROW_LIMIT and facts['events']['rows_truncated'] is True
    with store.transaction() as tx:
        rows, meta = scan_bounded(tx, 'observations', limit=5, page=2)
        assert [r['event_id'] for r in rows] == [f'r{i:05d}' for i in range(5)] and meta['truncated'] is True
        rows, meta = scan_bounded(tx, 'observation_audit', limit=5, page=2)
        assert rows == [] and meta == {'scanned': 0, 'limit': 5, 'truncated': False}


def test_script_like_labels_and_credentials_are_redacted_and_bounded():
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put('observation_audit', 'x', event('x', 'operations', 'warning', reason_code='<script>alert(1)</script>',
                                              event_type='operations.' + 'y' * 400))
        tx.put('operations', 'op', {'id': 'op', 'status': 'running', 'reason_code': None, 'task_id': 't1',
                                    'goal': {'criterion': 'token=' + CANARY + ' <img onerror=x>'}})
    facts = observation_facts(store, None, NOW)
    row = facts['events']['rows'][0]
    assert row['reason_code'] == '<script>alert(1)</script>' and len(row['event_type']) == 200
    operation = facts['operations']['rows'][0]
    assert CANARY not in operation['criterion'] and '[REDACTED' in operation['criterion']
    assert facts['operations']['by_status'] == {'running': 1}


def test_collection_alerts_quarantine_terminations_and_operations_are_separate():
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put('observation_collections', 'c1', {'id': 'c1', 'file': 'a.jsonl', 'records': 3, 'inserted': 2,
                                                  'duplicates': 1, 'at': (NOW - timedelta(seconds=90)).isoformat()})
        tx.put('observation_collections', 'c0', {'id': 'c0', 'records': 1, 'at': (NOW - timedelta(hours=1)).isoformat()})
        tx.put('observation_collections', 'cx', {'id': 'cx', 'at': 'garbage'})
        tx.put('observation_alerts', 'al', {'event_id': 'al', 'notification': {'status': 'pending'}})
        tx.put('observation_quarantine', 'q', {'id': 'q', 'reason': 'corrupt_record'})
        tx.put('observation_terminations', 't1', {'record_id': 't1', 'status': 'pending_reconciliation'})
        tx.put('observation_terminations', 't2', {'record_id': 't2', 'status': 'unconfirmed'})
        tx.put('observation_terminations', 't3', {'record_id': 't3', 'status': 'closed'})
        tx.put('operations', 'op', {'id': 'op', 'status': 'failed', 'reason_code': 'evidence_gate_refused',
                                    'task_id': 'task', 'lead_accepted': None, 'goal': {'criterion': 'c'}})
        tx.put('tasks', 'task', {'id': 'task', 'status': 'succeeded'})
    facts = observation_facts(store, None, NOW)
    assert facts['collection']['last_at'] == (NOW - timedelta(seconds=90)).isoformat()
    assert facts['collection']['lag_seconds'] == 90.0 and facts['collection']['receipts'] == 3
    assert facts['collection']['last']['inserted'] == 2 and facts['collection']['receipts_with_time'] == 2
    assert facts['alerts'] == {'recorded': 1, 'by_status': {'pending': 1}}
    assert facts['quarantine'] == {'total': 1, 'by_reason': {'corrupt_record': 1}}
    assert facts['terminations'] == {'by_status': {'pending_reconciliation': 1, 'unconfirmed': 1, 'closed': 1}, 'pending': 2}
    assert facts['operations']['rows'][0] == {'id': 'op', 'status': 'failed', 'reason_code': 'evidence_gate_refused',
                                              'task_id': 'task', 'decision_id': None, 'lead_accepted': None,
                                              'criterion': 'c', 'correlation_id': None}
    empty = observation_facts(MemoryStore(), None, NOW)
    assert empty['collection']['last_at'] is None and empty['collection']['lag_seconds'] is None
    assert empty['events']['rows'] == [] and empty['authority'] == 'informational_only'


def test_local_spool_health_is_read_only_and_unavailable_when_missing(tmp_path):
    assert local_facts(tmp_path) == {'status': 'unavailable', 'reason': 'directory_missing'}
    root = tmp_path / 'observations'
    directory = SpoolDirectory(root)
    directory.write_health('a' * 32, {'process_run_id': 'a' * 32, 'component': 'exec', 'role': 'worker',
                                      'updated_at': NOW.isoformat(), 'sink': 'unavailable',
                                      'counters': {'dropped_spool_full': 2}, 'spool': {'unacknowledged_bytes': 10, 'limit_bytes': 20},
                                      'pending_alerts': [{'event_type': 'x'}], 'last_defect': 'password=' + CANARY})
    (root / 'health' / ('b' * 32 + '.json')).write_text('{broken', 'utf-8')
    directory.write_pending_alerts('a' * 32, [{'event_id': 'p1'}])
    directory.record_termination('term', {'record_id': 'term', 'task_id': 't', 'status': 'pending_reconciliation'})
    (root / 'spool').mkdir()
    (root / 'spool' / ('a' * 32 + '.0000.jsonl')).write_bytes(b'x' * 1024)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))
    local = local_facts(tmp_path)
    assert local['status'] == 'ok' and local['segments'] == 1 and local['unacknowledged_bytes'] == 1024
    assert local['health_total'] == 2 and local['health'][0]['dropped']['dropped_spool_full'] == 2
    assert local['health'][0]['sink'] == 'unavailable' and CANARY not in str(local)
    assert local['health'][1]['unreadable'] is True
    assert local['pending_alerts'] == 1 and local['pending_alert_files'] == {'a' * 32: 1}
    assert local['pending_terminations'] == 1 and local['unreadable_terminations'] == 0
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob('*')) == before  # no lock, ack or reclaim


def test_collect_adds_observations_only_with_runtime_and_keeps_other_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(monitoring, 'docker_facts', lambda repository, containers=None: [])
    monkeypatch.setattr(monitoring, 'redis_facts', lambda url, agents: [])
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put('observations', 'e', event('e', 'operations', 'critical', record_kind='event'))
    service, artifacts = read_only(SimpleNamespace(store=store, org=organization()), None)
    legacy = monitoring.collect(service, artifacts, str(tmp_path), 'redis://127.0.0.1/0')
    # autonomous-operation-001 added the read-only `fleet_backlog`, `host_delivery` and
    # `worker_sessions` envelopes beside the existing store-backed sources; `observations` still
    # appears only with a runtime directory, and every original source is still collected as before.
    assert set(legacy['sources']) == {'database', 'docker', 'redis', 'fleet', 'research_programs', 'portfolio',
                                      'fleet_backlog', 'host_delivery', 'worker_sessions'}
    assert legacy['sources']['worker_sessions']['status'] == 'ok'
    assert legacy['sources']['worker_sessions']['data']['sessions'] == []
    assert legacy['sources']['fleet']['data']['registered'] is False
    assert legacy['sources']['fleet_backlog']['data']['registered'] is False
    # Nothing registered and delivery disabled: an explicit projection, never an absent source.
    assert legacy['sources']['host_delivery']['status'] == 'ok'
    assert legacy['sources']['host_delivery']['data']['registered'] is False
    assert legacy['sources']['host_delivery']['data']['enabled'] is False
    assert legacy['sources']['host_delivery']['data']['targets'] == []
    assert 'observations' not in legacy['sources']
    before = store.data.copy()
    result = monitoring.collect(service, artifacts, str(tmp_path), 'redis://127.0.0.1/0', runtime=tmp_path / 'runtime')
    source = result['sources']['observations']
    assert source['status'] == 'ok' and source['data']['events']['by_severity'] == {'critical': 1}
    assert source['data']['local'] == {'status': 'unavailable', 'reason': 'directory_missing'}
    assert result['sources']['database']['status'] == 'ok' and store.data == before

    class Broken:
        def transaction(self):
            raise RuntimeError('injected observation outage')
    monkeypatch.setattr(monitoring, 'observation_facts',
                        lambda store, runtime: observation_facts(Broken(), runtime))
    result = monitoring.collect(service, artifacts, str(tmp_path), 'redis://127.0.0.1/0', runtime=tmp_path)
    assert result['sources']['observations'] == {'status': 'unavailable', 'error': 'RuntimeError', 'data': None,
                                                 'observed_at': result['sources']['observations']['observed_at']}
    assert result['sources']['database']['status'] == 'ok' and result['sources']['docker']['status'] == 'ok'
    # One failed source hides no neighbour, old or newly added.
    assert result['sources']['fleet_backlog']['status'] == 'ok'
    assert result['sources']['host_delivery']['status'] == 'ok'


def test_projection_never_writes_through_the_read_only_store():
    store = MemoryStore()
    service, _ = read_only(SimpleNamespace(store=store, org=organization()), None)
    with pytest.raises(ContractError):
        with service.store.transaction() as tx:
            tx.put('observations', 'x', {})
    assert observation_facts(service.store, None, NOW)['events']['total'] == 0 and store.data == {}
