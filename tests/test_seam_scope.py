"""FA-028: OK speaks only for the scopes a check covered; byte identity and checked-scope equality are different
facts; shared values are declarations, not delivery (INV-SEAM-SCOPE-001).

The upstream seam check compared enum tag:name, so a proto money-field type change and an RPC
rename kept HIGH/OK, envelope null/errorCode differences were outside its scope, and copied proto
files were called identical although package, options, service and response definitions differed.
"""
import pytest
from test_seam_contracts import POLICY, REV, observation

from codex_harness.adapters.seam_extraction import extract
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.seam_ledger import SeamLedger
from codex_harness.domain.model import ContractError
from codex_harness.domain.seam_view import build_view, seam_id
from codex_harness.domain.seams import (
    CHECK_SCOPES,
    compare,
    parse_observation,
    parse_policy,
    scope_coverage,
)


def covered(obs, scopes):
    return {**obs, 'covered_scopes': list(scopes)}


ENUM_SCOPES = ['member_names', 'member_types', 'member_tags']


def test_policies_and_observations_declare_scopes_explicitly():
    assert parse_policy(POLICY)['required_scopes'] == ['member_names'], 'the default requires only what an enum check can cover'
    wide = parse_policy({**POLICY, 'required_scopes': ['member_names', 'rpc', 'response_types']})
    assert wide['required_scopes'] == ['member_names', 'response_types', 'rpc']
    for bad in ([], ['names'], ['member_names', 'member_names'], 'member_names'):
        with pytest.raises(ContractError, match='required_scopes'):
            parse_policy({**POLICY, 'required_scopes': bad})
    with pytest.raises(ContractError, match='covered_scopes'):
        parse_observation(covered(observation('Status', [('A', 'int', 1)]), ['payload']))
    assert set(CHECK_SCOPES) >= {'member_names', 'member_types', 'member_tags', 'envelope', 'rpc', 'response_types',
                                 'error_mapping', 'storage', 'execution', 'human_scenario'}


def test_ok_is_limited_to_checked_scopes_and_the_rest_is_unverified():
    producer = covered(observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2)]), ENUM_SCOPES)
    consumer = covered(observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2)], package='shop.billing'), ENUM_SCOPES)
    identity = {'version': 1, 'kind': 'identity'}
    narrow = compare(producer, consumer, identity, {**POLICY, 'compare': ['name', 'type', 'tag']})
    assert narrow['verdict'] == 'OK' and narrow['scope_coverage'] == {
        'required': ['member_names'], 'checked': ['member_names'], 'unverified': [], 'complete': True,
        'note': 'OK speaks only for checked scopes; an unverified scope is not agreement'}
    # The approved spec also requires the RPC and response types; the enum check cannot see them.
    spec = {**POLICY, 'compare': ['name', 'type', 'tag'], 'required_scopes': ['member_names', 'member_types', 'rpc', 'response_types']}
    partial = compare(producer, consumer, identity, spec)
    assert partial['verdict'] == 'OK', 'the checked scopes do agree'
    assert partial['scope_coverage']['checked'] == ['member_names', 'member_types']
    assert partial['scope_coverage']['unverified'] == ['response_types', 'rpc'] and partial['scope_coverage']['complete'] is False
    # A policy that compares names only cannot claim member_types even when both sides covered them.
    names_only = compare(producer, consumer, identity, {**POLICY, 'compare': ['name'], 'required_scopes': ['member_names', 'member_types']})
    assert names_only['scope_coverage']['unverified'] == ['member_types']
    # An UNKNOWN observation covers nothing: everything required is unverified and the verdict is BLOCKED anyway.
    unknown = observation('Status', [], fidelity='UNKNOWN')
    blocked = compare(producer, unknown, identity, spec)
    assert blocked['verdict'] == 'BLOCKED' and blocked['scope_coverage']['checked'] == []
    assert scope_coverage(producer, {'covered_scopes': []}, parse_policy(spec))['complete'] is False


