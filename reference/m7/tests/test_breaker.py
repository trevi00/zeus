"""FA-020: breaker admission is a committed, generation-fenced transition (INV-BREAKER-001).

The upstream composite breaker returned an admission bool with no owner or generation, kept
admitting when its state file could not be written, let an old holder's success close a slot
another holder had reclaimed, folded histories in input order and took booleans as thresholds.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from test_app_server import finish, replay
from test_executor_research import setup as setup
from test_workflow import assignment

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.breaker import (
    BUCKET,
    DEFAULT_POLICY,
    EVENTS,
    NOTICES,
    Breaker,
    breaker_key,
    result_of,
    result_of_exception,
)
from codex_harness.application.observations import PostExecutionRecordFailure
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.breaker import decide, fold_failures, parse_policy, parse_state
from codex_harness.domain.model import ContractError

SCHEMA = {'type': 'object', 'properties': {'accepted': {'type': 'boolean'}}, 'required': ['accepted']}
T0 = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
KEY = breaker_key('codex-app-server', 'implementation')


def backend_store(backend, request):
    return MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')


def lease(store, owner='owner-1', agent='worker:implementation', seconds=60):
    workflow = Workflow(store, organization())
    workflow.submit(assignment(agent=agent))
    return workflow.claim(agent, owner, lease_seconds=seconds)


def policy(**changes):
    return {**DEFAULT_POLICY, **changes}


def test_policy_is_validated_on_read_with_types_and_cross_field_bounds():
    parsed = parse_policy(policy())
    assert parsed['failure_threshold'] == 3 and parsed['policy_hash']
    bad = [({'failure_threshold': True}, 'failure_threshold must be an integer'),  # bool is not a count
           ({'failure_threshold': 0}, 'failure_threshold'), ({'failure_threshold': '3'}, 'failure_threshold'),
           ({'window_seconds': 0}, 'window_seconds'), ({'window_seconds': -5}, 'window_seconds'),
           ({'cooldown_seconds': float('nan')}, 'cooldown_seconds'), ({'cooldown_seconds': float('inf')}, 'cooldown_seconds'),
           ({'version': 99}, 'Unknown breaker policy version'), ({'version': None}, 'Unknown breaker policy version'),
           ({'failure_threshold': 60, 'max_history': 50}, 'cannot exceed the retained history'),
           ({'probe_ttl_seconds': 700, 'window_seconds': 600}, 'cannot exceed the failure window'),
           ({'revision': 'latest'}, 'Policy revision'), ({'revision': 'A' * 40}, 'Policy revision')]
    for change, match in bad:
        with pytest.raises(ContractError, match=match):
            parse_policy(policy(**change))
    with pytest.raises(ContractError, match='exactly'):
        parse_policy({**policy(), 'extra': 1})
    with pytest.raises(ContractError, match='exactly'):
        parse_policy({k: v for k, v in policy().items() if k != 'max_history'})


def test_keys_are_typed_identities_not_composed_paths():
    assert breaker_key('a-b', 'c') != breaker_key('a', 'b-c') and breaker_key('a', 'b') == breaker_key('a', 'b')
    for provider, scope in (('OpenAI', 'x'), ('open ai', 'x'), ('a/b', 'x'), ('', 'x'), ('a', '..'), ('a', 'C:\\repo')):
        with pytest.raises(ContractError, match='lowercase token'):
            breaker_key(provider, scope)
    assert breaker_key('codex-app-server', 'design').startswith('breaker:') and '/' not in KEY


def test_failure_history_folds_over_unique_events_by_time_not_input_order():
    a = {'id': 'a', 'at': (T0 - timedelta(seconds=30)).isoformat()}
    b = {'id': 'b', 'at': (T0 - timedelta(seconds=20)).isoformat()}
    old = {'id': 'old', 'at': (T0 - timedelta(seconds=900)).isoformat()}
    assert [f['id'] for f in fold_failures([b, a, old], T0, 600)] == ['a', 'b']
    assert fold_failures([a, b, a, b, a], T0, 600) == fold_failures([a, b], T0, 600)
    assert fold_failures([old], T0, 600) == []
    with pytest.raises(ContractError, match='failure.at'):
        fold_failures([{'id': 'x', 'at': 200}], T0, 600)


def test_state_records_are_validated_and_decisions_are_pure():
    p = parse_policy(policy(cooldown_seconds=120, probe_ttl_seconds=300))
    closed = {'id': KEY, 'state': 'closed', 'generation': 0, 'failures': [], 'opened_at': None, 'reservation': None}
    assert decide(parse_state(closed), T0, p) == ('admit', 'closed')
    opened = {**closed, 'state': 'open', 'opened_at': T0.isoformat(), 'generation': 1}
    assert decide(opened, T0 + timedelta(seconds=119), p)[0] == 'refuse'
    assert decide(opened, T0 + timedelta(seconds=120), p)[0] == 'probe'
    reservation = {'owner': 'o', 'task_id': 't', 'generation': 1, 'attempt': 1, 'breaker_generation': 2,
                   'expires_at': (T0 + timedelta(seconds=300)).isoformat()}
    half = {**closed, 'state': 'half_open', 'generation': 2, 'reservation': reservation}
    assert decide(half, T0 + timedelta(seconds=299), p) == ('refuse', 'probe in flight')
    assert decide(half, T0 + timedelta(seconds=300), p)[0] == 'reclaim'
    assert decide({**half, 'reservation': None}, T0, p)[0] == 'probe'
    corrupt = [{**closed, 'failures': None}, {**closed, 'failures': 'many'}, {**closed, 'generation': True},
               {**closed, 'generation': float('nan')}, {**closed, 'state': 'CLOSED'}, {**closed, 'state': 'true'},
               {**closed, 'opened_at': 0}, {**closed, 'reservation': {'owner': 'x'}},
               {**closed, 'failures': [{'id': '', 'at': T0.isoformat()}]}, 'closed', None,
               {**closed, 'state': 'closed', 'reservation': reservation}]
    for row in corrupt:
        with pytest.raises(ContractError):
            parse_state(row)


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_single_probe_slot_is_fenced_by_generation(backend, request):
    store = backend_store(backend, request)
    breaker = Breaker(store, policy(failure_threshold=2, cooldown_seconds=60, probe_ttl_seconds=30, window_seconds=600))
    first = lease(store)
    t = T0
    token = breaker.admit(KEY, first, now=t)
    assert token['probe'] is False and token['generation'] == 0
    assert breaker.report(token, 'failure', now=t)['state'] == 'closed'
    second = breaker.admit(KEY, first, now=t + timedelta(seconds=1))
    assert breaker.report(second, 'failure', now=t + timedelta(seconds=1)) == {'applied': True, 'state': 'open', 'generation': 1}
    with pytest.raises(ContractError, match='refuses admission.*open until'):
        breaker.admit(KEY, first, now=t + timedelta(seconds=30))
    # Cooldown elapsed: exactly one probe slot, reserved for its holder.
    probe = breaker.admit(KEY, first, now=t + timedelta(seconds=61))
    assert probe['probe'] is True and probe['generation'] == 2
    other = lease(store, owner='owner-2', agent='worker:github')
    with pytest.raises(ContractError, match='probe in flight'):
        breaker.admit(KEY, other, now=t + timedelta(seconds=70))
    # The holder's TTL expires: another holder reclaims the slot with a new generation.
    reclaimed = breaker.admit(KEY, other, now=t + timedelta(seconds=92))
    assert reclaimed['probe'] and reclaimed['generation'] == 3 and reclaimed['task_id'] == other['id']
    # The old holder's late success is stale: it cannot close the slot the new holder owns.
    stale = breaker.report(probe, 'success', now=t + timedelta(seconds=93))
    assert stale == {'applied': False, 'reason': 'stale_generation', 'state': 'half_open', 'generation': 3}
    # Review counterexample (PR #52): the current holder's success after its own TTL expired, with no
    # reclaim in between (same generation), must not close the breaker either.
    late = breaker.report(reclaimed, 'success', now=t + timedelta(seconds=92 + 31))
    assert late == {'applied': False, 'reason': 'probe_expired', 'state': 'half_open', 'generation': 3}
    assert breaker.inspect(KEY, now=t + timedelta(seconds=92 + 31))['state'] == 'half_open'
    forged = breaker.report({**reclaimed, 'owner': 'someone-else'}, 'success', now=t + timedelta(seconds=93))
    assert forged['applied'] is False and forged['reason'] == 'probe_other_holder'
    assert breaker.inspect(KEY, now=t + timedelta(seconds=93))['state'] == 'half_open'
    # Unknown (interrupted, cancelled) releases the slot without a verdict; the next probe is fresh.
    assert breaker.report(reclaimed, 'unknown', now=t + timedelta(seconds=94))['state'] == 'half_open'
    released = breaker.report(reclaimed, 'success', now=t + timedelta(seconds=94))
    assert released == {'applied': False, 'reason': 'probe_released', 'state': 'half_open', 'generation': 3}, 'a released token settles nothing'
    again = breaker.admit(KEY, first, now=t + timedelta(seconds=95))
    assert again['probe'] and again['generation'] == 4
    assert breaker.report(again, 'success', now=t + timedelta(seconds=96)) == {'applied': True, 'state': 'closed', 'generation': 5}
    with store.transaction() as tx:
        kinds = [e['kind'] for e in sorted(tx.scan(EVENTS), key=lambda e: e['sequence'])]
    assert kinds.count('stale_result') == 4 and kinds.count('probe_reserved') == 3
    report = breaker.inspect(KEY, now=t + timedelta(seconds=97))
    assert report['state'] == 'closed' and report['admits'] and 'never acceptance' in report['authority']


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_concurrent_holders_get_one_probe_slot(backend, request):
    store = backend_store(backend, request)
    breaker = Breaker(store, policy(failure_threshold=1, cooldown_seconds=1, probe_ttl_seconds=60))
    holder = lease(store)
    breaker.report(breaker.admit(KEY, holder, now=T0), 'failure', now=T0)
    assert breaker.inspect(KEY, now=T0)['state'] == 'open'

    def attempt(index):
        try:
            return breaker.admit(KEY, {**holder, 'lease_owner': f'racer-{index}'}, now=T0 + timedelta(seconds=2))
        except ContractError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(8)))
    tokens = [r for r in results if isinstance(r, dict)]
    assert len(tokens) == 1 and all('probe in flight' in r for r in results if isinstance(r, str))
    with store.transaction() as tx:
        state = tx.get(BUCKET, KEY)
    assert state['state'] == 'half_open' and state['reservation']['task_id'] == tokens[0]['task_id']
    assert state['reservation']['breaker_generation'] == tokens[0]['generation']


class FailingCommitStore:
    """A store whose transaction cannot commit: admission must not be granted."""

    def __init__(self, inner):
        self.inner = inner

    @contextmanager
    def transaction(self):
        with self.inner.transaction() as tx:
            yield tx
            raise OSError('Explicit commit failure fixture')


def test_storage_failure_never_returns_an_admission():
    store = MemoryStore()
    breaker = Breaker(store, policy(failure_threshold=1, cooldown_seconds=1))
    holder = lease(store)
    breaker.report(breaker.admit(KEY, holder, now=T0), 'failure', now=T0)
    before = breaker.inspect(KEY, now=T0 + timedelta(seconds=2))
    assert before['decision'] == 'probe'
    broken = Breaker(FailingCommitStore(store), policy(failure_threshold=1, cooldown_seconds=1))
    with pytest.raises(OSError):
        broken.admit(KEY, holder, now=T0 + timedelta(seconds=2))
    after = breaker.inspect(KEY, now=T0 + timedelta(seconds=2))
    assert after['state'] == 'open' and after['reservation'] is None, 'no admission, no reservation, state unchanged'
    assert breaker.admit(KEY, holder, now=T0 + timedelta(seconds=2))['probe'] is True


def test_corrupt_missing_and_unreadable_are_named_and_never_closed():
    store = MemoryStore()
    breaker = Breaker(store)
    assert breaker.inspect(KEY)['state'] == 'missing'
    holder = lease(store)
    breaker.admit(KEY, holder, now=T0)
    store.data[BUCKET, KEY]['failures'] = None
    report = breaker.inspect(KEY, now=T0)
    assert report['state'] == 'corrupt' and report['admits'] is False
    with pytest.raises(ContractError, match='requires repair'):
        breaker.admit(KEY, holder, now=T0)
    with pytest.raises(ContractError, match='requires repair'):
        breaker.admit(KEY, holder, now=T0)
    with store.transaction() as tx:
        notices = tx.scan(NOTICES)
    assert len(notices) == 1 and 'failure history' in notices[0]['reason'] and 'None' in notices[0]['excerpt']
    store.data[BUCKET, KEY]['generation'] = float('nan')
    assert breaker.inspect(KEY, now=T0)['state'] == 'corrupt'
    unreachable = Breaker(__import__('codex_harness.adapters.store', fromlist=['PostgresStore']).PostgresStore(
        'postgresql://127.0.0.1:1/zeus?connect_timeout=1'))
    assert unreachable.inspect(KEY)['state'] == 'unreadable'


def test_postgres_corruption_is_repair_required(isolated_pgstore):
    store = isolated_pgstore
    breaker = Breaker(store)
    holder = lease(store)
    breaker.admit(KEY, holder, now=T0)
    with psycopg.connect(store.dsn) as conn:
        conn.execute("UPDATE documents SET body = body || '{\"state\": \"true\", \"history\": null}' WHERE bucket=%s AND id=%s",
                     (BUCKET, KEY))
    assert breaker.inspect(KEY, now=T0)['state'] == 'corrupt'
    with pytest.raises(ContractError, match='requires repair'):
        breaker.admit(KEY, holder, now=T0)


def test_policy_write_is_validated_and_read_back():
    store = MemoryStore()
    breaker = Breaker(store)
    revision = 'b' * 40
    applied = breaker.update_policy({k: v for k, v in policy(failure_threshold=5).items() if k != 'revision'}, revision=revision)
    assert applied['applied'] and breaker.policy['failure_threshold'] == 5 and breaker.policy['revision'] == revision
    with pytest.raises(ContractError, match='failure_threshold must be an integer'):
        breaker.update_policy({k: v for k, v in policy(failure_threshold=True).items() if k != 'revision'}, revision=revision)
    assert breaker.policy['failure_threshold'] == 5, 'a refused write leaves the effective policy alone'
    holder = lease(store)
    token = breaker.admit(KEY, holder, now=T0)
    assert token['policy_revision'] == revision and token['policy_hash'] == breaker.policy['policy_hash']


def test_runner_results_map_to_breaker_verdicts(monkeypatch):
    accepted, *_ = replay(monkeypatch, finish())
    assert result_of(accepted) == 'success'
    empty, *_ = replay(monkeypatch, finish(''))
    assert result_of(empty) == 'unknown', 'a malformed answer proves the provider was reached, not that it failed'
    assert result_of({'answer': None, 'failure': {'cause': 'codex-provider-usage-limit-exceeded'}}) == 'failure'
    assert result_of({'answer': None, 'interrupted': True}) == 'unknown'
    assert result_of({'answer': None, 'inspection_blocked': True}) == 'unknown'
    assert result_of_exception(ContractError('Codex App Server timed out')) == 'failure'
    assert result_of_exception(ContractError('Stale or expired task execution')) == 'unknown'
    assert result_of_exception(OSError('disk')) == 'unknown'


def test_executor_admits_per_call_and_refuses_while_open(setup, monkeypatch):
    s = setup
    s.executor.breaker = Breaker(s.service.store, policy(failure_threshold=2, cooldown_seconds=3600))
    calls = []

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, *args, **kwargs):
            calls.append(1)
            raise ContractError('Codex App Server exited unexpectedly: fixture outage')

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    key = breaker_key('codex-app-server', 'final_validation')
    for _ in range(2):
        lease_row = s.executor.workflow.claim('worker:github', 'outage-owner')
        # INV-OBSERVATION-001: an outage after provider entry is reported with termination evidence;
        # the breaker still counts it as a failure of that call.
        with pytest.raises(PostExecutionRecordFailure, match='fixture outage') as raised:
            s.executor._run('worker:github', lease_row['id'], 'Breaker', {}, str(s.executor.git.repository), SCHEMA, lease=lease_row)
        s.executor.workflow.fail(lease_row, 'fixture outage')
        s.executor.observer.resolve_termination(raised.value.record_id, resolution='rerun', operator='test',
                                                reason='outage fixture reconciled')
    assert len(calls) == 2 and s.executor.breaker.inspect(key)['state'] == 'open'
    lease_row = s.executor.workflow.claim('worker:github', 'blocked-owner')
    with pytest.raises(ContractError, match='Breaker refuses admission'):
        s.executor._run('worker:github', lease_row['id'], 'Breaker', {}, str(s.executor.git.repository), SCHEMA, lease=lease_row)
    assert len(calls) == 2, 'an open breaker never reaches the transport'
    s.executor.workflow.fail(lease_row, 'refused')
    # A healthy call records success with its admitted generation in the evidence.
    s.executor.breaker = Breaker(s.service.store, policy(failure_threshold=2, cooldown_seconds=3600))
    with s.service.store.transaction() as tx:
        tx.put(BUCKET, key, {**tx.get(BUCKET, key), 'state': 'closed', 'opened_at': None, 'failures': [], 'reservation': None})

    class Healthy(Runtime):
        def run(self, *args, **kwargs):
            result, *_ = replay(monkeypatch, finish())
            return result

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Healthy)
    s.executor.workflow.submit(assignment(agent='worker:github'))  # the outage task exhausted its attempts
    lease_row = s.executor.workflow.claim('worker:github', 'healthy-owner')
    assert lease_row is not None
    answer = s.executor._run('worker:github', lease_row['id'], 'Breaker', {}, str(s.executor.git.repository), SCHEMA, lease=lease_row)
    assert answer['accepted'] is True
    with s.service.store.transaction() as tx:
        evidence_ref = tx.get('sessions', 'worker:github')['checkpoint']['evidence_ref']
    evidence = json.loads(s.artifacts.text(evidence_ref, 400000))
    assert evidence['breaker']['verdict'] == 'success' and evidence['breaker']['applied'] and evidence['breaker']['key'] == key
