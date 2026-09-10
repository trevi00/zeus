"""Actual process/service interruptions. These do NOT prove PC sleep or reboot."""
import ctypes
import json
import os
import runpy
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from test_workflow import assignment

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import PostgresStore
from codex_harness.adapters.verification import VerificationServices
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization

WORKER = '''
import json,os,sys,threading,time
from pathlib import Path
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError
root=Path(sys.argv[1]);mode=sys.argv[2]
w=Workflow(PostgresStore(os.environ['HOST_TEST_DSN']),organization())
lease=json.loads((root/'lease.json').read_text('utf-8'))
if mode=='suspend':
 # Single Python worker main thread is the only workflow caller; no background heartbeat.
 w.heartbeat(lease)
 info={'pid':os.getpid(),'ppid':os.getppid(),'thread':threading.get_native_id(),
       'nonce':os.environ['HOST_TEST_NONCE'],'monotonic':time.monotonic()}
 (root/'ready.tmp').write_text(json.dumps(info),encoding='utf-8');(root/'ready.tmp').replace(root/'ready.json')
 while not (root/'go').exists():time.sleep(.02)
elif mode=='uncommitted':
 with w.store.transaction() as tx:
  w.fail(lease,'controlled uncommitted failure',transaction=tx)
  (root/'ready.json').write_text('{}',encoding='utf-8')
  while not (root/'go').exists():time.sleep(.02)
 print('committed');raise SystemExit(0)
try:
 if mode=='heartbeat':w.heartbeat(lease);result={'accepted':True}
 else:result=w.complete(lease,{'summary':'explicit process result'})
except ContractError as exc:result={'rejected':str(exc)}
print(json.dumps(result))
'''


def launch(tmp_path, store, lease, mode, nonce=''):
    (tmp_path/'lease.json').write_text(json.dumps(lease), encoding='utf-8')
    script = tmp_path/'child.py'
    script.write_text(WORKER, encoding='utf-8')
    return subprocess.Popen([sys.executable, str(script), str(tmp_path), mode],
        env=dict(os.environ, HOST_TEST_DSN=store.dsn, HOST_TEST_NONCE=nonce, PYTHONIOENCODING='utf-8'),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def await_ready(child, path):
    limit = time.monotonic() + 20
    while not path.exists() and child.poll() is None and time.monotonic() < limit:
        time.sleep(.02)
    assert path.exists(), 'Child did not reach the control barrier'
    return json.loads(path.read_text('utf-8'))


def finish(child):
    try:
        return child.communicate(timeout=35)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True)
        else:
            child.kill()
        child.communicate(timeout=10)
        raise


def evidence(name, data):
    if location := os.environ.get('ZEUS_HOST_TEST_EVIDENCE'):
        root = Path(location)
        root.mkdir(parents=True, exist_ok=True)
        (root/(name+'-'+uuid4().hex+'.json')).write_text(json.dumps({
            'scope': 'Actual process/service interruption only; NOT host sleep/reboot/VM resume/clock step',
            'observed_at': datetime.now(timezone.utc).isoformat(), **data}, indent=2)+'\n', encoding='utf-8')


