"""FA-027: the seam view keeps provenance, roles and direction; the gate has a closed vocabulary and nonzero
obligations; the view is a deterministic derived projection (INV-SEAM-VIEW-001).

The upstream graph's LIVE meant "matched and not BLOCKED", dropped roles and drift direction, showed
absent fixtures as participating edges, accepted `--fail-on TYPO` and passed an empty seam list 0/0.
"""
import json

import pytest
from test_seam_contracts import POLICY, REV, observation

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.seam_ledger import OBSERVATIONS, VIEWS, SeamLedger
from codex_harness.domain.model import ContractError
from codex_harness.domain.sdd import gate_report
from codex_harness.domain.seam_view import (
    FAIL_ON_VOCABULARY,
    build_view,
    gate,
    parse_gate_policy,
    seam_id,
)
from codex_harness.domain.seams import compare


def test_gate_policy_is_a_closed_vocabulary_with_nonzero_obligations():
    ok = parse_gate_policy({'version': 1, 'fail_on': ['DRIFT', 'BLOCKED'], 'required_seams': ['s1']})
    assert ok['fail_on'] == ['BLOCKED', 'DRIFT'] and ok['policy_hash']
    for bad, match in (({'version': 1, 'fail_on': ['TYPO'], 'required_seams': ['s1']}, 'outside the vocabulary'),
                       ({'version': 1, 'fail_on': ['OK'], 'required_seams': ['s1']}, 'outside the vocabulary'),
                       ({'version': 1, 'fail_on': [], 'required_seams': ['s1']}, 'at least one verdict'),
                       ({'version': 1, 'fail_on': ['DRIFT'], 'required_seams': []}, 'at least one seam'),
                       ({'version': 1, 'fail_on': ['DRIFT', 'DRIFT'], 'required_seams': ['s1']}, 'repeats'),
                       ({'version': 2, 'fail_on': ['DRIFT'], 'required_seams': ['s1']}, 'version'),
                       ({'fail_on': ['DRIFT'], 'required_seams': ['s1']}, 'requires version')):
        with pytest.raises(ContractError, match=match):
            parse_gate_policy(bad)
    assert set(FAIL_ON_VOCABULARY) == {'DRIFT', 'NEEDS_TRANSFORM', 'BLOCKED'}


def fixtures():
    producer = observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2), ('PAID_LATE', 'int', 3)])
    consumer = observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2)], package='shop.billing')
    aligned = observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2), ('PAID_LATE', 'int', 3)], package='shop.ledger')
    low = observation('Priority', [('LOW', 'int', 1)], package='shop.billing', fidelity='LOW', unresolved=1)
    absent = observation('Priority', [], package='shop.ghost', fidelity='UNKNOWN')
    identity = {'version': 1, 'kind': 'identity'}
    comparisons = [
        {'id': 'c-drift', 'result': compare(producer, consumer, identity, POLICY)},
        {'id': 'c-ok', 'result': compare(producer, aligned, identity, POLICY)},
        {'id': 'c-blocked', 'result': compare(low, absent, identity, POLICY)},
    ]
    return [producer, consumer, aligned, low, absent], comparisons


