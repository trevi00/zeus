"""Offline transport reconstructions; historical receipts are not native events."""
import ast
import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_app_server import failure as inspection_failure
from test_app_server import finish, replay
from test_executor_research import setup as setup
from test_integration import pgstore as pgstore

from codex_harness.adapters.executor import Executor
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, ExecutionFailure, envelope

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'harness_hooks/hook-ec928b6c78b06bb571eb45cb.json').read_text())


def rejected(error=None):
    return {'method': 'turn/completed', 'params': {'threadId': 'thread',
            'turn': {'id': 'turn', 'status': 'failed', 'error': error or {
                'codexErrorInfo': 'usageLimitExceeded', 'message': 'provider original'}}}}


@pytest.mark.parametrize('case', MANIFEST['cases']['reproduction'])
def test_historical_receipts_reconstructed_at_transport_boundary(monkeypatch, case):
    receipt = case['input']
    error = ast.literal_eval(receipt['error'].removeprefix('Codex turn failed: '))
    event = rejected(error)
    result, *_ = replay(monkeypatch, [event, event])
    assert result['failure']['provider_error'] == error
    assert result['failure']['cause'] == 'codex-provider-usage-limit-exceeded'
    assert result['thread_id'] == 'thread' and result['turn_id'] == 'turn'
    assert result['answer'] is None and result['events'] == [event]


@pytest.mark.parametrize('error', [None, [], 'usageLimitExceeded', {},
    {'message': 'usageLimitExceeded'}, {'codexErrorInfo': {'usageLimitExceeded': {}}},
    {'codexErrorInfo': 'rateLimitExceeded'}, {'codexErrorInfo': 'invalid_json_schema'},
    {'codexErrorInfo': 'UsageLimitExceeded'}])
def test_unconfirmed_errors_remain_generic(monkeypatch, error):
    event = rejected()
    event['params']['turn']['error'] = error
    with pytest.raises(ContractError, match='Codex turn failed'):
        replay(monkeypatch, [event])


def test_wrong_turn_success_text_and_inspection_precedence(monkeypatch):
    old = rejected()
    old['params']['turn']['id'] = 'old'
    result, *_ = replay(monkeypatch, [old, *finish('{"accepted":true,"text":"usageLimitExceeded"}')])
    assert result['answer']['accepted'] and 'failure' not in result
    result, *_ = replay(monkeypatch, [inspection_failure(), rejected()])
    assert result['inspection_blocked'] and 'failure' not in result


def install_rejection(monkeypatch, s, cleanup=False):
    calls = []

    class Runtime:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *args):
            if cleanup:
                raise OSError('cleanup failed')
        def run(self, *args, **kw):
            calls.append(1)
            result, *_ = replay(monkeypatch, [rejected()], read_only=kw['read_only'])
            return result

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    return calls


@pytest.mark.parametrize('cleanup', [False, True])
def test_failed_execution_is_persisted_and_restart_does_not_resubmit(setup, monkeypatch, cleanup):
    s = setup
    calls = install_rejection(monkeypatch, s, cleanup)
    failed = s.executor.execute_one('worker:github')
    assert failed['status'] == 'failed' and failed['attempt'] == 1
    failure = failed['failure']
    assert failure['task_id'] == s.task['id'] and failure['attempt'] == 1
    raw = s.artifacts._body(failure['execution_ref'])
    assert hashlib.sha256(raw.encode()).hexdigest() == failure['execution_ref'][7:]
    record = json.loads(raw)
    assert record['failure']['provider_error']['codexErrorInfo'] == 'usageLimitExceeded'
    assert record['events'] == [rejected()]
    if cleanup:
        assert record['cleanup_error']['message'] == 'cleanup failed'
    assert failed['attempt_outcomes'][0]['failure'] == failure
    for _ in range(3):
        assert s.executor.execute_one('worker:github') is None
        assert s.executor.workflow.submit(s.task['message']) == failed
    restarted = Executor(s.service, s.executor.git, s.artifacts, research=s.executor.research)
    assert restarted.execute_one('worker:github') is None
    assert len(calls) == 1
    with s.service.store.transaction() as tx:
        messages = [r['message'] for r in tx.scan('outbox')]
        assert len(messages) == 1 and messages[0]['type'] == 'execution.notice'
        assert messages[0]['what']['details']['status'] == 'failed'
        assert len(tx.scan('decisions_pending')) == 1
    # Fresh authorized work is permitted: there is no inferred account-wide block.
    fresh = copy.deepcopy(s.task['message'])
    fresh['message_id'] = 'fresh-authorized-assignment'
    restarted.workflow.submit(fresh)
    assert restarted.workflow.claim('worker:github', 'new-owner')['id'] == fresh['message_id']


def test_retry_history_survives_terminal_quota_failure(setup, monkeypatch):
    s = setup
    s.config['failure'] = 'shortlist'
    assert s.executor.execute_one('worker:github')['status'] == 'retry'
    install_rejection(monkeypatch, s)
    failed = s.executor.execute_one('worker:github')
    assert failed['status'] == 'failed' and failed['attempt'] == 2
    assert [r['status'] for r in failed['attempt_outcomes']] == ['failed', 'failed']
    assert 'failure' not in failed['attempt_outcomes'][0]


