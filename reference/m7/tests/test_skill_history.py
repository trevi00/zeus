import copy
import hashlib
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.skill_history import prepare_history, project_identity, record_history
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.skill_history import SkillHistory
from codex_harness.domain.model import (
    ContextItem,
    ContractError,
    canonical,
    compile_context,
    digest,
)
from codex_harness.domain.skill_history import assess_history


def event(key, score=1, content='sha256:' + 'a' * 64):
    return {'id': key, 'manifest_ref': 'sha256:' + 'b' * 64,
            'context_ref': 'sha256:' + 'c' * 64,
            'top': [{'path': 'python/broad.md', 'content_ref': content, 'score': score}]}


def test_thresholds_and_content_version_scope():
    events = [event(str(i)) for i in range(3)]
    current = events[0]['top']
    assert not assess_history(events[:2], current)[0]['candidate']
    assert assess_history(events, current)[0]['candidate']
    assert not assess_history(events + [event('strong', 5)], current)[0]['candidate']
    assert assess_history(events + [event('strong', 5)], current, 'strong')[0]['candidate']
    assert assess_history(events, event('changed', content='new-body')['top']) == []
    damaged = [None, {}, {'id': 'missing', 'top': None},
               {'id': 'invalid', 'top': [None, {}, {**current[0], 'score': True}]}]
    assert assess_history(damaged + events, current) == assess_history(events, current)


def test_transactional_dedup_conflicts_retention_and_lease_guard(monkeypatch):
    store = MemoryStore()
    history = SkillHistory(store)
    monkeypatch.setattr('codex_harness.application.skill_history.MAX_EVENTS', 2)
    assert history.record('project', event('first'))
    assert not history.record('project', event('first'))
    with pytest.raises(ContractError, match='Conflicting'):
        history.record('project', event('first', 5))
    for key in ['second', 'third']:
        history.record('project', event(key))
    assert not history.record('project', event('first'))  # dedup survives hot-window eviction
    with store.transaction() as tx:
        assert [e['id'] for e in tx.get('skill_history', 'project')['events']] == ['second', 'third']
    def rejected(tx):
        raise ContractError('Stale execution')
    with pytest.raises(ContractError, match='Stale'):
        history.record('project', event('stale'), rejected)
    assert history.record('project', event('stale'))
    assert history.snapshot('other-project', event('x')['top'], '') == []


def test_atomic_body_advisory_uses_prior_samples_and_preserves_source(tmp_path):
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    raw = artifacts.put('FULL BODY', 'fixture')
    path = '.harness/skills/python/broad.md'
    record = {'path': path, 'content_ref': raw['ref'], 'score': 5,
              'base_score': 5, 'tier': 'full'}
    manifest = artifacts.put(canonical({'skills': [record]}), 'fixture-manifest')
    history = SkillHistory(store)
    for index in range(3):
        prior = event(str(index), content=raw['ref'])
        prior['top'][0]['path'] = path
        history.record(digest('project'), prior)
    selection = {'manifest_ref': manifest['ref']}
    item = ContextItem('project-skill:' + path, 'FULL BODY', raw['ref'], 'a' * 40, 18)
    items, observation = prepare_history(store, artifacts, 'project', 'agent', 'task', 'objective',
                                         selection, [item])
    assert 'historical_advisory' in items[0].body
    assert items[0].source_ref == raw['ref']
    required = {'role': 'worker', 'objective': 'verify',
                'acceptance_criteria': ['bounded'], 'policy': 'fixture'}
    plain = compile_context('worker', 'task', 'snapshot', required, [item], 10000, 0)
    budget = plain.estimated_tokens
    bounded = compile_context('worker', 'task', 'snapshot', required, items, budget, 0)
    assert bounded.evidence == []
    assert bounded.omitted[0]['id'] == item.id
    assert bounded.estimated_tokens == len(bounded.render().encode()) <= budget
    admitted = compile_context('worker', 'task', 'snapshot', required, items, 10000, 0)
    assert admitted.evidence[0]['body'] == items[0].body
    assert admitted.estimated_tokens > plain.estimated_tokens
    assert admitted.manifest_hash != plain.manifest_hash
    before = copy.deepcopy(selection)
    service, project, current = observation
    service.record(project, {**current, 'context_ref': 'context'})
    replay = {'manifest_ref': manifest['ref']}
    repeated, _ = prepare_history(store, artifacts, 'project', 'agent', 'task', 'objective', replay, [item])
    assert repeated == items and replay == before
    record['tier'] = 'pointer'
    pointer_manifest = artifacts.put(canonical({'skills': [record]}), 'pointer')
    unchanged, _ = prepare_history(store, artifacts, 'project', 'agent', 'pointer', 'objective',
        {'manifest_ref': pointer_manifest['ref']}, [item])
    assert unchanged == [item]
    del record['base_score']
    old_manifest = artifacts.put(canonical({'skills': [record]}), 'legacy-no-base')
    legacy = {'manifest_ref': old_manifest['ref']}
    _, observation = prepare_history(store, artifacts, 'project', 'agent', 'old', 'objective', legacy, [item])
    assert observation is not None and 'base_score' not in observation[2]['top'][0]


@pytest.mark.integration
def test_postgres_concurrent_duplicate_delivery_has_one_sample(isolated_pgstore):
    store = isolated_pgstore
    history = SkillHistory(store)
    project = 'test-skill-history-' + uuid4().hex
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: history.record(project, event('same')), range(8)))
    assert sum(results) == 1
    assert history.snapshot(project, event('same')['top'], '')[0]['count'] == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: history.record(project, event('distinct-' + str(i))),
                                range(12)))
    assert all(results)
    assert history.snapshot(project, event('same')['top'], '')[0]['count'] == 13
    with store.transaction() as tx:
        ids = {entry['id'] for entry in tx.get('skill_history', project)['events']}
    assert ids == {'same'} | {'distinct-' + str(i) for i in range(12)}


