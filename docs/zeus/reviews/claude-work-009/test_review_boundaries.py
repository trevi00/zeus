"""Independent counterexamples. Passing means the reported unsafe behavior reproduced.

Uses MemoryStore and deterministic fault injection; not production/model evidence.
"""
import sys
import json
from pathlib import Path

repository = next(p for p in Path(__file__).resolve().parents if (p / 'src' / 'codex_harness').is_dir())
sys.path.insert(0, str(repository / 'tests'))

from test_observations import Interceptor
from test_observation_wiring import build
from codex_harness.adapters.store import MemoryStore
from codex_harness.adapters.contracts import validate_observation
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.application.observations import Observer, Collector
from codex_harness.domain.observation import new_process_run_id


def observer(root, store, cap=4096):
    directory = SpoolDirectory(root)
    spool = FileSpool(root, new_process_run_id(), max_bytes=cap)
    return Observer(store, spool, component='review', role='worker:geeknews', directory=directory)


def test_collected_spool_stays_full(tmp_path):
    store = MemoryStore()
    o = observer(tmp_path, store)
    collector = Collector(store, o.directory, validate=validate_observation)
    for _ in range(20):
        o.emit('general.process_idle_exit', 'observed', attributes={'idle_seconds': 1})
        collector.collect()
    assert o.counters['dropped_spool_full'] > 0
    assert o.directory.acknowledged(o.spool.path) == o.spool.size()
    before = o.counters['dropped_spool_full']
    o.emit('general.process_idle_exit', 'observed', attributes={'idle_seconds': 1})
    assert o.counters['dropped_spool_full'] == before + 1
    o.close()


def test_failed_reconcile_removes_last_pending_marker(tmp_path):
    store = Interceptor(MemoryStore())
    o = observer(tmp_path, store)
    lease = {'id': 'review-task', '_bucket': 'tasks', 'generation': 1, 'attempt': 1}
    store.fail_transaction = OSError('sink unavailable')
    record_id = o.record_termination(lease, reservation_id=None, classification='unknown',
                                     stream_hash=None, error=OSError('lost settlement'))
    assert o.pending_terminations('review-task')
    try:
        o.resolve_termination(record_id, resolution='rerun', operator='review', reason='test')
    except OSError:
        pass
    else:
        raise AssertionError('expected transaction failure')
    store.fail_transaction = None
    assert o.pending_terminations('review-task') == []
    with store.transaction() as tx:
        assert tx.scan('observation_terminations') == []
        assert tx.scan('observation_audit') == []
    o.close()


def test_runtime_exception_allows_second_provider_start(tmp_path, monkeypatch):
    s = build(tmp_path, monkeypatch, MemoryStore(), runtime_error=OSError('lost transport after start'))
    first = s.executor.execute_one('worker:geeknews')
    assert first['status'] == 'retry' and len(s.starts) == 1
    assert s.observer.pending_terminations(s.task['id']) == []
    s.executor.execute_one('worker:geeknews')
    assert len(s.starts) == 2


def test_post_settlement_artifact_failure_allows_second_start(tmp_path, monkeypatch):
    s = build(tmp_path, monkeypatch, MemoryStore())
    def fail(*args, **kwargs):
        raise OSError('result artifact write failed')
    monkeypatch.setattr('codex_harness.adapters.executor.persist_result', fail)
    first = s.executor.execute_one('worker:geeknews')
    assert first['status'] == 'retry' and len(s.starts) == 1
    assert s.observer.pending_terminations(s.task['id']) == []
    s.executor.execute_one('worker:geeknews')
    assert len(s.starts) == 2


def test_reconcile_reason_leaks_credential_shaped_text(tmp_path):
    store = MemoryStore()
    o = observer(tmp_path, store)
    lease = {'id': 'review-task', '_bucket': 'tasks', 'generation': 1, 'attempt': 1}
    record_id = o.record_termination(lease, reservation_id=None, classification='unknown',
                                     stream_hash=None, error=OSError('lost settlement'))
    canary = 'review-secret-123456789'
    result = o.resolve_termination(record_id, resolution='discard', operator='review',
                                    reason='password=' + canary)
    assert canary in json.dumps(result)
    assert canary in (tmp_path / 'terminations' / 'resolved' / (record_id + '.json')).read_text('utf-8')
    with store.transaction() as tx:
        assert canary in json.dumps(tx.get('observation_terminations', record_id))
    o.close()


def test_correlation_and_schema_error_leak_into_observations(tmp_path):
    store = MemoryStore()
    o = observer(tmp_path, store, cap=16384)
    canary = 'review-secret-123456789'
    event = o.emit('general.process_idle_exit', 'observed', correlation_id='password=' + canary,
                   attributes={'idle_seconds': 1})
    assert canary in json.dumps(event)
    invalid = dict(event, event_id='invalid-review-event', outcome='password=' + canary)
    o.spool.append('event', invalid)
    Collector(store, o.directory, validate=validate_observation).collect()
    with store.transaction() as tx:
        assert canary in json.dumps(tx.scan('observations'))
        assert canary in json.dumps(tx.scan('observation_quarantine'))
    o.close()