def test_native_suspended_worker_cannot_commit_after_deadline(isolated_pgstore, tmp_path):
    store = isolated_pgstore
    w = Workflow(store, organization())
    message = assignment()
    due = datetime.now(timezone.utc) + timedelta(seconds=6)
    message['when']['deadline'] = due.isoformat()
    w.submit(message)
    lease = w.claim('worker:implementation', 'native-paused-owner')
    nonce = uuid4().hex
    child = launch(tmp_path, store, lease, 'suspend', nonce)
    handle, suspended, api = None, False, None
    try:
        ready = await_ready(child, tmp_path/'ready.json')
        assert ready['nonce'] == nonce and ready['ppid'] in {os.getpid(), child.pid}
        if os.name == 'nt':
            from ctypes import wintypes
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            api.OpenThread.restype = wintypes.HANDLE
            for name in ('GetProcessIdOfThread', 'SuspendThread', 'ResumeThread'):
                fn = getattr(api, name)
                fn.argtypes, fn.restype = [wintypes.HANDLE], wintypes.DWORD
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = api.OpenThread(0x0802, False, ready['thread'])
            assert handle and api.GetProcessIdOfThread(handle) == ready['pid']
            assert api.SuspendThread(handle) == 0
        else:
            assert ready['pid'] == child.pid
            os.kill(child.pid, signal.SIGSTOP)
            pid, status = os.waitpid(child.pid, os.WUNTRACED)
            assert pid == child.pid and os.WIFSTOPPED(status)
        suspended = True
        (tmp_path/'go').write_text('resume after deadline', encoding='utf-8')
        while datetime.now(timezone.utc) <= due + timedelta(seconds=.2):
            time.sleep(.05)
        assert child.poll() is None
        if api:
            assert api.ResumeThread(handle) == 1
        else:
            os.kill(child.pid, signal.SIGCONT)
        suspended = False
        stdout, stderr = finish(child)
        assert child.returncode == 0, stderr.decode('utf-8')
        assert 'rejected' in json.loads(stdout)
        with store.transaction() as tx:
            row = tx.get('tasks', lease['id'])
            assert row['status'] in {'expired', 'blocked'} and row['result'] is None
            assert len(tx.scan('execution_time_events')) == len(tx.scan('execution_notices')) == 1
            reason = tx.scan('execution_time_events')[0]['reason']
            assert reason in {'deadline_exceeded', 'ClockDiscontinuity'}
        observer = launch(tmp_path, store, lease, 'heartbeat')
        observed, stderr = finish(observer)
        assert observer.returncode == 0 and 'rejected' in json.loads(observed)
        evidence('native-pause', {'platform': sys.platform, 'worker_pid': ready['pid'],
                 'native_thread': ready['thread'], 'deadline': due.isoformat(),
                 'observed_disposition': reason, 'result_committed': False})
    finally:
        (tmp_path/'go').write_text('cleanup', encoding='utf-8')
        if suspended:
            api.ResumeThread(handle) if api else os.kill(child.pid, signal.SIGCONT)
        if handle:
            api.CloseHandle(handle)
        if child.poll() is None:
            finish(child)


@pytest.fixture
def disposable_service(tmp_path):
    if os.environ.get('ZEUS_TEST_DOCKER') != '1':
        pytest.skip('Explicit disposable Docker verification required')
    service = VerificationServices(tmp_path/'services', FileArtifacts(tmp_path/'artifacts'))
    with service as endpoints:
        store = PostgresStore(endpoints['database_url'])
        store.migrate()
        yield service, store


def refresh_test_endpoint(service, store):
    # Fixture endpoint discovery only; not a claim of production auto-reconnection.
    endpoint = service._command('port', 'postgres', '5432')
    assert endpoint.startswith('127.0.0.1:')
    store.dsn = make_conninfo(store.dsn, port=endpoint.rsplit(':', 1)[1])


@pytest.mark.parametrize('pause_seconds', [2, 12])
def test_postgres_pause_is_not_a_clock_step(disposable_service, tmp_path, pause_seconds):
    service, store = disposable_service
    w = Workflow(store, organization())
    w.submit(assignment())
    lease = w.claim('worker:implementation', 'owner', lease_seconds=120)
    child = None
    try:
        service._command('pause', 'postgres')
        child = launch(tmp_path, store, lease, 'heartbeat')
        time.sleep(pause_seconds)
    finally:
        service._command('unpause', 'postgres')
    stdout, _ = finish(child)
    if child.returncode:
        assert not stdout  # An unavailable connection is not a successful operation.
    else:
        assert json.loads(stdout) == {'accepted': True}
    retry = launch(tmp_path, store, lease, 'heartbeat')
    retried, stderr = finish(retry)
    assert retry.returncode == 0, stderr.decode('utf-8')
    assert json.loads(retried) == {'accepted': True}
    with store.transaction() as tx:
        assert tx.get('tasks', lease['id'])['status'] == 'running'
        assert not tx.scan('execution_time_events') and not tx.scan('execution_notices')
    evidence('pg-pause', {'pause_seconds': pause_seconds, 'initial_exit': child.returncode,
             'retry_exit': retry.returncode, 'false_clock_events': 0})


