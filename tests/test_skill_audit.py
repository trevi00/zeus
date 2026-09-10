import copy
import json
from uuid import uuid4

import pytest

from codex_harness.adapters.skill_audit import main, render_text
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.skill_history import SkillHistory
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.skill_audit import audit_history, duration_seconds, timestamp
from codex_harness.domain.skill_history import assess_history


def observation(index, score=1, content='v1', dimensions=None, at='2026-09-08T00:00:00Z'):
    return {'id': str(index), 'manifest_ref': 'manifest', 'context_ref': 'context', 'at': at,
            'top': [{'path': 'python/a.md', 'content_ref': content, 'score': score,
                     'dimensions': dimensions or ['kw:test']}]}


def test_audit_predicate_dimensions_versions_and_threshold_override():
    events = [observation(i, score) for i, score in enumerate([1, 2, 2, 1])]
    report = audit_history(events)
    row = report['skills'][0]
    assert (row['count'], row['score_min'], row['score_median'], row['score_max']) == (4, 1, 1.5, 2)
    assert row['dominant_dim'] == 'kw' and report['dim_weight'] == {'kw': 4}
    assert len(report['false_positive_candidates']) == 1
    assert assess_history(events, events[0]['top'])[0]['candidate']
    assert audit_history(events, min_samples=5)['false_positive_candidates'] == []
    report = audit_history(events + [observation('new', 6, 'v2', ['intent:x', 'path:y', 'pat:z', '???'])])
    assert len(report['skills']) == 2 and len(report['false_positive_candidates']) == 1
    assert report['dim_weight'] == {'kw': 4, 'intent': 1, 'path': 1, 'pat': 1, 'unknown': 1}
    assert 'Narrow the kw surface' in render_text(report)


def test_dates_legacy_dimensions_and_invalid_entries_are_explicit():
    old = observation('old', at='2020-01-01T00:00:00Z')
    unknown = observation('unknown', at=None)
    del unknown['top'][0]['dimensions']
    report = audit_history([old, unknown, observation('new')], cutoff=timestamp('2026-01-01T00:00:00Z'))
    assert report['invocations'] == 2 and report['unknown_timestamp_events'] == 1
    assert report['dim_weight'] == {'kw': 1}
    assert timestamp('2026-09-08T09:00:00+09:00') == timestamp('2026-09-08T00:00:00Z')
    invalid = observation('bool', True)
    invalid['top'].append(None)
    assert audit_history([invalid])['invalid_entries'] == 2
    assert 'no skill-match telemetry' in render_text(audit_history([]))


def test_match_rank_and_body_arrival_are_separate_counts_not_one_precision():
    # FA-012: the upstream evaluator blended "matched AND winner" with "matched"; here each target
    # is its own count and behavior is declared unmeasured.
    def two(index, a_score, b_score, a_tier, b_tier):
        return {'id': str(index), 'manifest_ref': 'manifest', 'context_ref': 'context', 'at': '2026-09-08T00:00:00Z',
                'top': [{'path': 'python/a.md', 'content_ref': 'v1', 'score': a_score, 'tier': a_tier,
                         'rendered_hash': 'h-a', 'dimensions': ['kw:x']},
                        {'path': 'python/b.md', 'content_ref': 'v1', 'score': b_score, 'tier': b_tier,
                         'dimensions': ['kw:x']}]}
    events = [two(0, 5, 3, 'full', 'pointer'), two(1, 2, 4, 'pointer', 'full'), two(2, 3, 3, 'full', 'external_pointer'),
              observation('legacy', 3)]
    report = audit_history(events)
    rows = {row['path']: row for row in report['skills']}
    a, b = rows['python/a.md'], rows['python/b.md']
    assert (a['count'], a['rank_first_count']) == (4, 3) and (b['count'], b['rank_first_count']) == (3, 2)
    assert a['delivery'] == {'full': 2, 'pointer': 1, 'external_pointer': 0, 'unmatched': 0, 'legacy': 0, 'unknown': 1}
    assert b['delivery'] == {'full': 1, 'pointer': 1, 'external_pointer': 1, 'unmatched': 0, 'legacy': 0, 'unknown': 0}
    assert set(report['measurement_targets']) == {'raw_match', 'rank', 'body_arrival', 'behavior'}
    assert 'not measured' in report['measurement_targets']['behavior']
    assert 'precision' not in json.dumps(report).lower()
    text = render_text(report)
    assert 'ranked first: 3/4; delivered full body: 2, pointer: 1, tier unknown: 1' in text
    assert 'match != delivery != behavior' in text


