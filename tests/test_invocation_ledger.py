"""FA-019: a model call is a typed request, a reserved attempt and a measured, classified result (INV-INVOCATION-001).

The upstream providers dropped unsupported request fields, echoed the requested model as the
responding one, took rc0 empty output as an answer and read missing usage as zero. Here the
support matrix refuses before execution, the attempt is reserved in the transaction that proves
ownership, the outcome is named from what was observed, and unknown usage stays unknown.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_app_server import finish, replay
from test_executor_research import setup as setup
from test_workflow import assignment

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.invocation_ledger import BUCKET, InvocationLedger, reservation_key
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.invocation import (
    OUTCOMES,
    availability,
    classify_result,
    confirmed_model,
    parse_request,
    stream_hash,
    usage_record,
)
from codex_harness.domain.model import ContractError

SCHEMA = {'type': 'object', 'properties': {'accepted': {'type': 'boolean'}}, 'required': ['accepted']}


def backend_store(backend, request):
    return MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')


def running_lease(store, owner='owner-1', seconds=60, agent='worker:implementation'):
    workflow = Workflow(store, organization())
    workflow.submit(assignment(agent=agent))
    return workflow, workflow.claim(agent, owner, lease_seconds=seconds)


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


def test_results_are_classified_by_observation_and_usage_stays_unknown(monkeypatch):
    accepted, *_ = replay(monkeypatch, finish())
    assert classify_result(accepted) == 'accepted'
    empty, *_ = replay(monkeypatch, finish(''))
    assert classify_result(empty) == 'invalid_output', 'a clean exit with empty output is not an answer'
    assert classify_result({'answer': None, 'model_answer_text': '', 'events': [],
                            'interrupted': False}) == 'empty_answer'
    tool_only = {'answer': None, 'model_answer_text': '', 'interrupted': False, 'events': [
        {'method': 'item/completed', 'params': {'item': {'id': 'c1', 'type': 'commandExecution'}}}]}
    assert classify_result(tool_only) == 'tool_only'
    assert classify_result({'answer': None, 'interrupted': True, 'events': []}) == 'interrupted'
    assert classify_result({'answer': None, 'inspection_blocked': True, 'events': []}) == 'inspection_blocked'
    assert classify_result({'answer': None, 'failure': {'cause': 'codex-provider-usage-limit-exceeded'}}) == 'provider_failure'
    assert set(OUTCOMES) >= {'accepted', 'empty_answer', 'invalid_output', 'tool_only', 'interrupted',
                             'inspection_blocked', 'provider_failure'}
    # Usage: absent is unknown (never 0); present names its event source and basis.
    unknown = usage_record({'events': [], 'usage': None, 'requested_model': 'gpt-5-codex'})
    assert unknown['source'] == 'unknown' and unknown['total_tokens'] is None and unknown['basis'] is None
    assert unknown['requested_model'] == 'gpt-5-codex' and unknown['confirmed_model'] is None
    assert unknown['model_confirmation'] == 'unknown'
    measured = usage_record({'events': [], 'usage': {'total': {'totalTokens': 120}, 'last': {'totalTokens': 80}}})
    assert (measured['source'], measured['total_tokens'], measured['last_tokens'], measured['basis']) == (
        'thread/tokenUsage/updated', 120, 80, 'total')
    last_only = usage_record({'events': [], 'usage': {'modelContextWindow': 100, 'last': {'totalTokens': 80}}})
    assert (last_only['total_tokens'], last_only['basis']) == (80, 'last_only')
    assert usage_record({'events': [], 'usage': {'total': {'totalTokens': '120'}}})['source'] == 'unknown'
    # The responding model is only what the transport reported, never the request label.
    events = [{'method': 'thread/started', 'params': {'thread': {'id': 't', 'model': 'gpt-5-codex-2026'}}}]
    assert confirmed_model(events) == 'gpt-5-codex-2026' and confirmed_model([]) is None
    assert usage_record({'events': events, 'usage': None})['model_confirmation'] == 'transport_reported'
    assert stream_hash(events) == stream_hash(json.loads(json.dumps(events))) != stream_hash([])


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_reservation_is_bound_to_current_ownership_and_capacity(backend, request):
    store = backend_store(backend, request)
    workflow, lease = running_lease(store)
    ledger = InvocationLedger(store, capacity=1)
    guard = lambda tx: workflow._owned(tx, lease)  # noqa: E731
    req = parse_request('app_server', {'model': 'gpt-5-codex', 'timeout': 30})
    row = ledger.reserve(lease, request=req, budget_seconds=30, guard=guard)
    assert row['status'] == 'reserved' and row['usage'] == {'source': 'unknown', 'total_tokens': None, 'last_tokens': None}
    assert row['id'] == reservation_key('tasks', lease['id'], lease['generation'], lease['attempt'], 1)
    with pytest.raises(ContractError, match='already holds an open invocation reservation'):
        ledger.reserve(lease, request=req, budget_seconds=30, guard=guard)
    stale = {**lease, 'lease_owner': 'someone-else'}
    with pytest.raises(ContractError, match='Stale or expired'):
        ledger.reserve(stale, request=req, budget_seconds=30, guard=lambda tx: workflow._owned(tx, stale))
    with store.transaction() as tx:
        assert len(tx.scan(BUCKET)) == 1, 'a refused reservation leaves nothing'
    # Capacity is the number of open reservations, not a declared field nobody reads.
    other_workflow, other = running_lease(store, owner='owner-2', agent='worker:github')
    assert other is not None, 'a second running execution within the task policy'
    with pytest.raises(ContractError, match='capacity is reserved'):
        ledger.reserve(other, request=req, budget_seconds=30)
    ledger.settle(row['id'], outcome='accepted', usage={'source': 'thread/tokenUsage/updated', 'total_tokens': 5,
                                                        'last_tokens': 5, 'basis': 'total'})
    other_row = ledger.reserve(other, request=req, budget_seconds=30)
    assert other_row['status'] == 'reserved'
    ledger.settle(other_row['id'], outcome='interrupted',
                  usage={'source': 'unknown', 'total_tokens': None, 'last_tokens': None})
    # A second stage of the same attempt is a second invocation, in order.
    second_stage = ledger.reserve(lease, request=req, budget_seconds=30, guard=guard, stage='detail')
    assert (second_stage['invocation'], second_stage['stage']) == (2, 'detail')


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_settlement_is_idempotent_and_unknown_usage_is_never_zero(backend, request):
    store = backend_store(backend, request)
    workflow, lease = running_lease(store)
    ledger = InvocationLedger(store)
    row = ledger.reserve(lease, request={}, budget_seconds=30)
    measured = {'source': 'thread/tokenUsage/updated', 'total_tokens': 42, 'last_tokens': 42, 'basis': 'total'}
    settled = ledger.settle(row['id'], outcome='accepted', usage=measured)
    assert settled['status'] == 'settled' and settled['usage'] == measured and settled['within_budget'] is True
    assert ledger.settle(row['id'], outcome='accepted', usage=measured) == settled
    with pytest.raises(ContractError, match='Conflicting settlement'):
        ledger.settle(row['id'], outcome='empty_answer', usage=measured)
    assert ledger.reserve(lease, request={}, budget_seconds=30)['invocation'] == 2, 'a settled attempt may call again'
    with pytest.raises(ContractError, match='Unknown invocation outcome'):
        ledger.settle(row['id'], outcome='success', usage=measured)
    with pytest.raises(ContractError, match='Usage must name its source'):
        ledger.settle(row['id'], outcome='accepted', usage={'source': 'unknown', 'total_tokens': 0})
    # A second attempt after a crash: the old reservation closes as unknown, not as zero.
    ledger.abandon(reservation_key('tasks', lease['id'], lease['generation'], lease['attempt'], 2), 'test teardown')
    workflow.complete(lease, {'summary': 'done'})  # frees the execution slot, not the ledger rows
    workflow2, first = running_lease(store, owner='crash-owner', seconds=1)
    assert first is not None
    crashed = ledger.reserve(first, request={}, budget_seconds=1)
    time.sleep(1.2)
    second = workflow2.claim('worker:implementation', 'retry-owner', lease_seconds=60)
    assert (second['id'], second['attempt']) == (first['id'], 2)
    retry = ledger.reserve(second, request={}, budget_seconds=30)
    with store.transaction() as tx:
        old = tx.get(BUCKET, crashed['id'])
    assert old['status'] == 'unsettled_unknown' and old['usage']['total_tokens'] is None
    assert old['reason'] == 'superseded_by_new_attempt' and retry['status'] == 'reserved'
    abandoned = ledger.abandon(retry['id'], 'exception:OSError')
    assert abandoned['status'] == 'unsettled_unknown' and abandoned['usage']['source'] == 'unknown'
    assert ledger.abandon(retry['id'], 'again') == abandoned
    summary = ledger.summary()
    assert summary['by_status'] == {'reserved': 0, 'settled': 1, 'unsettled_unknown': 3}
    assert summary['usage_unknown'] == 3 and summary['measured_total_tokens'] == 42


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_concurrent_reservations_are_serialized_and_only_one_opens(backend, request):
    store = backend_store(backend, request)
    workflow, lease = running_lease(store)
    ledger = InvocationLedger(store, capacity=1)

    def attempt(_):
        try:
            return ledger.reserve(lease, request={}, budget_seconds=30, guard=lambda tx: workflow._owned(tx, lease))
        except ContractError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(8)))
    opened = [r for r in results if isinstance(r, dict)]
    assert len(opened) == 1 and all('already holds an open invocation reservation' in r for r in results if isinstance(r, str))
    with store.transaction() as tx:
        assert len(tx.scan(BUCKET)) == 1, 'the check and the write are one transaction'


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

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
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

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    with pytest.raises(OSError):
        s.executor._run('worker:github', lease['id'], 'Invocation ledger', {}, str(s.executor.git.repository),
                        SCHEMA, lease=lease)
    with s.service.store.transaction() as tx:
        rows = tx.scan(BUCKET)
    assert len(rows) == 1 and rows[0]['status'] == 'unsettled_unknown' and rows[0]['reason'] == 'exception:OSError'
    assert rows[0]['usage'] == {'source': 'unknown', 'total_tokens': None, 'last_tokens': None}