def test_postgres_restart_rolls_back_unconfirmed_failure(disposable_service, tmp_path):
    service, store = disposable_service
    w = Workflow(store, organization())
    w.submit(assignment())
    lease = w.claim('worker:implementation', 'owner', lease_seconds=120)
    original_port = conninfo_to_dict(store.dsn)['port']
    original_container = service._command('ps', '--all', '--quiet', 'postgres')
    assert original_container
    child = launch(tmp_path, store, lease, 'uncommitted')
    try:
        await_ready(child, tmp_path/'ready.json')
        service._command('stop', '--timeout', '5', 'postgres')
        (tmp_path/'go').write_text('try commit against stopped server', encoding='utf-8')
        stdout, _ = finish(child)
        assert child.returncode != 0 and not stdout
    finally:
        # Compose 2.x start has no --wait; retain the existing container explicitly.
        service._command('up', '-d', '--no-recreate', '--wait', 'postgres')
        refresh_test_endpoint(service, store)
        if child.poll() is None:
            (tmp_path/'go').write_text('cleanup', encoding='utf-8')
            finish(child)
    assert service._command('ps', '--all', '--quiet', 'postgres') == original_container
    with store.transaction() as tx:
        assert tx.get('tasks', lease['id']) == lease
        assert not tx.scan('execution_failures') and not tx.scan('outbox')
    observer = launch(tmp_path, store, lease, 'heartbeat')
    stdout, stderr = finish(observer)
    assert observer.returncode == 0, stderr.decode('utf-8')
    assert json.loads(stdout) == {'accepted': True}
    evidence('pg-restart', {'unconfirmed_exit': child.returncode, 'rollback_verified': True,
             'original_port': original_port, 'restored_port': conninfo_to_dict(store.dsn)['port'],
             'storage': 'Dedicated VerificationServices named database volume',
             'retained_container_id':original_container,
             'endpoint_scope': 'Fixture rediscovery, not production automatic repair'})


def test_postgres_outage_cannot_extend_durable_deadline(disposable_service, tmp_path):
    service, store = disposable_service
    w = Workflow(store, organization())
    message = assignment()
    due = datetime.now(timezone.utc) + timedelta(seconds=3)
    message['when']['deadline'] = due.isoformat()
    w.submit(message)
    lease = w.claim('worker:implementation', 'owner')
    original_container = service._command('ps', '--all', '--quiet', 'postgres')
    assert original_container
    try:
        service._command('stop', '--timeout', '5', 'postgres')
        child = launch(tmp_path, store, lease, 'complete')
        stdout, _ = finish(child)
        assert child.returncode != 0 and not stdout
        while datetime.now(timezone.utc) <= due:
            time.sleep(.05)
    finally:
        # Compose 2.x start has no --wait; retain the existing container explicitly.
        service._command('up', '-d', '--no-recreate', '--wait', 'postgres')
        refresh_test_endpoint(service, store)
    assert service._command('ps', '--all', '--quiet', 'postgres') == original_container
    observer = launch(tmp_path, store, lease, 'complete')
    stdout, stderr = finish(observer)
    assert observer.returncode == 0, stderr.decode('utf-8')
    assert 'rejected' in json.loads(stdout)
    with store.transaction() as tx:
        row = tx.get('tasks', lease['id'])
        assert row['status'] == 'expired' and row['result'] is None
        assert len(tx.scan('execution_time_events')) == len(tx.scan('execution_notices')) == 1
        assert tx.scan('execution_time_events')[0]['reason'] == 'deadline_exceeded'
    evidence('pg-outage-deadline', {'unavailable_exit':child.returncode,
             'after_restart_exit':observer.returncode, 'result_committed':False,
             'deadline':due.isoformat(), 'disposition':'deadline_exceeded',
             'retained_container_id':original_container})


def test_host_probe_never_falls_back_to_public_tasks(disposable_service, monkeypatch):
    _, store = disposable_service
    monkeypatch.setenv('ZEUS_DATABASE_URL', store.dsn)
    monkeypatch.setenv('HARNESS_DATABASE_URL', store.dsn)
    api = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/host_cycle.py'))
    public = Workflow(store, organization())
    public.submit(assignment())  # Canary in this disposable database, never the real ledger.
    with store.transaction() as tx:
        before = tx.records()
    identity = uuid4().hex
    state = {'run':identity, 'schema':'host_probe_'+identity}
    with psycopg.connect(store.dsn) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(state['schema'])))
    try:
        probe = api['workflow'](state)
        probe.store.migrate()
        with psycopg.connect(probe.store.dsn) as conn:
            conn.execute('DROP TABLE documents')
        with pytest.raises(psycopg.errors.UndefinedTable):
            probe.claim('worker:implementation', 'must-not-claim-public-canary')
        with store.transaction() as tx:
            assert tx.records() == before
    finally:
        api['remove_probe_schema'](state)
    evidence('probe-schema-boundary', {'missing_probe_table_rejected':True,
             'public_canary_unchanged':True, 'schema_removed':True})