def test_recorded_observations_keep_tier_and_reject_unknown_tiers():
    store, history = MemoryStore(), None
    history = SkillHistory(store)
    event = observation('with-tier')
    event['top'][0].update(tier='full', rendered_hash='abc')
    assert history.record('project', event)
    with store.transaction() as tx:
        stored = tx.get('skill_history', 'project')['events'][0]['top'][0]
    assert stored['tier'] == 'full' and stored['rendered_hash'] == 'abc'
    bad = observation('bad-tier')
    bad['top'][0]['tier'] = 'delivered?'
    with pytest.raises(ContractError, match='delivery tier'):
        history.record('project', bad)
    empty_hash = observation('bad-hash')
    empty_hash['top'][0]['rendered_hash'] = ''
    with pytest.raises(ContractError, match='rendered body hash'):
        history.record('project', empty_hash)
    # Adding the tier to an already recorded selection is a diagnostic, not a new observation.
    replay = observation('with-tier')
    assert not history.record('project', replay)


def test_total_score_matches_upstream_producer_not_pointer_eligibility():
    events = [observation(i, 4) for i in range(3)]
    for event in events:
        event['top'][0]['base_score'] = 1  # weak prompt relevance plus upstream +3 stage boost
    assert audit_history(events)['false_positive_candidates'] == []
    assert not assess_history(events, events[0]['top'])[0]['candidate']
    report = audit_history(events)
    assert report['skills'][0]['base_score_profile'] == {
        'count': 3, 'min': 1, 'median': 1, 'max': 1, 'boosted_count': 3}
    assert 'base score median: 1' in render_text(report)


def test_window_cutoff_boundary_and_legacy_slug_cli(capsys, monkeypatch):
    monkeypatch.setattr('codex_harness.domain.skill_audit.MAX_EVENTS', 2)
    boundary = timestamp('2026-09-08T00:00:00Z')
    report = audit_history([observation(i) for i in range(3)], cutoff=boundary)
    assert report['invocations'] == 2 and report['max_events'] == 2
    store = MemoryStore()
    SkillHistory(store).record(digest('github:owner/repo'), observation('slug'))
    assert main(['--github-repo', 'Owner/Repo', '--json'], store=store) == 0
    assert json.loads(capsys.readouterr().out)['invocations'] == 1


@pytest.mark.parametrize('value', ['0s', '-1d', 'NaNh', 'infh', '7x', ''])
def test_invalid_since_is_rejected(value):
    with pytest.raises(ContractError):
        duration_seconds(value)


@pytest.mark.parametrize('value', ['yesterday', True, float('nan')])
def test_invalid_cutoff_is_a_contract_error(value):
    with pytest.raises(ContractError, match='Invalid time cutoff'):
        audit_history([], cutoff=value)


@pytest.mark.parametrize('value', [True, '1', 1.5, -1, 2])
def test_invalid_base_score_cannot_be_recorded(value):
    store = MemoryStore()
    entry = observation('invalid')
    entry['top'][0]['base_score'] = value
    with pytest.raises(ContractError, match='Invalid base score'):
        SkillHistory(store).record('project', entry)
    assert store.data == {}


def test_cli_reads_same_project_without_writes_and_replay_preserves_time(capsys):
    store = MemoryStore()
    project_id = str(uuid4())
    key = digest('uuid:' + project_id)
    history = SkillHistory(store)
    entry = observation('old')
    del entry['top'][0]['dimensions']
    history.record(key, entry)
    before = copy.deepcopy(store.data)
    entry['top'][0]['dimensions'] = ['kw:new-detail']
    assert not history.record(key, entry)
    assert store.data == before
    for index in range(3):
        history.record(key, observation(index))
    before = copy.deepcopy(store.data)
    assert main(['--project-id', project_id, '--json', '--since', '1h'], store=store) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['invocations'] == 4 and report['dim_weight'] == {'kw': 3}
    assert report['unknown_timestamp_events'] == 0
    assert store.data == before
    assert main(['--project-id', str(uuid4()), '--json'], store=store) == 0
    assert json.loads(capsys.readouterr().out)['invocations'] == 0
    assert main(['--github-repo', '../sibling', '--json'], store=store) == 2
    assert main(['--project-id', project_id, '--since', 'invalid'], store=store) == 2
    assert main(['--project-id', project_id, '--min-samples', '0'], store=store) == 2
    assert main(['--project-id', 'not-a-uuid'], store=store) == 2
    capsys.readouterr()
    assert main(['--project-id', project_id], store=store) == 0
    assert 'Narrow the kw surface' in capsys.readouterr().out


def test_store_value_error_is_unavailable_not_bad_arguments(capsys):
    class BrokenStore:
        def transaction(self):
            raise ValueError('secret backend detail')
    assert main(['--project-id', str(uuid4())], store=BrokenStore()) == 1
    error = json.loads(capsys.readouterr().err)
    assert error == {'error': 'Audit unavailable', 'type': 'ValueError'}