def test_view_keeps_provenance_roles_direction_and_reserves_live():
    observations, comparisons = fixtures()
    producer, consumer, aligned, low, absent = observations
    drift_seam = seam_id(producer['identity']['id'], consumer['identity']['id'])
    ok_seam = seam_id(producer['identity']['id'], aligned['identity']['id'])
    blocked_seam = seam_id(low['identity']['id'], absent['identity']['id'])
    policy = {'version': 1, 'fail_on': ['DRIFT'], 'required_seams': [drift_seam, ok_seam, blocked_seam, 'declared-but-never-compared']}
    view = build_view(observations, comparisons, policy)
    nodes = {n['id']: n for n in view['nodes']}
    assert nodes[producer['identity']['id']]['provenance'] == 'observed' and nodes[low['identity']['id']]['provenance'] == 'extracted_partial'
    assert nodes[absent['identity']['id']]['provenance'] == 'unavailable' and nodes[absent['identity']['id']]['members'] == 0
    edges = {e['seam_id']: e for e in view['edges']}
    drift = edges[drift_seam]
    assert drift['roles'] == {'producer': producer['identity']['id'], 'consumer': consumer['identity']['id']}
    assert drift['direction'] == 'producer_to_consumer' and drift['verdict'] == 'DRIFT' and drift['producer_only'] == ['PAID_LATE']
    assert drift['live'] is False and drift['blocking_eligible'] is False
    assert edges[ok_seam]['live'] is True and edges[ok_seam]['verdict'] == 'OK'
    blocked = edges[blocked_seam]
    assert blocked['verdict'] == 'BLOCKED' and blocked['live'] is False and blocked['fidelity'] == {'producer': 'LOW', 'consumer': 'UNKNOWN'}
    ghost = edges['declared-but-never-compared']
    assert ghost['provenance'] == 'declared_only' and ghost['verdict'] is None and ghost['live'] is False
    assert 'never observed traffic' in view['legend']['live']
    # The gate: fail_on DRIFT fails on the drifted seam; nothing about BLOCKED or the ghost is a pass.
    decision = view['gate']
    assert decision['decision'] == 'fail' and decision['failing'] == [drift_seam]
    assert decision['missing'] == ['declared-but-never-compared'] and decision['undecided'] == [blocked_seam]
    assert decision['required'] == 4 and decision['checked'] == 3 and decision['ok'] == 1
    # Upstream: --fail-on DRIFT accepted a BLOCKED seam. Here a BLOCKED required seam leaves the gate undecided.
    only_blocked = build_view(observations, comparisons, {'version': 1, 'fail_on': ['DRIFT'], 'required_seams': [blocked_seam]})
    assert only_blocked['gate']['decision'] == 'undecided' and only_blocked['gate']['undecided'] == [blocked_seam]
    assert build_view(observations, comparisons, {'version': 1, 'fail_on': ['BLOCKED'], 'required_seams': [blocked_seam]})['gate']['decision'] == 'fail'
    passing = build_view(observations, comparisons, {'version': 1, 'fail_on': ['DRIFT', 'BLOCKED'], 'required_seams': [ok_seam]})
    assert passing['gate']['decision'] == 'pass' and passing['gate']['ok'] == 1
    assert gate({**passing, 'policy': {**passing['policy'], 'required_seams': [ok_seam, 'ghost']}})['decision'] == 'undecided'


