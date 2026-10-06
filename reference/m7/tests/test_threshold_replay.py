import copy
import json
import math

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import MemoryStore
from codex_harness.adapters.threshold_replay import main
from codex_harness.application.skill_history import SkillHistory
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.threshold_replay import (
    evaluate_threshold_change,
    full_body_admit_precision,
    non_truncation_rate,
    replay_report,
    split_by_holdout,
)


def corpus(sized=True):
    return [{'id': str(i), 'at': '2026-01-01T00:00:00Z' if i < 10 else '2026-02-01T00:00:00Z',
             'top': [{'score': 3, **({'body_chars': 1000} if sized else {})},
                     {'score': 5, **({'body_chars': 1000} if sized else {})}]} for i in range(20)]


def evaluate(events, **options):
    return evaluate_threshold_change(events=events, old_value=3, proposed_value=4,
        holdout_boundary='2026-02-01T00:00:00Z', **options)


def test_reference_gate_rejects_missing_evidence_and_non_generalizing_improvement():
    assert evaluate(corpus()).accept
    assert evaluate(corpus()).target_delta_holdout == .5
    assert evaluate(corpus(False)).reason == 'non_finite_metric'
    assert evaluate(corpus()[:10]).reason == 'insufficient_holdout'
    assert evaluate([]).reason == 'corpus_too_small'
    events = corpus()
    for event in events[10:]:
        event['top'] = [{'score': 5, 'body_chars': 1000}]
    assert not evaluate(events).accept  # improvement in training alone is insufficient
    assert not evaluate(corpus(), guard_fn=lambda _, threshold: 1 / threshold).accept
    def broken(*args):
        raise OSError('backend details')
    assert evaluate(corpus(), metric_fn=broken).reason == 'replay_error:OSError'


def test_half_open_split_utc_offsets_and_unknown_dates():
    events = [{'at': None}, {'at': '2026-02-01T09:00:00+09:00'}, {'at': '2026-01-31T23:59:59Z'}]
    trailing, held = split_by_holdout(events, '2026-02-01T00:00:00Z')
    assert trailing == [events[0], events[2]] and held == [events[1]]
    with pytest.raises(ContractError):
        split_by_holdout(events, 'unknown')


def test_reference_pressure_replays_sizes_instead_of_recorded_truncation():
    events = [{'top': [{'score': 5, 'body_chars': 2000}, {'score': 3, 'body_chars': 3000}],
               'truncated': False}]
    assert non_truncation_rate(events, 3) == 0
    assert non_truncation_rate(events, 4) == 1
    assert math.isnan(non_truncation_rate([{'top': [{'score': 3}]}], 3))
    assert full_body_admit_precision([], 3) == 1
    assert evaluate(corpus(), min_corpus=0).reason == 'invalid_min_corpus'


def test_report_exposes_actual_guard_denominator_and_partial_coverage():
    events = [{'top': [{'score': 3, 'body_chars': 10}, {'score': 5}]},
              {'top': [{'score': 3, 'body_chars': 20}]},
              {'top': [{'score': 3}]},
              {'top': [{'score': True, 'body_chars': 10}]}]
    report = replay_report(events, old_value=3, proposed_value=4,
                           holdout_boundary='2026-02-01T00:00:00Z')
    assert report['guard_usable_events'] == 2
    assert report['guard_skipped_events'] == 2
    assert report['guard_partially_sized_events'] == 1


def test_body_size_enrichment_does_not_recount_or_rewrite_old_observation():
    store = MemoryStore()
    history = SkillHistory(store)
    event = {'id': 'one', 'manifest_ref': 'manifest', 'context_ref': 'context',
             'top': [{'path': 'skill', 'content_ref': 'body', 'score': 3}]}
    history.record('project', event)
    before = copy.deepcopy(store.data)
    event['top'][0]['body_chars'] = 2000
    assert not history.record('project', event)
    assert store.data == before
    for size in (True, -1, 2**21, '100'):
        event['top'][0]['body_chars'] = size
        with pytest.raises(ContractError, match='body size'):
            history.record('project', event)


def test_cli_preserves_corpus_and_never_writes_policy(tmp_path, capsys):
    store = MemoryStore()
    key = digest('github:owner/repo')
    with store.transaction() as tx:
        tx.put('skill_history', key, {'events': corpus()})
    before = copy.deepcopy(store.data)
    args = ['--github-repo', 'owner/repo', '--old-value', '3', '--proposed-value', '4',
            '--holdout-boundary', '2026-02-01T00:00:00Z', '--artifacts', str(tmp_path)]
    assert main(args, store=store) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['report']['gate']['accept'] and output['report']['advisory_only']
    assert not output['report']['policy_changed'] and store.data == before
    assert FileArtifacts(str(tmp_path)).document(output['evidence_ref'])['events'] == corpus()
    assert main(args + ['--old-value', 'nan'], store=store) == 2
