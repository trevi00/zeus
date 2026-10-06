"""Explicit fault inputs; native process tests do not simulate a model provider."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_app_server import failure, finish, replay
from test_executor_research import setup as setup
from test_workflow import assignment

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.execution_output import completed_output, evidence_json
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import canonical, digest

SCHEMA = {'type': 'object', 'properties': {'summary': {'type': 'string'}},
          'required': ['summary'], 'additionalProperties': False}


@pytest.mark.parametrize('text,reason', [('', 'empty'), (' \n\t', 'empty'), ('{', 'invalid_json'),
    ('{}', 'schema_mismatch'), ('null', 'schema_mismatch'), ('[]', 'schema_mismatch'),
    ('{"summary":7}', 'schema_mismatch'), ('{"summary":"ok","extra":1}', 'schema_mismatch'),
    ('{"summary":NaN}', 'invalid_json'), ('{"summary":1e999}', 'invalid_json'),
    ('{"summary":"first","summary":"second"}', 'invalid_json'),
    ('{"summary":"\\ud800"}', 'invalid_json'), ('\ud800', 'invalid_json'), (None, 'invalid_text')])
def test_output_faults_are_runner_observed_and_preserve_raw_text(text, reason):
    result = completed_output(text, SCHEMA)
    assert result['answer'] is None and result['model_answer_text'] == text
    assert result['failure']['output_reason'] == reason
    assert result['failure']['cause'] == 'codex-output-' + reason.replace('_', '-')


def test_valid_empty_field_is_not_an_invented_business_failure():
    assert completed_output('{"summary":""}', SCHEMA)['answer'] == {'summary': ''}


def test_normal_utf8_keeps_content_address_and_recovery_read_budget(tmp_path):
    value = {'summary': '\uac80' * 40000}
    body = evidence_json(value)
    assert body == canonical(value)
    artifacts = FileArtifacts(tmp_path / 'artifacts')
    receipt = artifacts.put(body, 'explicit-budget-input')
    assert receipt['ref'] == 'sha256:' + digest(value)
    assert artifacts.text(receipt['ref'], 131072) == body


def test_interrupted_surrogate_is_available_to_next_handoff(setup, monkeypatch):
    s, calls, packets = setup, [], []
    lease = s.executor.workflow.claim('worker:github', 'handoff-owner')

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, *args, **kwargs):
            packets.append(json.loads(prompt))
            events = finish('\ud800', 'interrupted') if not calls else finish()
            calls.append(1)
            result, *_ = replay(monkeypatch, events)
            for event in result['events']:
                kwargs['on_event'](event)
            return result

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    result = s.executor._run('worker:github', lease['id'], 'Explicit unit handoff', {},
        str(s.executor.git.repository), {'type': 'object', 'properties': {'accepted': {'type': 'boolean'}},
        'required': ['accepted']}, lease=lease)
    assert result['accepted'] is True and len(calls) == 2
    ref = packets[1]['required']['recovery']['sources']['completed']['ref']
    events = json.loads(s.artifacts.text(ref, 131072))
    assert events[0]['params']['item']['text'] == '\ud800'
    with s.service.store.transaction() as tx:
        assert tx.get('sessions', 'worker:github')['generation'] == 2


def test_output_failure_retains_observed_context_threshold(monkeypatch):
    usage = {'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'thread', 'turnId': 'turn',
             'tokenUsage': {'modelContextWindow': 100, 'last': {'totalTokens': 80}}}}
    result, requests, *_ = replay(monkeypatch, [usage, *finish('{')])
    assert result['failure'] and result['rotate']
    assert any(method == 'turn/interrupt' for method, _ in requests)


@pytest.mark.parametrize('text', ['', '{', '{}', '\ud800'])
def test_transport_unit_fault_uses_existing_failure_shape(monkeypatch, text):
    result, _, observed, _ = replay(monkeypatch, finish(text))
    assert result['failure'] and result['answer'] is None
    assert result['model_answer_text'] == text and result['events'] == observed
    assert result['thread_id'] == 'thread' and result['turn_id'] == 'turn'
    assert result['rotate'] is False and result['interrupted'] is False
    blocked, *_ = replay(monkeypatch, [failure(), *finish(text)])
    assert blocked['inspection_blocked'] and 'failure' not in blocked


@pytest.mark.parametrize('text', ['{', '\ud800'])
@pytest.mark.parametrize('cleanup', [False, True])
def test_executor_unit_wiring_persists_output_failure_before_retry(setup, monkeypatch, cleanup, text):
    s = setup

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args):
            if cleanup:
                raise OSError('Explicit cleanup failure fixture')
        def run(self, *args, **kwargs):
            result, *_ = replay(monkeypatch, finish(text))
            for event in result['events']:
                kwargs['on_event'](event)
            return result

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    row = s.executor.execute_one('worker:github')
    assert row['status'] == 'retry' and row['failure']['output_reason'] == 'invalid_json'
    body = s.artifacts.document(row['failure']['execution_ref'])
    assert body['model_answer_text'] == text and body['events']
    assert ('cleanup_error' in body) == cleanup
    assert row['attempt_outcomes'][0]['failure'] == row['failure']
    with s.service.store.transaction() as tx:
        progress = tx.scan('execution_progress')
        assert progress
        event = s.artifacts.document(progress[0]['last_record'])['event']
        assert event['params']['item']['text'] == text


@pytest.mark.parametrize('reject_write', [False, True])
@pytest.mark.parametrize('text,reason', [('', 'empty'), ('{', 'invalid_json'), ('{}', 'schema_mismatch'),
                                       ('\ud800', 'invalid_json')])
def test_native_process_output_failure_replay_and_reclaim_preserve_state(
        isolated_pgstore, tmp_path, text, reason, reject_write):
    store = isolated_pgstore
    workflow = Workflow(store, organization())
    root = tmp_path / 'project with spaces' / '\uac80\uc99d'
    root.mkdir(parents=True)
    artifacts = FileArtifacts(root / 'artifacts')
    retrospective_ref = artifacts.put('Retrospective evidence retained across failure', 'explicit-test-input')['ref']
    task = workflow.submit(assignment('research', 'worker:github'))
    preserved = {'project_context': {'id': 'project', 'cwd': str(root)},
                 'retrospective': {'seen': 3, 'target': 5, 'ref': retrospective_ref}}
    with store.transaction() as tx:
        row = tx.get('tasks', task['id'])
        row.update(preserved)
        tx.put('tasks', row['id'], row)
    lease = workflow.claim('worker:github', 'native-owner')
    input_path, lease_path = root / 'output.json', root / 'lease.json'
    # JSON escaping faithfully transports a lone surrogate through a UTF-8 file.
    input_path.write_text(json.dumps(text, ensure_ascii=True), encoding='utf-8')
    lease_path.write_text(json.dumps(lease), encoding='utf-8')
    script = root / 'process.py'
    script.write_text('''
import json,os,sys
from pathlib import Path
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.execution_output import completed_output,persist_result
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ExecutionFailure
root=Path.cwd();w=Workflow(PostgresStore(os.environ['OUTPUT_TEST_DSN']),organization())
if sys.argv[1]=='claim':
    row=w.claim('worker:github','restarted-native-owner')
else:
    lease=json.loads((root/'lease.json').read_text('utf-8'))
    schema={'type':'object','properties':{'summary':{'type':'string'}},'required':['summary'],'additionalProperties':False}
    result={**completed_output(json.loads((root/'output.json').read_text('utf-8')),schema),
            'thread_id':None,'turn_id':None,'events':[],
            'origin':'explicit fault input; no provider or model execution'}
    try:
        persist_result(FileArtifacts(root/'artifacts'),result,key=lease['id'],agent=lease['agent'],
                       lease=lease,basis_revision=None,context_ref=None)
    except ExecutionFailure as error:
        row=w.fail_execution(lease,error)
    else:raise SystemExit('Invalid output accepted')
print(json.dumps(row))
''', encoding='utf-8')
    processes = []
    if reject_write:
        import psycopg
        with psycopg.connect(store.dsn) as conn:
            conn.execute("""CREATE FUNCTION reject_output_failure() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.bucket='execution_failures' THEN
                    RAISE EXCEPTION 'explicit output failure write rejection';
                END IF; RETURN NEW; END $$""")
            conn.execute('CREATE TRIGGER reject_output_failure BEFORE INSERT OR UPDATE ON documents '
                         'FOR EACH ROW EXECUTE FUNCTION reject_output_failure()')
    operations = ('reject', 'fail', 'fail', 'claim') if reject_write else ('fail', 'fail', 'claim')
    for operation in operations:
        child = subprocess.Popen([sys.executable, str(script), operation], cwd=root,
            env=dict(os.environ, OUTPUT_TEST_DSN=store.dsn, PYTHONIOENCODING='utf-8'),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            stdout, stderr = child.communicate(timeout=40)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate(timeout=10)
            raise
        if operation == 'reject':
            assert child.returncode != 0 and not stdout
            assert b'explicit output failure write rejection' in stderr
            processes.append({'pid': child.pid, 'operation': operation, 'exit_code': child.returncode})
            with store.transaction() as tx:
                assert tx.get('tasks', task['id']) == lease
                assert not tx.scan('execution_failures') and not tx.scan('outbox')
            with psycopg.connect(store.dsn) as conn:
                conn.execute('DROP TRIGGER reject_output_failure ON documents')
                conn.execute('DROP FUNCTION reject_output_failure()')
            continue
        assert child.returncode == 0, stderr.decode('utf-8')
        row = json.loads(stdout)
        processes.append({'pid': child.pid, 'operation': operation, 'exit_code': child.returncode,
                          'task_id': row['id'], 'attempt': row['attempt'], 'status': row['status']})
        assert row['id'] == task['id'] and all(row[k] == value for k, value in preserved.items())
        assert row['message'] == task['message'] and row['input_hash'] == task['input_hash']
        assert len(row['attempt_outcomes']) == 1
        assert row['failure']['output_reason'] == reason
        body = artifacts.document(row['failure']['execution_ref'])
        assert body['model_answer_text'] == text and body['thread_id'] is None
        assert body['output_schema'] == SCHEMA and digest(body['output_schema']) == row['failure']['schema_hash']
        if operation == 'fail':
            assert row['attempt'] == 1 and row['status'] == 'retry'
        else:
            assert row['attempt'] == 2 and row['generation'] == lease['generation'] + 1
    with store.transaction() as tx:
        assert len(tx.scan('execution_failures')) == len(tx.scan('execution_notices')) == 1
        assert all(r['message']['type'] == 'execution.notice' for r in tx.scan('outbox'))
    evidence = os.environ.get('ZEUS_OUTPUT_TEST_EVIDENCE')
    if evidence:
        from uuid import uuid4
        path = Path(evidence)
        path.mkdir(parents=True, exist_ok=True)
        (path / (uuid4().hex + '.json')).write_text(json.dumps({'scope': 'Actual child processes, UTF-8 files, '
            'PG and artifacts; explicit fault inputs, no model/provider run', 'reason': reason,
            'processes': processes, 'preservation_verified': True, 'failure_receipts': 1}, indent=2) + '\n',
            encoding='utf-8')