def test_byte_identity_and_checked_equality_are_separate_facts():
    producer = covered(observation('Status', [('PENDING', 'int', 1)]), ENUM_SCOPES)
    same_bytes = covered(observation('Status', [('PENDING', 'int', 1)], package='shop.copy'), ENUM_SCOPES)
    identity = {'version': 1, 'kind': 'identity'}
    result = compare(producer, same_bytes, identity, POLICY)
    assert result['copy']['same_blob'] is True and result['equivalent_on_checked_scopes'] is True
    different_bytes = {**same_bytes, 'source': {**same_bytes['source'], 'blob_sha': 'sha256:' + 'c' * 64}}
    result = compare(producer, different_bytes, identity, POLICY)
    assert result['copy']['same_blob'] is False and result['equivalent_on_checked_scopes'] is True, 'equal members, different file'
    retyped = covered(observation('Status', [('PENDING', 'str', 'pending')], package='shop.copy'), ENUM_SCOPES)
    result = compare(producer, retyped, identity, {**POLICY, 'compare': ['name', 'type']})
    assert result['same_blob'] if 'same_blob' in result else result['copy']['same_blob'] is True
    assert result['equivalent_on_checked_scopes'] is False and result['changed'] == ['PENDING'], 'same bytes claimed, different types found'


def test_view_marks_scope_incomplete_ok_as_not_live_and_keeps_undeclared_contracts(tmp_path):
    producer = covered(observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2)]), ENUM_SCOPES)
    consumer = covered(observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2)], package='shop.billing'), ENUM_SCOPES)
    stray = covered(observation('Heartbeat', [('HEARTBEAT', 'str', 'HEARTBEAT')], package='shop.ops'), ENUM_SCOPES)
    peer = covered(observation('Signals', [('HEARTBEAT', 'str', 'HEARTBEAT'), ('OTHER', 'int', 1)], package='shop.peer'), ENUM_SCOPES)
    identity = {'version': 1, 'kind': 'identity'}
    spec = {**POLICY, 'compare': ['name', 'type', 'tag'], 'required_scopes': ['member_names', 'rpc']}
    full = {**POLICY, 'compare': ['name', 'type', 'tag']}
    seam = seam_id(producer['identity']['id'], consumer['identity']['id'])
    incomplete = build_view([producer, consumer, stray, peer], [{'id': 'c1', 'result': compare(producer, consumer, identity, spec)}],
                            {'version': 1, 'fail_on': ['DRIFT'], 'required_seams': [seam]})
    edge = {e['seam_id']: e for e in incomplete['edges']}[seam]
    assert edge['verdict'] == 'OK' and edge['live'] is False and edge['scope_coverage']['unverified'] == ['rpc']
    assert incomplete['gate']['decision'] == 'undecided' and incomplete['gate']['statuses'][seam] == 'OK_unverified_scopes'
    complete = build_view([producer, consumer, stray, peer], [{'id': 'c1', 'result': compare(producer, consumer, identity, full)}],
                          {'version': 1, 'fail_on': ['DRIFT'], 'required_seams': [seam]})
    assert {e['seam_id']: e for e in complete['edges']}[seam]['live'] is True and complete['gate']['decision'] == 'pass'
    nodes = {n['id']: n for n in complete['nodes']}
    assert nodes[stray['identity']['id']]['undeclared'] is True and nodes[stray['identity']['id']]['provenance'] == 'observed'
    assert nodes[producer['identity']['id']]['undeclared'] is False and nodes[producer['identity']['id']]['covered_scopes'] == ENUM_SCOPES
    shared = {s['value']: s for s in complete['shared_values']}
    assert shared['str:HEARTBEAT']['contracts'] == sorted([stray['identity']['id'], peer['identity']['id']])
    assert shared['str:HEARTBEAT']['identity'] == 'type+tag' and 'never causal' in shared['str:HEARTBEAT']['note']
    assert 'int:1' in shared and 'undeclared' in complete['legend']


