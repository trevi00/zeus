"""Review counterexamples: pass means the unsafe boundary was reproduced.

MemoryStore, real temporary spool files, fake provider, deterministic failures.
"""
import json
import sys
from contextlib import contextmanager
from pathlib import Path

repository = next(p for p in Path(__file__).resolve().parents if (p / 'src' / 'codex_harness').is_dir())
sys.path.insert(0, str(repository / 'tests'))

from test_observation_wiring import build
from test_observations import CANARY, Interceptor, file_observer
from codex_harness.adapters.store import MemoryStore
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.adapters.contracts import validate_observation
from codex_harness.application.observations import Observer, Collector
from codex_harness.domain.observation import new_process_run_id
from codex_harness.cli import emit


class ScanFailureStore:
    def __init__(self):
        self.store = MemoryStore()
        self.fail_scan = False

    @contextmanager
    def transaction(self):
        with self.store.transaction() as tx:
            owner = self
            class Tx:
                def __getattr__(self, name):
                    return getattr(tx, name)
                def scan(self, bucket):
                    if bucket == 'observation_terminations' and owner.fail_scan:
                        owner.fail_scan = False
                        raise OSError('transient marker read outage')
                    return tx.scan(bucket)
            yield Tx()


def test_failed_marker_read_starts_provider_despite_prior_unconfirmed(tmp_path, monkeypatch):
    store = ScanFailureStore()
    s = build(tmp_path, monkeypatch, store)
    # A durable marker from an earlier unknown execution exists; the task is claimable after recovery.
    prior = s.executor.workflow.claim('worker:geeknews', 'previous-worker')
    with store.transaction() as tx:
        marker = s.observer.mark_unconfirmed(tx, prior, reservation_id='prior-invocation')
        row = tx.get('tasks', s.task['id'])
        row['lease_until'] = '2000-01-01T00:00:00+00:00'
        tx.put('tasks', s.task['id'], row)
    store.fail_scan = True
    result = s.executor.execute_one('worker:geeknews')
    assert result['status'] == 'succeeded' and len(s.starts) == 1
    with store.transaction() as tx:
        assert tx.get('observation_terminations', marker['record_id'])['status'] == 'unconfirmed'


def test_completion_error_still_leaks_to_cli(tmp_path, monkeypatch, capsys):
    store = Interceptor(MemoryStore())
    s = build(tmp_path, monkeypatch, store)
    store.fail_put = lambda bucket, row: bucket == 'tasks' and row.get('status') == 'succeeded'
    result = s.executor.execute_one('worker:geeknews')
    assert result['status'] == 'blocked'
    assert CANARY in json.dumps(result)
    emit(result)
    assert CANARY in capsys.readouterr().out


def test_pending_alerts_without_spool_records_never_replay(tmp_path):
    store = Interceptor(MemoryStore())
    spool = FileSpool(tmp_path, new_process_run_id(), max_bytes=1)
    first = Observer(store, spool, component='review', directory=SpoolDirectory(tmp_path))
    store.fail_transaction = OSError('sink down')
    assert first.emit('general.process_idle_exit', 'observed', attributes={'idle_seconds': 1}) is None
    assert first.pending_alerts and first.directory.read_pending_alerts()
    first.close()
    store.fail_transaction = None
    second = Observer(store, FileSpool(tmp_path, new_process_run_id(), max_bytes=10000),
                      component='review-collector', directory=SpoolDirectory(tmp_path))
    collector = Collector(store, second.directory, validate=validate_observation, observer=second)
    for _ in range(3):
        assert collector.collect()['records'] == 0
    assert second.inherited_pending and second.directory.read_pending_alerts()
    with store.transaction() as tx:
        assert tx.scan('observation_alerts') == []
    second.close()


def test_age_alone_classifies_live_writer_as_finished(tmp_path):
    o = file_observer(tmp_path, MemoryStore())
    assert o.emit('general.process_idle_exit', 'observed', attributes={'idle_seconds': 1})
    assert o.spool._descriptor is not None and not o.directory.closed(o.process_run_id)
    cutoff = o.spool.path.stat().st_mtime + 8 * 86400
    assert o.directory.run_finished(o.process_run_id, now=cutoff)
    # The same writer can still append; no closure or liveness proof was involved.
    assert o.emit('general.process_idle_exit', 'observed', attributes={'idle_seconds': 2})
    o.close()