def test_invalid_observation_does_not_write_history():
    store = MemoryStore()
    history = SkillHistory(store)
    for field in ('manifest_ref', 'context_ref'):
        malformed = event('invalid')
        del malformed[field]
        with pytest.raises(ContractError, match='Missing skill evidence'):
            history.record('project', malformed)
    malformed = event('invalid')
    malformed['top'] = [None]
    with pytest.raises(ContractError, match='Invalid skill observation item'):
        history.record('project', malformed)
    assert store.data == {}


def test_project_identity_is_portable_and_never_inferred_from_checkout_path():
    identity = str(uuid4())
    one = SimpleNamespace(repository='/workspace/one', remote=None)
    other = SimpleNamespace(repository='/workspace/two', remote='owner/other')
    assert project_identity({'project_id': identity}, one) == project_identity(
        {'project_id': identity}, other)
    assert project_identity({'project_id': str(uuid4())}, one) != project_identity(
        {'project_id': identity}, one)
    assert project_identity({}, one) is None
    assert project_identity({}, other) == 'github:owner/other'
    assert project_identity({}, SimpleNamespace(remote='Owner/Other.git')) == 'github:owner/other'
    assert project_identity({}, SimpleNamespace(remote='https://secret@host/repo')) is None


def test_advisory_failures_degrade_but_ownership_failure_still_stops_work(tmp_path, monkeypatch):
    store = MemoryStore()
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    item = ContextItem('fixture', 'body', 'source', 'revision')
    selection = {'manifest_ref': 'sha256:' + 'f' * 64}
    items, observation = prepare_history(store, artifacts, 'project', 'agent', 'task', 'objective',
                                        selection, [item])
    assert items == [item] and observation is None
    assert selection['history']['status'] == 'unavailable'
    history = SkillHistory(store)
    observation = (history, 'project', event('record'))

    def stale(tx):
        raise ContractError('Stale ownership')

    with pytest.raises(ContractError, match='Stale ownership'):
        record_history(observation, 'context', stale)
    assert store.data == {}
    assert record_history(observation, 'context')['status'] == 'recorded'
    assert record_history(observation, 'new-context')['status'] == 'duplicate'

    def unavailable(*args, **kwargs):
        raise OSError('Do not expose secret backend details')

    monkeypatch.setattr(history, 'record', unavailable)
    assert record_history(observation, 'context') == {'status': 'unavailable', 'reason': 'OSError'}
    with pytest.raises(OSError):
        record_history(observation, 'context', stale)  # ownership could not be checked


def test_budget_omission_is_recorded_as_omitted_not_full(tmp_path):
    # Review counterexample (PR #45): a 50,000-char full skill under a 22,000-byte budget never reached
    # the packet, yet the audit counted delivery.full=1. The record now comes from the sealed packet.
    from codex_harness.adapters.skill_history import finalize_delivery, record_history
    store, artifacts = MemoryStore(), FileArtifacts(str(tmp_path / 'artifacts'))
    body = 'X' * 50_000
    raw = artifacts.put(body, 'fixture')
    path = '.harness/skills/python/huge.md'
    record = {'path': path, 'content_ref': raw['ref'], 'score': 7, 'base_score': 7, 'tier': 'full',
              'rendered_hash': 'manifest-hash', 'body_chars': len(body)}
    manifest = artifacts.put(canonical({'skills': [record]}), 'fixture-manifest')
    item = ContextItem('project-skill:' + path, body, raw['ref'], 'a' * 40, 18)
    required = {'role': 'worker', 'objective': 'verify', 'acceptance_criteria': ['bounded'], 'policy': 'fixture'}
    items, observation = prepare_history(store, artifacts, 'project', 'agent', 'task', 'objective',
                                         {'manifest_ref': manifest['ref']}, [item])
    assert observation[2]['top'][0]['tier'] == 'full' and observation[2]['evidence_stage'] == 'selected_not_compiled'
    starved = compile_context('worker', 'task', 'snapshot', required, items, 22_000, 0)
    assert starved.evidence == [] and starved.omitted[0]['id'] == item.id
    history, project, event = finalize_delivery(observation, starved)
    assert event['top'][0]['tier'] == 'omitted' and 'rendered_hash' not in event['top'][0]
    assert event['delivery'] == {'stage': 'context_compiled', 'admitted': [], 'omitted': [path]}
    assert record_history((history, project, event), 'context-1') == {'status': 'recorded'}
    report = history.audit(project)
    row = next(r for r in report['skills'] if r['path'] == path)
    assert row['delivery']['full'] == 0 and row['delivery']['omitted'] == 1
    # Admitted under a real budget: the body hash is taken from the packet, not from the manifest.
    admitted = compile_context('worker', 'task-2', 'snapshot', required, items, 200_000, 0)
    _, _, event2 = finalize_delivery(observation, admitted)
    assert event2['top'][0]['tier'] == 'full'
    assert event2['top'][0]['context_body_hash'] == hashlib.sha256(admitted.evidence[0]['body'].encode('utf-8')).hexdigest()
    assert event2['delivery'] == {'stage': 'context_compiled', 'admitted': [path], 'omitted': []}
    # A record that claims a full tier outside its admitted set is refused by the ledger itself.
    with pytest.raises(ContractError, match='full tier must be in the admitted set'):
        history.record(project, {**event2, 'id': 'forged', 'context_ref': 'c', 'delivery': {**event2['delivery'], 'admitted': []}})
    assert finalize_delivery(None, starved) is None