def test_extractor_declares_its_scopes(tmp_path):
    src = tmp_path / 'pkg'
    src.mkdir()
    (src / 'status.py').write_text('from enum import Enum\nclass Status(Enum):\n    A = 1\n', encoding='utf-8')
    status, = extract('python', tmp_path, 'pkg/status.py', revision=REV)
    assert status['covered_scopes'] == ENUM_SCOPES
    java, = extract('java', tmp_path, 'pkg/Status.java', revision=REV)
    assert java['covered_scopes'] == [] and java['fidelity'] == 'UNKNOWN', 'an absent tool covers nothing'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_scope_gate_over_extracted_members_across_two_revisions(backend, request, tmp_path):
    # Review (PR #60): the scope gate re-verified on the fixed extractor (#56: annotated members count) and
    # the per-revision view (#59): a member the consumer lacks fails the gate at one revision and passes at the
    # next, and an unresolved member candidate never lets OK through.
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    ledger = SeamLedger(store)
    later = 'e' * 40
    producer_dir, consumer_dir = tmp_path / 'shop' / 'orders', tmp_path / 'shop' / 'billing'
    producer_dir.mkdir(parents=True)
    consumer_dir.mkdir(parents=True)
    enum_source = 'from enum import Enum\nclass Status(Enum):\n    A = 1\n'
    (producer_dir / 'status.py').write_text(enum_source + '    B: int = 2\n', encoding='utf-8')
    (consumer_dir / 'status.py').write_text(enum_source, encoding='utf-8')
    full = {**POLICY, 'compare': ['name', 'type', 'tag'], 'required_scopes': ENUM_SCOPES}
    identity = {'version': 1, 'kind': 'identity'}

    def snapshot(revision):
        producer, = extract('python', tmp_path, 'shop/orders/status.py', revision=revision)
        consumer, = extract('python', tmp_path, 'shop/billing/status.py', revision=revision)
        rows = [ledger.record_observation(o, binding={'revision': revision}) for o in (producer, consumer)]
        return producer, consumer, rows, ledger.compare(rows[0]['id'], rows[1]['id'], identity, full)

    producer, consumer, rows, drift = snapshot(REV)
    assert [m['name'] for m in producer['members']] == ['A', 'B'] and producer['fidelity'] == 'HIGH', 'B: int = 2 is a member (#56)'
    assert producer['denominator'] == {'symbols_found': 2, 'unresolved': 0} and consumer['denominator']['symbols_found'] == 1
    assert drift['result']['verdict'] == 'DRIFT' and drift['result']['scope_coverage']['complete'] is True
    seam = seam_id(producer['identity']['id'], consumer['identity']['id'])
    gate = {'version': 1, 'fail_on': ['DRIFT'], 'required_seams': [seam]}
    first = ledger.view(gate)
    assert first['view']['gate']['decision'] == 'fail' and first['view']['receipt']['revision'] == REV
    # The consumer catches up at the next revision: the same seam is OK on every required scope and live.
    (consumer_dir / 'status.py').write_text(enum_source + '    B: int = 2\n', encoding='utf-8')
    producer2, consumer2, rows2, ok = snapshot(later)
    assert ok['result']['verdict'] == 'OK' and ok['result']['scope_coverage']['unverified'] == [] and ok['result']['copy']['same_blob'] is True
    newest = ledger.view(gate)
    edge = {e['seam_id']: e for e in newest['view']['edges']}[seam]
    assert newest['view']['receipt']['revision'] == later and newest['view']['gate']['decision'] == 'pass' and edge['live'] is True
    assert ledger.view(gate, revision=REV)['id'] == first['id'], 'the failing earlier view regenerates unchanged (#59)'
    # An unresolved member candidate (multi-target assignment) keeps the producer below HIGH: no OK, no pass.
    (producer_dir / 'status.py').write_text(enum_source + '    B: int = 2\n    C = D = 3\n', encoding='utf-8')
    third = 'f' * 40
    producer3, consumer3, rows3, blocked = snapshot(third)
    assert producer3['fidelity'] == 'LOW' and producer3['denominator'] == {'symbols_found': 4, 'unresolved': 2}
    assert blocked['result']['verdict'] != 'OK'
    assert ledger.view(gate)['view']['gate']['decision'] != 'pass' and ledger.view(gate)['view']['receipt']['revision'] == third
