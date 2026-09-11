"""Counterexamples: a pass means unsafe behavior reproduced, not acceptance.

MemoryStore, actual temporary files, fake provider, deterministic fault injection.
"""
import json
import sys
from pathlib import Path

repository = next(p for p in Path(__file__).resolve().parents if (p / 'src' / 'codex_harness').is_dir())
sys.path.insert(0, str(repository / 'tests'))

from test_observation_wiring import build
from test_observations import CANARY, Interceptor, file_observer
from codex_harness.adapters.store import MemoryStore
from codex_harness.adapters.contracts import validate_observation
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.application.observations import Collector, Observer
from codex_harness.domain.observation import new_process_run_id


def test_completion_commit_failure_restarts_provider(tmp_path, monkeypatch):
    store = Interceptor(MemoryStore())
    s = build(tmp_path, monkeypatch, store)
    store.fail_put = lambda bucket, row: bucket == 'tasks' and row.get('status') == 'succeeded'
    result = s.executor.execute_one('worker:geeknews')
    assert result['status'] == 'retry' and len(s.starts) == 1
    assert not s.observer.pending_terminations(s.task['id'])
    store.fail_put = None
    assert s.executor.execute_one('worker:geeknews')['status'] == 'succeeded'
    assert len(s.starts) == 2


def test_termination_file_failure_bypasses_pg_and_block(tmp_path, monkeypatch):
    s = build(tmp_path, monkeypatch, MemoryStore(), runtime_error=OSError('transport after effect'))
    def disk_full(*args):
        raise OSError('disk full')
    monkeypatch.setattr(s.observer.directory, 'record_termination', disk_full)
    assert s.executor.execute_one('worker:geeknews')['status'] == 'retry'
    assert s.observer.pending_terminations(s.task['id']) == []
    s.executor.execute_one('worker:geeknews')
    assert len(s.starts) == 2


def test_live_origin_new_alert_deleted_by_stale_inheritor(tmp_path):
    store = Interceptor(MemoryStore())
    first = file_observer(tmp_path, store, alert_window_seconds=0)
    store.fail_transaction = OSError('sink unavailable')
    first.alert('spool_saturated', 'old', attributes={'bytes': 1, 'limit_bytes': 1, 'dropped': 1})
    second = file_observer(tmp_path, store, alert_window_seconds=0)
    inherited = {r['event_id'] for rows in second.inherited_pending.values() for r in rows}
    first.alert('spool_append_failed', 'new', attributes={'error_type': 'E', 'dropped': 1})
    new_ids = {r['event_id'] for r in first.pending_alerts} - inherited
    assert new_ids
    store.fail_transaction = None
    second.alert('spool_append_failed', 'recovered', attributes={'error_type': 'E', 'dropped': 1})
    with store.transaction() as tx:
        assert new_ids.isdisjoint({r['event_id'] for r in tx.scan('observation_alerts')})
    assert first.process_run_id not in first.directory.read_pending_alerts()
    first.close()  # next process must rely on durable pending debt
    third = file_observer(tmp_path, store, alert_window_seconds=0)
    assert not third.inherited_pending
    Collector(store, third.directory, validate=validate_observation, observer=third).collect()
    with store.transaction() as tx:
        assert new_ids.isdisjoint({r['event_id'] for r in tx.scan('observation_alerts')})
    second.close()
    third.close()


def test_segment_10000_is_invisible_to_collector(tmp_path):
    store = MemoryStore()
    spool = FileSpool(tmp_path, new_process_run_id(), max_bytes=10000, segment_bytes=1000)
    spool.segment = 10000  # equivalent reachable segment index without 10000 writes
    o = Observer(store, spool, component='review', directory=SpoolDirectory(tmp_path))
    event = o.emit('general.process_idle_exit', 'observed', attributes={'idle_seconds': 1})
    assert event is not None and spool.path.is_file()
    assert o.directory.spool_files() == []
    assert Collector(store, o.directory, validate=validate_observation).collect()['records'] == 0
    o.close()


def test_known_token_shape_accepted_as_identifier(tmp_path):
    store = MemoryStore()
    o = file_observer(tmp_path, store)
    token = 'ghp_' + 'A' * 30  # synthetic, recognized by existing redactor
    event = o.emit('general.process_idle_exit', 'observed', correlation_id=token,
                   evidence_refs=[token], attributes={'idle_seconds': 1})
    assert event is not None and token in json.dumps(event)
    Collector(store, o.directory, validate=validate_observation).collect()
    with store.transaction() as tx:
        assert token in json.dumps(tx.scan('observations'))
    o.close()


def test_settlement_error_cause_reaches_cli_output(tmp_path, monkeypatch, capsys):
    from codex_harness.cli import emit
    store = Interceptor(MemoryStore())
    s = build(tmp_path, monkeypatch, store)
    store.fail_put = lambda bucket, row: bucket == 'observation_audit' and row.get('event_type') == 'development.invocation_settled'
    result = s.executor.execute_one('worker:geeknews')
    assert result['status'] == 'blocked'
    assert CANARY in json.dumps(result)
    emit(result)
    assert CANARY in capsys.readouterr().out
