"""Arm/observe a real Windows restart without initiating one or changing host time.

Uses a private schema on the configured Zeus ledger and two real heartbeat workers.
The PC restart is an operator action; process/WSL restarts cannot satisfy the gate.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
from filelock import FileLock
from psycopg import sql
from psycopg.conninfo import make_conninfo

import codex_harness
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.execution_rejections import reconcile
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import database_url, organization
from codex_harness.domain.model import ContractError, envelope

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO/'.runtime/host-cycle'


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, data):
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    pending.replace(path)


def read(path):
    return json.loads(path.read_text('utf-8'))


def command(argv):
    r = subprocess.run(argv, capture_output=True, timeout=30)
    if r.returncode:
        raise RuntimeError('Host observation command failed: '+argv[0])
    return r.stdout.decode('utf-8-sig').strip()


def host():
    if os.name != 'nt':
        raise RuntimeError('Prepare/verify must observe the native Windows host')
    boot = command(['powershell', '-NoProfile', '-NonInteractive', '-Command',
        "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')"])
    linux_boot = command(['wsl', '-d', 'Ubuntu', '--', 'cat', '/proc/sys/kernel/random/boot_id'])
    ledger = json.loads(command(['docker', 'inspect', 'zeus-ticket-ledger']))[0]
    desktop = read(Path(os.environ['APPDATA'])/'Docker/settings-store.json')
    return {'windows_boot': boot, 'wsl_boot': linux_boot, 'wall': now(),
            'process_monotonic': time.monotonic(), 'container_id': ledger['Id'],
            'container_started_at': ledger['State']['StartedAt'],
            'container_running': ledger['State']['Running'],
            'container_health': ledger['State'].get('Health', {}).get('Status'),
            'container_restart_policy':ledger['HostConfig']['RestartPolicy'],
            'docker_desktop_autostart':desktop.get('AutoStart'),
            'port_bindings': ledger['HostConfig']['PortBindings'],
            'volumes': [m.get('Name') for m in ledger['Mounts']]}


def runtime_hash():
    parts = []
    package = Path(codex_harness.__file__).resolve().parent
    for path in sorted(package.rglob('*')):
        if path.is_file() and path.suffix in {'.py','.json','.sql'}:
            parts.append(path.relative_to(package).as_posix().encode()+b'\0'+
                         path.read_bytes().replace(b'\r\n',b'\n'))
    return hashlib.sha256(b'\0'.join(parts)).hexdigest()


def workflow(state):
    schema = state['schema']
    assert schema.startswith('host_probe_') and len(schema) == 43 and schema[11:].isalnum()
    return Workflow(PostgresStore(make_conninfo(database_url(), options=f'-c search_path={schema}')),
                    organization())


def remove_probe_schema(state):
    schema = state['schema']
    assert schema == 'host_probe_'+state['run'] and len(state['run']) == 32
    assert all(c in '0123456789abcdef' for c in state['run'])
    with psycopg.connect(database_url()) as conn:
        conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


def worker(directory, key):
    state = read(directory/'state.json')
    w = workflow(state)
    lease = read(directory/('lease-'+key+'.json'))
    loaded_hash = runtime_hash()
    deadline = time.monotonic()+3*60*60
    try:
        assert loaded_hash == state['runtime_hash'], 'Worker loaded a different application runtime'
        while not (directory/'stop').exists() and time.monotonic() < deadline:
            w.heartbeat(lease, seconds=30)
            write(directory/('worker-'+key+'.json'), {'pid': os.getpid(), 'wall': now(),
                'monotonic': time.monotonic(), 'status': 'heartbeating', 'task_id': lease['id'],
                'generation': lease['generation'], 'platform': sys.platform, 'runtime_hash':loaded_hash})
            time.sleep(2)
        write(directory/('worker-'+key+'.json'), {'pid': os.getpid(), 'wall': now(),
              'status': 'stopped', 'reason': 'stop marker or three-hour lifetime reached'})
    except Exception as exc:
        write(directory/('worker-'+key+'.json'), {'pid': os.getpid(), 'wall': now(),
              'status': 'error', 'error_type': type(exc).__name__})
        raise


def seed_probe(state, directory):
    with psycopg.connect(database_url()) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(state['schema'])))
    w = workflow(state)
    w.store.migrate()
    with psycopg.connect(w.store.dsn) as conn:
        for table in ('documents','knowledge_nodes','knowledge_edges'):
            relation = conn.execute('SELECT to_regclass(%s)::oid, to_regclass(%s)::oid',
                (table,state['schema']+'.'+table)).fetchone()
            assert relation[0] is not None and relation[0] == relation[1]
    artifact = FileArtifacts(directory/'artifacts').put('Real host-cycle probe rationale', 'host-probe')['ref']
    for key, agent, action in [('windows','worker:github','research'),
                               ('wsl','worker:implementation','implement')]:
        message = envelope('task.assign', w.org.actor(agent).parent, agent, action,
                           {'objective':'Retain this isolated probe across a real Windows restart'}, state['run'])
        task = w.submit(message)
        with w.store.transaction() as tx:
            row = tx.get('tasks', task['id'])
            row['host_probe_ref'] = artifact
            tx.put('tasks', task['id'], row)
        lease = w.claim(agent, 'host-probe-'+key+'-'+state['run'], lease_seconds=30)
        write(directory/('lease-'+key+'.json'), lease)


def prepare(wsl_python):
    ROOT.mkdir(parents=True, exist_ok=True)
    if (ROOT/'current.json').exists():
        prior = ROOT/read(ROOT/'current.json')['run']
        if not (prior/'verified.json').exists() and not (prior/'cancelled.json').exists():
            raise RuntimeError('An unfinished host cycle exists; use status/verify or cancel first')
    before = host()
    assert before['container_running'] and before['container_health'] == 'healthy'
    assert before['docker_desktop_autostart'] is True, 'Enable Docker Desktop start on login before arming'
    assert before['container_restart_policy']['Name'] == 'unless-stopped'
    assert before['port_bindings']['5432/tcp'][0]['HostPort'], 'Host port must be pinned first'
    identity = uuid4().hex
    directory = ROOT/identity
    directory.mkdir()
    state = {'version':1, 'run':identity, 'schema':'host_probe_'+identity,
             'prepared_at':now(), 'before':before, 'runtime_hash':runtime_hash(),
             'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'source_commit':command(['git','-C',str(REPO),'rev-parse','HEAD']),
             'scope':'Actual Windows restart observation; NOT sleep or clock-step acceptance',
             'wsl_python':wsl_python}
    write(directory/'state.json', state)
    # Paths are explicit /mnt/c paths for this Windows/Ubuntu host, not arbitrary shells.
    linux_dir = '/mnt/'+directory.drive[0].lower()+directory.as_posix()[2:]
    linux_script = '/mnt/'+REPO.drive[0].lower()+REPO.as_posix()[2:]+'/scripts/host_cycle.py'
    processes = []
    try:
        seed_probe(state, directory)
        for key, argv in [('windows',[sys.executable,str(Path(__file__).resolve()),'worker',str(directory),'windows']),
                         ('wsl',['wsl','-d','Ubuntu','--',wsl_python,linux_script,'worker',linux_dir,'wsl'])]:
            with (directory/(key+'.stdout')).open('wb') as stdout, (directory/(key+'.stderr')).open('wb') as stderr:
                process = subprocess.Popen(argv, cwd=REPO, stdout=stdout, stderr=stderr,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
            processes.append(process)
            limit = time.monotonic()+30
            while not (directory/('worker-'+key+'.json')).exists() and process.poll() is None:
                if time.monotonic() >= limit:
                    break
                time.sleep(.1)
            observed = directory/('worker-'+key+'.json')
            if not observed.exists() or read(observed)['status'] != 'heartbeating':
                raise RuntimeError(key+' worker not ready; inspect private '+key+'.stderr')
            assert read(observed)['runtime_hash'] == state['runtime_hash']
        write(ROOT/'current.json', {'run':identity})
        return {'status':'armed_waiting_for_actual_windows_restart', 'run':identity,
                'worker_states':{key:read(directory/('worker-'+key+'.json')) for key in ('windows','wsl')},
                'automatic_restart_requested':False, 'proof_of_restart':False}
    except BaseException:
        (directory/'stop').write_text('prepare failed', encoding='utf-8')
        for process in processes:
            process.wait(timeout=15)
        remove_probe_schema(state)
        write(directory/'cancelled.json', {'at':now(), 'reason':'prepare failed; workers stopped and schema removed'})
        raise


def verify():
    directory = ROOT/read(ROOT/'current.json')['run']
    state = read(directory/'state.json')
    if (directory/'verified.json').exists():
        return read(directory/'verified.json')
    try:
        after = host()
    except (RuntimeError, subprocess.TimeoutExpired):
        return {'status':'waiting_for_host_services', 'run':state['run'], 'proof_of_boot_transition':False}
    if after['windows_boot'] == state['before']['windows_boot']:
        return {'status':'waiting_for_actual_windows_restart', 'proof_of_restart':False,
                'run':state['run'], 'reason':'Windows boot marker unchanged; no workflow writes performed'}
    assert datetime.fromisoformat(after['windows_boot']) > datetime.fromisoformat(state['prepared_at'])
    assert after['wsl_boot'] != state['before']['wsl_boot'], 'WSL restart not observed'
    assert after['container_id'] == state['before']['container_id'], 'Container replaced; inspect separately'
    assert after['port_bindings'] == state['before']['port_bindings']
    assert set(after['volumes']) == set(state['before']['volumes']) and after['container_running']
    assert after['container_health'] == 'healthy' and after['container_started_at'] != state['before']['container_started_at']
    assert runtime_hash() == state['runtime_hash'], 'Runtime changed during host cycle'
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == state['probe_sha256'], 'Host probe changed'
    w = workflow(state)
    receipts = []
    # Observe both original leases before mutating either; waiting is read-only.
    with w.store.transaction() as tx:
        for key in ('windows','wsl'):
            previous = read(directory/('lease-'+key+'.json'))
            row = tx.get('tasks', previous['id'])
            if (row['generation'] == previous['generation'] and row.get('lease_until')
                    and datetime.fromisoformat(row['lease_until']) > datetime.now(timezone.utc)):
                return {'status':'waiting_for_pre_restart_lease_expiry', 'run':state['run'], 'proof_of_restart':True}
    for key in ('windows','wsl'):
        previous = read(directory/('lease-'+key+'.json'))
        last_worker = read(directory/('worker-'+key+'.json'))
        if last_worker['status'] != 'heartbeating':
            return {'status':'inconclusive_requires_inspection', 'run':state['run'],
                    'reason':'Worker stopped or reached its three-hour lifetime before the boot observation'}
        with w.store.transaction() as tx:
            row = tx.get('tasks', previous['id'])
            assert row['message'] == previous['message'] and row['input_hash'] == previous['input_hash']
            assert row['host_probe_ref'] == previous['host_probe_ref']
        owner = 'after-actual-restart-'+state['run']
        result = {'summary':'Observed continuation after actual Windows restart',
                  'host_probe_run':state['run'], 'host_probe_key':key}
        checkpoint_path = directory/f"verified-task-{key}-{row['generation']}.json"
        if row['status'] == 'succeeded':
            assert row['result'] == result and checkpoint_path.exists()
            checkpoint = read(checkpoint_path)
            assert row['generation'] == checkpoint['generation'] and row['lease_owner'] == owner
            receipts.append(checkpoint)
            continue
        live_owned = (row['lease_owner'] == owner and row['status'] == 'running' and row.get('lease_until')
                      and datetime.fromisoformat(row['lease_until']) > datetime.now(timezone.utc))
        claimed = row if live_owned else w.claim(previous['agent'], owner, lease_seconds=120)
        if not claimed:
            return {'status':'inconclusive_requires_inspection', 'run':state['run'],
                    'task_id':previous['id'], 'reason':'Claim unavailable; no silent repair or acceptance'}
        assert claimed['id'] == previous['id']
        assert claimed['generation'] > previous['generation'] and claimed['attempt'] > previous['attempt']
        checkpoint_path = directory/f"verified-task-{key}-{claimed['generation']}.json"
        if checkpoint_path.exists():
            checkpoint = read(checkpoint_path)
            assert all(checkpoint[k] == claimed[k] for k in ('generation','attempt'))
            assert checkpoint['task_id'] == claimed['id']
            rejected = {'rejection_id':checkpoint['rejection_id']}
        else:
            try:
                w.complete(previous, {'summary':'old executor must not succeed'})
            except ContractError as exc:
                rejected = reconcile(w.store, previous, exc)
            else:
                raise AssertionError('Old execution committed')
        with w.store.transaction() as tx:
            record = tx.get('execution_rejections', rejected['rejection_id'])
            assert record['request']['reason_code'] == 'execution_identity_changed'
        checkpoint = {'task_id':claimed['id'], 'generation':claimed['generation'],
                         'attempt':claimed['attempt'], 'rejection_id':rejected['rejection_id'],
                         'prior_attempt_outcomes':claimed.get('attempt_outcomes',[]),
                         'last_worker_observation':last_worker}
        if not checkpoint_path.exists():
            write(checkpoint_path, checkpoint)
        w.complete(claimed, result)
        receipts.append(checkpoint)
    result = {'status':'verified_windows_boot_transition', 'run':state['run'],
              'before':state['before'], 'after':after, 'tasks':receipts,
              'proof_of_boot_transition':True, 'requested_operator_action':'Windows Restart',
              'restart_vs_power_on_classified':False, 'proof_of_sleep':False, 'proof_of_clock_step':False,
              'schema_retained_for_review':state['schema']}
    write(directory/'verified.json',result)
    return result


def execute(args):
    if args.command == 'prepare':
        return prepare(args.wsl_python)
    if not (ROOT/'current.json').exists():
        return {'status':'no_host_cycle_prepared', 'proof_of_boot_transition':False}
    if args.command == 'verify':
        return verify()
    directory = ROOT/read(ROOT/'current.json')['run']
    if args.command == 'cancel':
        (directory/'stop').write_text('operator cancelled host probe', encoding='utf-8')
        limit = time.monotonic()+15
        while any(read(directory/('worker-'+key+'.json')).get('status') == 'heartbeating'
                  for key in ('windows','wsl')):
            if time.monotonic() >= limit:
                return {'status':'cancel_pending_worker_exit', 'schema_removed':False}
            time.sleep(.2)
        remove_probe_schema(read(directory/'state.json'))
        write(directory/'cancelled.json', {'at':now(), 'reason':'operator cancelled; schema removed; no boot proof'})
    return {'state':read(directory/'state.json'), 'verified':(directory/'verified.json').exists(),
            'workers':{key:read(directory/('worker-'+key+'.json')) for key in ('windows','wsl')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    arm = sub.add_parser('prepare')
    arm.add_argument('--wsl-python', required=True)
    sub.add_parser('verify')
    sub.add_parser('status')
    sub.add_parser('cancel')
    job = sub.add_parser('worker')
    job.add_argument('directory', type=Path)
    job.add_argument('key', choices=['windows','wsl'])
    args = parser.parse_args()
    if args.command == 'worker':
        worker(args.directory,args.key)
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    with FileLock(str(ROOT/'control.lock'), timeout=1):
        result = execute(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
