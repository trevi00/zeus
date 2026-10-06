from dataclasses import replace

import pytest

from codex_harness.domain.model import ContractError
from codex_harness.domain.threshold_proposals import (
    LOCKED_DENY,
    REGISTRY,
    direction_allowed,
    holdout_boundary,
    propose_threshold_changes,
    validate_registry,
)

NAME = 'skill_match.FULL_BODY_MIN_SCORE'


def corpus(score=3, sized=True):
    return [{'at': f'2026-01-01T00:00:{i:02d}Z',
             'top': [{'score': s, **({'body_chars': 500} if sized else {})} for s in [score, score + 2]]}
            for i in range(40)]


def propose(events, current=3, revision='a' * 40, **kwargs):
    return propose_threshold_changes(events_by_source={'skill-match': events},
        current_values={NAME: current}, policy_revision=revision, **kwargs)


def test_reference_proposal_generalizes_and_binds_effective_policy():
    from codex_harness.domain.threshold_replay import evaluate_threshold_change

    proposal, = propose(corpus())
    assert proposal['suggested'] == 4 and proposal['reference_accepted']
    assert proposal['trailing_size'] == 28 and proposal['holdout_size'] == 12
    assert proposal['advisory_only'] and not proposal['activation_ready']
    assert propose(corpus()) == [proposal]
    assert propose(corpus(), revision='b' * 40)[0]['id'] != proposal['id']
    shifted, = propose(corpus(4), current=4)
    assert shifted['suggested'] == 5 and shifted['current'] == 4
    # Both directions tie on the reference metric; source iteration prefers raising.
    gates = [evaluate_threshold_change(events=corpus(), old_value=3, proposed_value=value,
             holdout_boundary=proposal['holdout_boundary']) for value in [4, 2]]
    assert all(gate.accept for gate in gates)
    assert gates[0].target_delta_holdout == gates[1].target_delta_holdout
    assert proposal['selection_rule'] == 'highest_holdout_gain_raise_first_ties'
    assert [candidate['value'] for candidate in proposal['alternatives']] == [4, 2]
    assert all(candidate['report']['gate']['accept'] for candidate in proposal['alternatives'])


def test_missing_sizes_and_non_generalizing_improvements_cannot_offer_apply():
    missing, = propose(corpus(sized=False))
    assert missing['suggested'] is None and not missing['reference_accepted']
    assert missing['evaluated_value'] == 2  # source reports the last rejected candidate
    assert missing['selection_rule'] == 'last_rejected_candidate'
    assert len(missing['alternatives']) == 2
    assert all(candidate['report']['gate']['reason'] == 'non_finite_metric'
               for candidate in missing['alternatives'])
    assert missing['report']['gate']['reason'] == 'non_finite_metric'
    events = corpus()
    for event in events[28:]:
        event['top'] = [{'score': 5, 'body_chars': 500}]
    rejected, = propose(events)
    assert rejected['suggested'] is None
    assert rejected['report']['gate']['target_delta_holdout'] == 0


def test_temporal_partition_and_sample_floors():
    assert propose(corpus()[:5]) == []
    assert holdout_boundary([{'at': None}]) is None
    assert propose([{'at': '2026-01-01T00:00:00Z'}] * 40) == []
    assert holdout_boundary([{'at': '2026-01-01T09:00:00+09:00'},
                             {'at': '2026-01-01T01:00:00Z'}]) == '2026-01-01T01:00:00+00:00'
    for invalid in [0, -1, True, 10.0]:
        with pytest.raises(ContractError):
            propose(corpus(), min_sample=invalid)


def test_closed_registry_and_direction_enforcement(monkeypatch):
    validate_registry()
    assert len(REGISTRY) == 5 and len(LOCKED_DENY) == 12
    entry = replace(REGISTRY[NAME], direction_safety='raise_safe')
    assert direction_allowed(entry, 5, 6) and not direction_allowed(entry, 5, 4)
    lower = replace(entry, direction_safety='lower_safe')
    assert direction_allowed(lower, 5, 4) and not direction_allowed(lower, 5, 6)
    monkeypatch.setitem(REGISTRY, NAME, replace(entry, qualified=next(iter(LOCKED_DENY))))
    with pytest.raises(ContractError, match='locked'):
        propose(corpus())


def test_no_implicit_default_or_unknown_policy():
    for values in [{}, {'unknown': 3}, {NAME: float('nan')}, {NAME: True}]:
        with pytest.raises(ContractError):
            propose_threshold_changes(events_by_source={}, current_values=values, policy_revision='a' * 40)
    with pytest.raises(ContractError, match='revision'):
        propose(corpus(), revision='unbound')


def test_calculation_rules_are_bound_even_without_verdict_change(monkeypatch):
    from codex_harness.domain import threshold_replay

    before, = propose(corpus())
    monkeypatch.setattr(threshold_replay, 'REFERENCE_BODY_BUDGET', 5000)
    after, = propose(corpus())
    assert after['suggested'] == before['suggested']
    assert after['id'] != before['id']


def test_invalid_registry_and_corpus_fail_explicitly(monkeypatch):
    entry = REGISTRY[NAME]
    for updates in [{'step': 0}, {'step': True}, {'default': float('inf')},
                    {'direction_safety': 'unknown'}, {'target_metric': 'unknown'}]:
        monkeypatch.setitem(REGISTRY, NAME, replace(entry, **updates))
        with pytest.raises(ContractError):
            propose(corpus())
    monkeypatch.setitem(REGISTRY, NAME, entry)
    malformed = corpus()
    malformed[0]['extra'] = object()
    with pytest.raises(ContractError, match='encoding'):
        propose(malformed)


def test_hysteresis_suppresses_small_training_gain():
    events = corpus(5)
    events[0]['top'][0]['score'] = 3
    assert propose(events) == []  # 1/56 training gain is below 0.02


def test_training_filtered_alternative_is_not_misrepresented_as_gate_rejection():
    events = corpus()
    for event in events:
        event['top'] = [{'score': score, 'body_chars': 500} for score in [3, 4]]
    proposal, = propose(events)
    assert proposal['suggested'] == 2
    raised, lowered = proposal['alternatives']
    assert not raised['passed_hysteresis'] and raised['report'] is None
    assert lowered['passed_hysteresis'] and lowered['report']['gate']['accept']