def test_view_is_deterministic_with_a_generation_receipt():
    observations, comparisons = fixtures()
    policy = {'version': 1, 'fail_on': ['DRIFT'], 'required_seams': [seam_id(observations[0]['identity']['id'], observations[2]['identity']['id'])]}
    first = build_view(observations, comparisons, policy)
    again = build_view(list(reversed(observations)), list(reversed(comparisons)), policy)
    assert first == again and first['receipt']['view_hash'] == again['receipt']['view_hash']
    assert json.dumps(first, sort_keys=True) == json.dumps(again, sort_keys=True), 'byte-equal for equal inputs in any order'
    assert first['receipt']['derived'] and 'not a ledger' in first['receipt']['authority']
    changed = build_view(observations, comparisons[:-1], policy)
    assert changed['receipt']['inputs_hash'] != first['receipt']['inputs_hash'] and changed['receipt']['view_hash'] != first['receipt']['view_hash']
    conflicting = [{'id': 'c-a', 'result': comparisons[0]['result']}, {'id': 'c-b', 'result': {**comparisons[0]['result'], 'verdict': 'OK'}}]
    with pytest.raises(ContractError, match='Two different comparisons for one seam'):
        build_view(observations, conflicting, policy)


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_ledger_view_row_is_derived_and_regenerable(backend, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    ledger = SeamLedger(store)
    observations, _ = fixtures()
    rows = [ledger.record_observation(o, binding={'revision': REV}) for o in observations[:3]]
    identity = {'version': 1, 'kind': 'identity'}
    drift = ledger.compare(rows[0]['id'], rows[1]['id'], identity, POLICY)
    ok = ledger.compare(rows[0]['id'], rows[2]['id'], identity, POLICY)
    policy = {'version': 1, 'fail_on': ['DRIFT'], 'required_seams': [seam_id(observations[0]['identity']['id'], observations[2]['identity']['id'])]}
    view = ledger.view(policy)
    assert view['derived'] and view['view']['gate']['decision'] == 'pass'
    assert {e['comparison'] for e in view['view']['edges']} == {drift['id'], ok['id']}
    assert ledger.view(policy) == view, 'same inputs, same row'
    stricter = ledger.view({**policy, 'required_seams': [seam_id(observations[0]['identity']['id'], observations[1]['identity']['id'])]})
    assert stricter['id'] != view['id'] and stricter['view']['gate']['decision'] == 'fail'
    with store.transaction() as tx:
        assert len(tx.scan(VIEWS)) == 2
    assert view['view']['receipt']['revision'] == REV and view['view']['receipt']['comparison_rows'] == sorted([drift['id'], ok['id']])
    # Review counterexample (PR #59): a second revision of the same contracts accumulates in the append-only
    # ledger; the view is per revision, so ordinary iteration never breaks it and history stays regenerable.
    later = 'f' * 40
    evolved = [{**o, 'source': {**o['source'], 'revision': later, 'blob_sha': 'sha256:' + ('9' * 63) + str(i)}} for i, o in enumerate(observations[:3])]
    evolved[1] = {**evolved[1], 'members': observations[0]['members']}  # the consumer caught up: no drift at the later revision
    rows2 = [ledger.record_observation(o, binding={'revision': later}) for o in evolved]
    fixed = ledger.compare(rows2[0]['id'], rows2[1]['id'], identity, POLICY)
    still_ok = ledger.compare(rows2[0]['id'], rows2[2]['id'], identity, POLICY)
    newest = ledger.view(policy)
    assert newest['view']['receipt']['revision'] == later and newest['view']['receipt']['revisions_recorded'] == [REV, later]
    assert {e['comparison'] for e in newest['view']['edges']} == {fixed['id'], still_ok['id']} and newest['view']['gate']['decision'] == 'pass'
    older = ledger.view(policy, revision=REV)
    assert older['id'] == view['id'] and older['view']['receipt']['revision'] == REV, 'the earlier view regenerates unchanged'
    explicit = ledger.view(policy, revision=later, comparison_ids=[fixed['id']])
    assert [e['comparison'] for e in explicit['view']['edges'] if 'comparison' in e] == [fixed['id']], 'declared-only seams stay as placeholders'
    with pytest.raises(ContractError, match='outside revision'):
        ledger.view(policy, revision=REV, comparison_ids=[fixed['id']])
    with pytest.raises(ContractError, match='Unknown seam comparison ids'):
        ledger.view(policy, comparison_ids=['nope'])
    with pytest.raises(ContractError, match='No observations recorded'):
        SeamLedger(MemoryStore()).view(policy)
    with store.transaction() as tx:
        assert len(tx.scan(OBSERVATIONS)) == 6, 'history is preserved, never rewritten'
        assert len(tx.scan(VIEWS)) == 4


def test_sdd_report_separates_stage_denominators():
    from test_sdd import spec_data
    report = gate_report(spec_data(), [{'physical_device': True, 'passed': True}])
    denominators = report['denominators']
    assert denominators['scenarios_declared'] == len(spec_data()['scenarios']) > 0
    assert denominators['observations_imported'] == 1 and denominators['scenarios_executed_by_runner'] == 0
    assert denominators['assertions_verified'] == 0 and denominators['human_accepted'] == 0
    assert not report['acceptance_passed'] and 'never count as executed' in denominators['note']