def test_decision_failure_has_evidence_and_never_creates_review(setup, monkeypatch):
    s = setup
    calls = install_rejection(monkeypatch, s)
    with s.service.store.transaction() as tx:
        tx.put('decisions_pending', 'decision', {'id': 'decision', 'actor': 'lead:research',
               'phase': 'diagnose', 'status': 'pending', 'attempt': 0, 'input': {},
               'message': s.task['message']})
    failed = s.executor.decide_one('lead:research')
    assert failed['status'] == 'failed'
    assert failed['failure']['task_id'] == 'decision'
    assert failed['failure']['attempt'] == 1
    assert s.executor.decide_one('lead:research') is None
    assert len(calls) == 1
    with s.service.store.transaction() as tx:
        messages = [r['message'] for r in tx.scan('outbox')]
        assert len(messages) == 1 and messages[0]['type'] == 'execution.notice'
        assert messages[0]['what']['details']['status'] == 'failed'
        assert not tx.scan('incidents')


@pytest.mark.parametrize('bucket', ['tasks', 'decisions_pending'])
@pytest.mark.parametrize('field,value', [('generation', 99), ('lease_owner', 'new-owner'),
    ('lease_until', '2000-01-01T00:00:00+00:00'), ('status', 'succeeded')])
def test_failure_writes_are_fenced(setup, bucket, field, value):
    s = setup
    task = s.executor.workflow.claim('worker:github', 'owner')
    task['_bucket'] = bucket
    with s.service.store.transaction() as tx:
        tx.put(bucket, task['id'], {**task, field: value})
    error = ExecutionFailure('codex-provider-usage-limit-exceeded', {'execution_ref': 'fixture'})
    with pytest.raises(ContractError, match='Stale'):
        s.executor.workflow.fail_execution(task, error)
    with s.service.store.transaction() as tx:
        assert tx.get(bucket, task['id'])[field] == value


def test_distinct_task_occurrences_and_authorized_recovery(setup):
    s = setup
    workflow = Workflow(s.service.store, s.service.org)
    error = ExecutionFailure('codex-provider-usage-limit-exceeded', {'execution_ref': 'fixture'})
    for index in range(2):
        message = envelope('task.assign', 'lead:research', 'worker:github', 'research', {}, 'fixture')
        if index == 0:
            message = s.task['message']
        workflow.submit(message)
        task = workflow.claim('worker:github', 'owner')
        workflow.fail_execution(task, error)
        # Persist an already expired lease; do not inject a future host clock.
        with s.service.store.transaction() as tx:
            terminal = tx.get('tasks', task['id'])
            terminal['lease_until'] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            tx.put('tasks', task['id'], terminal)
        assert workflow.claim('worker:github', 'owner') is None
        with s.service.store.transaction() as tx:
            assert tx.get('tasks', task['id']) == terminal
    unauthorized = envelope('task.assign', 'lead:improvement', 'worker:github', 'research', {}, 'fixture')
    with pytest.raises(ContractError):
        workflow.submit(unauthorized)
    recovery = envelope('task.assign', 'lead:research', 'worker:github', 'research', {}, 'fixture')
    workflow.submit(recovery)
    task = workflow.claim('worker:github', 'owner')
    assert workflow.complete(task, {'external_recovery': 'simulated'})['status'] == 'succeeded'


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get('HARNESS_INTEGRATION') != '1', reason='Local PostgreSQL required')
def test_quota_terminal_record_survives_postgres_reconnect(pgstore):
    workflow = Workflow(pgstore, organization())
    message = envelope('task.assign', 'lead:research', 'worker:github', 'research', {}, 'fixture')
    workflow.submit(message)
    task = workflow.claim('worker:github', 'owner')
    failed = workflow.fail_execution(task, ExecutionFailure('codex-provider-usage-limit-exceeded',
                                                           {'execution_ref': 'fixture'}))
    restarted = Workflow(PostgresStore(pgstore.dsn), organization())
    assert restarted.submit(message) == failed
    assert restarted.claim('worker:github', 'replacement') is None


@pytest.mark.parametrize('raw', [b'{', b'\xff', b'null', b'[]', b'"usageLimitExceeded"'])
def test_lifecycle_malformed_input_is_silent(raw):
    import subprocess
    import sys

    result = subprocess.run([sys.executable, str(ROOT / MANIFEST['spec']['script_path'])],
                            input=raw, capture_output=True, timeout=10)
    assert result.returncode == 0 and result.stdout == b'' and result.stderr == b''


def test_prompt_incident_text_cannot_classify_success(monkeypatch):
    from codex_harness.adapters.app_server import AppServer

    server = AppServer(executable='fixture')
    monkeypatch.setattr(server, 'request', lambda *a, **k: {
        'thread': {'id': 'thread'}, 'turn': {'id': 'turn'}})
    incoming = iter(finish())
    monkeypatch.setattr(server, '_receive', lambda *a, **k: next(incoming))
    result = server.run(json.dumps(rejected()), str(ROOT), {'type': 'object'})
    assert result['answer']['accepted'] and 'failure' not in result
