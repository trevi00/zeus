"""Ported from SOURCE M7 `tests/test_invocation_ledger.py`: the pure request-matrix and probe tests, and (S4) the
two executor tests.

Unchanged test bodies; imports point at the target (`execution.domain.invocation`, `kernel.errors`).
The reservation/ownership ledger tests of that file (Workflow claim, capacity, settlement, concurrency) are
compared differentially instead (`compare:execution.ledger`).

PORTING NOTES (S4 ported executor suites; the M7 assertions are unchanged):
- test_executor_reserves_before_the_call_and_settles_from_the_observed_result and
  test_executor_abandons_the_reservation_when_the_transport_raises: ported. `Executor`/`Harness` are
  `m7_executor.Executor`/`Service` (a TEST shim over RunTask; construction only); the patch target is
  `m7_executor.AppServer` (M7 `codex_harness.adapters.executor.AppServer`); `finish`/`replay` come from the ported
  `test_app_server`; `InvocationLedger`/`BUCKET` and `PostExecutionRecordFailure` from their target modules.
- The `setup` fixture is a minimal local stand-in for M7 `tests/test_executor_research.setup` (S8's research suite):
  the same service, artifacts, git stub and submitted `worker:github` research task, without the research
  collection doubles these two tests never call.
"""

import json
from types import SimpleNamespace

import m7_executor
import pytest
from test_app_server import finish, replay

from codex_harness.execution.application.invocation_ledger import BUCKET
from codex_harness.execution.domain.invocation import availability, parse_request
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.message import envelope
from codex_harness.observation.application.observations import PostExecutionRecordFailure
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

SCHEMA = {'type': 'object', 'properties': {'accepted': {'type': 'boolean'}}, 'required': ['accepted']}


def test_request_matrix_refuses_unknown_and_unsupported_options_before_execution():
    accepted = parse_request('app_server', {'model': 'gpt-5-codex', 'timeout': 30, 'output_schema': SCHEMA,
                                            'read_only': False})
    assert accepted['options'] == {'model': 'gpt-5-codex', 'timeout': 30, 'output_schema': SCHEMA, 'read_only': False}
    assert set(accepted['unsupported']) == {'system', 'temperature', 'max_output_tokens', 'response_format'}
    with pytest.raises(ContractError, match='Options not supported by app_server \\(not ignored\\): max_output_tokens, temperature'):
        parse_request('app_server', {'model': 'x', 'temperature': 0.2, 'max_output_tokens': 10})
    with pytest.raises(ContractError, match='Unknown invocation options: top_p'):
        parse_request('app_server', {'model': 'x', 'top_p': 1})
    for bad in ({'model': ''}, {'model': 7}, {'timeout': 0}, {'timeout': float('nan')}, {'timeout': '30'},
                {'output_schema': {}}, {'output_schema': 'schema'}, {'read_only': 'no'}):
        with pytest.raises(ContractError):
            parse_request('app_server', bad)
    with pytest.raises(ContractError, match='Unknown invocation transport'):
        parse_request('anthropic_sdk', {'model': 'x'})
    # Explicitly null unsupported options are not "set"; they are still not applied.
    assert 'system' not in parse_request('app_server', {'system': None})['options']


def test_probe_is_never_model_readiness_or_qualification():
    assert availability({'executable': '/bin/codex', 'passed': True, 'version': '0.1.0'})['state'] == 'version_confirmed'
    assert availability({'executable': '/bin/codex', 'passed': False, 'version': ''})['state'] == 'executable_found'
    assert availability({})['state'] == availability(None)['state'] == 'executable_missing'
    for probe in ({'executable': '/bin/codex', 'passed': True, 'version': '0.1.0'}, {}):
        report = availability(probe)
        assert report['model_ready'] == 'unknown' and report['qualified'] is False


@pytest.fixture
def setup(tmp_path):
    service = m7_executor.Service(MemoryStore())
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    executor = m7_executor.Executor(service, SimpleNamespace(repository=tmp_path, _git=lambda *a, **kw: 'harness'),
                                    artifacts)
    message = envelope('task.assign', 'lead:research', 'worker:github', 'research',
                       {'source': 'github', 'intent': 'user_request'}, 'fixture')
    task = executor.workflow.submit(message)
    return SimpleNamespace(executor=executor, service=service, artifacts=artifacts, task=task)


def test_executor_reserves_before_the_call_and_settles_from_the_observed_result(setup, monkeypatch):
    s = setup
    lease = s.executor.workflow.claim('worker:github', 'invocation-owner')
    seen = {}

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, cwd, schema, timeout, **kwargs):
            with s.service.store.transaction() as tx:
                seen['during_call'] = [r['status'] for r in tx.scan(BUCKET)]
            seen['timeout'] = timeout
            result, *_ = replay(monkeypatch, finish())
            return result

    monkeypatch.setattr('m7_executor.AppServer', Runtime)
    result = s.executor._run('worker:github', lease['id'], 'Invocation ledger', {}, str(s.executor.git.repository),
                             SCHEMA, lease=lease)
    assert result['accepted'] is True and seen['during_call'] == ['reserved'], 'reserved before the transport ran'
    with s.service.store.transaction() as tx:
        rows = tx.scan(BUCKET)
    assert len(rows) == 1 and rows[0]['status'] == 'settled' and rows[0]['outcome'] == 'accepted'
    assert rows[0]['request']['options']['timeout'] == seen['timeout'] and rows[0]['request']['unsupported']
    assert rows[0]['usage']['source'] in {'unknown', 'thread/tokenUsage/updated'}
    assert rows[0]['task_id'] == lease['id'] and rows[0]['attempt'] == lease['attempt']
    with s.service.store.transaction() as tx:
        evidence_ref = tx.get('sessions', 'worker:github')['checkpoint']['evidence_ref']
    evidence = json.loads(s.artifacts.text(evidence_ref, 400000))
    assert evidence['invocation']['reservation'] == rows[0]['id'] and evidence['invocation']['outcome'] == 'accepted'
    assert evidence['invocation']['usage']['requested_model'] == evidence['model_selection']['requested_model']


def test_executor_abandons_the_reservation_when_the_transport_raises(setup, monkeypatch):
    s = setup
    lease = s.executor.workflow.claim('worker:github', 'crash-owner')

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, *args, **kwargs):
            raise OSError('Explicit transport fault fixture')

    monkeypatch.setattr('m7_executor.AppServer', Runtime)
    # INV-OBSERVATION-001: the fault happened after provider entry, so it surfaces as a
    # post-execution record failure carrying the transport error as its cause.
    with pytest.raises(PostExecutionRecordFailure) as raised:
        s.executor._run('worker:github', lease['id'], 'Invocation ledger', {}, str(s.executor.git.repository),
                        SCHEMA, lease=lease)
    assert isinstance(raised.value.cause, OSError) and raised.value.boundary == 'transport'
    with s.service.store.transaction() as tx:
        rows = tx.scan(BUCKET)
    assert len(rows) == 1 and rows[0]['status'] == 'unsettled_unknown' and rows[0]['reason'] == 'exception:OSError'
    assert rows[0]['usage'] == {'source': 'unknown', 'total_tokens': None, 'last_tokens': None}
