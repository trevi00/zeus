"""FA-024: seam contracts carry qualified identity, honest denominators, validated transforms and advisory
verdicts (INV-SEAM-001).

The upstream registry returned OK when a partial value map or a prefix strip collapsed two values,
ignored unknown affix options, gave HIGH to extractions that dropped members, compared by tag:name
so a type change was invisible, dropped a second package's same short name and lost a prior DRIFT
when the ledger's last line was corrupt. Extraction below runs the real Python parser on real files.
"""
import json
import sys

import pytest

from codex_harness.adapters.seam_extraction import MAX_BLOB_BYTES, discover, extract
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.seam_ledger import COMPARISONS, IMPORTS, OBSERVATIONS, SeamLedger
from codex_harness.domain.model import ContractError
from codex_harness.domain.seams import (
    audit_records,
    compare,
    contract_identity,
    effective_transform,
    parse_observation,
    parse_policy,
    parse_transform,
)

REV = 'a' * 40
POLICY = {'version': 1, 'direction': 'producer_to_consumer', 'require_fidelity': 'HIGH', 'compare': ['name', 'type']}


def observation(name, members, *, package='shop.orders', stack='python', fidelity='HIGH', unresolved=0):
    return {'identity': contract_identity(stack, package, name), 'kind': 'enum',
            'members': [{'name': n, 'type': t, 'tag': v} for n, t, v in members],
            'fidelity': fidelity, 'denominator': {'symbols_found': len(members) + unresolved, 'unresolved': unresolved},
            'source': {'path': f'{package.replace(".", "/")}/{name.lower()}.py', 'blob_sha': 'sha256:' + 'b' * 64,
                       'revision': REV, 'parser': f'python-ast-{sys.version_info[0]}.{sys.version_info[1]}'}}


def test_transforms_are_closed_and_effective_over_every_input():
    names = ['PENDING', 'PAID', 'PAID_LATE', 'CANCELLED']
    # Partial value map: PAID_LATE -> PAID collides with the passthrough PAID (upstream: OK).
    partial = effective_transform({'version': 1, 'kind': 'value_map', 'value_map': {'PAID_LATE': 'PAID'}}, names)
    assert partial['collisions'] == {'PAID': ['PAID', 'PAID_LATE']} and partial['effective'] == 'mapping'
    # Prefix strip that collapses two inputs (upstream: OK).
    strip = effective_transform({'version': 1, 'kind': 'affix', 'strip_prefix': 'PAID_'}, ['PAID_LATE', 'LATE'])
    assert strip['collisions'] == {'LATE': ['PAID_LATE', 'LATE']}
    # An unknown affix option is refused, not ignored (upstream: a no-op affix bypassed the identity guard).
    with pytest.raises(ContractError, match='Unknown transform option'):
        parse_transform({'version': 1, 'kind': 'affix', 'strip_prefx': 'X'})
    with pytest.raises(ContractError, match='at least one non-empty affix'):
        parse_transform({'version': 1, 'kind': 'affix'})
    with pytest.raises(ContractError, match='Unknown transform option'):
        parse_transform({'version': 1, 'kind': 'identity', 'value_map': {}})
    for bad in ({'kind': 'value_map', 'value_map': {}}, {'version': 2, 'kind': 'identity'}, {'version': 1, 'kind': 'rename'},
                {'version': 1, 'kind': 'value_map', 'value_map': {'A': ''}}, 'identity'):
        with pytest.raises(ContractError):
            parse_transform(bad)
    # Declared non-identity that changes nothing over these inputs is reported, not trusted as a mapping.
    noop = effective_transform({'version': 1, 'kind': 'value_map', 'value_map': {'ABSENT': 'X'}}, names)
    assert noop['effective'] == 'identity' and noop['declared_effective_mismatch'] and not noop['collisions']
    identity = effective_transform({'version': 1, 'kind': 'identity'}, names)
    assert identity['mapping'] == dict(zip(names, names)) and not identity['declared_effective_mismatch']
    assert effective_transform({'version': 1, 'kind': 'affix', 'strip_prefix': 'PAID'}, ['PAID'])['empty_targets'] == ['']


def test_identity_is_qualified_and_fidelity_is_honest():
    a = contract_identity('python', 'shop.orders', 'Status')
    b = contract_identity('python', 'shop.billing', 'Status')
    assert a['id'] != b['id'] and a['name'] == b['name']
    for stack, package, name in (('', 'p', 'n'), ('python', 'p q', 'n'), ('python', 'p', '1n'), ('python', None, 'n')):
        with pytest.raises(ContractError, match='identifier token'):
            contract_identity(stack, package, name)
    with pytest.raises(ContractError, match='HIGH fidelity cannot coexist with unresolved'):
        parse_observation(observation('Status', [('A', 'int', 1)], unresolved=1))
    with pytest.raises(ContractError, match='Duplicate seam member'):
        parse_observation(observation('Status', [('A', 'int', 1), ('A', 'int', 2)]))
    forged = observation('Status', [('A', 'int', 1)])
    forged['identity']['package'] = 'other'
    with pytest.raises(ContractError, match='identity does not match'):
        parse_observation(forged)
    assert parse_policy(POLICY)['policy_hash']
    with pytest.raises(ContractError, match='Only HIGH fidelity'):
        parse_policy({**POLICY, 'require_fidelity': 'LOW'})
    with pytest.raises(ContractError, match='compare keys'):
        parse_policy({**POLICY, 'compare': ['type']})


def test_comparison_is_directional_typed_and_never_ok_below_high():
    producer = observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2), ('PAID_LATE', 'int', 3)])
    consumer = observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2), ('REFUNDED', 'int', 4)], package='shop.billing')
    identity = {'version': 1, 'kind': 'identity'}
    p2c = compare(producer, consumer, identity, POLICY)
    assert p2c['verdict'] == 'DRIFT' and p2c['producer_only'] == ['PAID_LATE'] and p2c['consumer_only'] == ['REFUNDED']
    assert p2c['authority'] == 'advisory' and p2c['blocking_eligible'] is False and 'not compiler' in p2c['note']
    c2p = compare(producer, consumer, identity, {**POLICY, 'direction': 'consumer_to_producer'})
    assert c2p['verdict'] == 'DRIFT' and c2p['consumer_only'] == ['REFUNDED']
    # A transform that maps PAID_LATE onto PAID collides with the passthrough PAID: NEEDS_TRANSFORM, not OK.
    collapsed = compare(producer, consumer, {'version': 1, 'kind': 'value_map', 'value_map': {'PAID_LATE': 'PAID'}}, POLICY)
    assert collapsed['verdict'] == 'NEEDS_TRANSFORM' and collapsed['transform']['collisions'] == {'PAID': ['PAID', 'PAID_LATE']}
    # A distinct rename resolves the drift for the producer direction; the consumer's extra value is allowed there.
    renamed = compare(producer, consumer, {'version': 1, 'kind': 'value_map', 'value_map': {'PAID_LATE': 'REFUNDED'}}, POLICY)
    assert renamed['verdict'] == 'OK' and renamed['consumer_only'] == []
    assert compare(producer, consumer, {'version': 1, 'kind': 'value_map', 'value_map': {'PAID_LATE': 'REFUNDED'}},
                   {**POLICY, 'direction': 'both'})['verdict'] == 'OK'
    # A type change is visible when type is compared (upstream tag:name hid it).
    retyped = observation('Status', [('PENDING', 'str', 'pending'), ('PAID', 'int', 2), ('PAID_LATE', 'int', 3)])
    assert compare(retyped, producer, identity, POLICY)['changed'] == ['PENDING']
    assert compare(retyped, producer, identity, {**POLICY, 'compare': ['name']})['verdict'] == 'OK', 'name-only is a weaker policy, stated as such'
    low = observation('Status', [('PENDING', 'int', 1)], fidelity='LOW', unresolved=2)
    blocked = compare(low, consumer, identity, POLICY)
    assert blocked['verdict'] == 'BLOCKED' and 'producer fidelity is LOW' in blocked['reason']
    assert blocked['denominators']['producer'] == {'symbols_found': 3, 'unresolved': 2}
    unknown = observation('Status', [], fidelity='UNKNOWN')
    assert compare(producer, unknown, identity, POLICY)['verdict'] == 'BLOCKED'
    assert compare(observation('Status', []), observation('Status', []), identity, POLICY)['verdict'] == 'OK', 'two empty HIGH sets agree; HIGH is what the denominator claims'


def test_python_extractor_keeps_original_spans_and_names_every_failure(tmp_path):
    src = tmp_path / 'shop' / 'orders'
    src.mkdir(parents=True)
    body = ('"""Docstring.\n\nmultiline\n"""\n'
            '# a comment line\n'
            '# another\n'
            'from enum import Enum, IntEnum\n\n'
            'def helper():\n    return 3\n\n'
            'class Status(Enum):\n'
            '    PENDING = 1\n'
            '    PAID = 2  # inline\n'
            '    A = 3\n'
            '    _ignored = 9\n\n'
            'class Priority(IntEnum):\n'
            '    LOW = helper()\n'
            '    HIGH = 10\n')
    (src / 'status.py').write_text(body, encoding='utf-8')
    observations = extract('python', tmp_path, 'shop/orders/status.py', revision=REV)
    status, priority = observations
    assert status['identity']['package'] == 'shop.orders' and status['identity']['name'] == 'Status'
    assert status['fidelity'] == 'HIGH' and [m['name'] for m in status['members']] == ['PENDING', 'PAID', 'A']
    assert status['denominator'] == {'symbols_found': 3, 'unresolved': 0}
    raw = (src / 'status.py').read_bytes()  # the on-disk blob (CRLF on Windows), not the Python literal
    span = status['members'][1]['span']
    assert raw[span['start']:span['end']] == b'PAID = 2' and span['line'] == 14, 'byte span into the original blob, comments included'
    assert status['members'][2]['name'] == 'A' and status['members'][2]['span']['text'] == 'A = 3', 'a one-character member is not dropped'
    assert status['source']['blob_sha'] == 'sha256:' + __import__('hashlib').sha256(raw).hexdigest()
    assert status['source']['revision'] == REV and status['source']['span']['line'] == 12
    assert priority['fidelity'] == 'LOW' and priority['denominator'] == {'symbols_found': 2, 'unresolved': 1}
    assert [m['name'] for m in priority['members']] == ['HIGH'], 'a call is not a literal member value'
    other = tmp_path / 'shop' / 'billing'
    other.mkdir()
    (other / 'status.py').write_text('from enum import Enum\nclass Status(Enum):\n    X = "x"\n', encoding='utf-8')
    twin, = extract('python', tmp_path, 'shop/billing/status.py', revision=REV)
    assert twin['identity']['id'] != status['identity']['id'], 'the same short name in another package is another contract'
    assert twin['members'][0]['type'] == 'str'
    (src / 'broken.py').write_text('class Status(Enum:\n', encoding='utf-8')
    broken, = extract('python', tmp_path, 'shop/orders/broken.py', revision=REV)
    assert broken['fidelity'] == 'UNKNOWN' and broken['state'] == 'unsupported_syntax'
    (src / 'bytes.py').write_bytes(b'class X(Enum):\n    A = "\xff"\n')
    undecodable, = extract('python', tmp_path, 'shop/orders/bytes.py', revision=REV)
    assert undecodable['state'] == 'decoding_error' and undecodable['fidelity'] == 'UNKNOWN'
    missing, = extract('python', tmp_path, 'shop/orders/nope.py', revision=REV)
    assert missing['state'] == 'missing_source'
    (src / 'huge.py').write_bytes(b'#' * (MAX_BLOB_BYTES + 1))
    huge, = extract('python', tmp_path, 'shop/orders/huge.py', revision=REV)
    assert huge['state'] == 'truncated' and huge['source']['bytes'] == MAX_BLOB_BYTES + 1
    java, = extract('java', tmp_path, 'shop/orders/Status.java', revision=REV)
    assert java['state'] == 'unsupported_stack' and java['fidelity'] == 'UNKNOWN', 'no regex HIGH for an unsupported stack'
    with pytest.raises(ContractError, match='source revision'):
        extract('python', tmp_path, 'shop/orders/status.py', revision='')
    found = discover(tmp_path, 'python', max_files=3)
    assert found['found'] == 5 and found['omitted'] == 2 and found['files'] == sorted(found['files']) and found['supported']
    assert found['files'][0] == 'shop/billing/status.py', 'sorted before the cap, so the selection is deterministic'
    assert discover(tmp_path, 'java')['supported'] is False and discover(tmp_path, 'java')['files'] == []


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_ledger_records_observations_comparisons_and_approvals(backend, request):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    ledger = SeamLedger(store)
    producer = observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2), ('PAID_LATE', 'int', 3)])
    consumer = observation('Status', [('PENDING', 'int', 1), ('PAID', 'int', 2)], package='shop.billing')
    p = ledger.record_observation(producer, binding={'revision': REV, 'task_id': 't1', 'attempt': 1})
    assert ledger.record_observation(producer, binding={'revision': REV, 'task_id': 't2', 'attempt': 1}) == p, 'same blob, parser, revision: one row'
    with pytest.raises(ContractError, match='source revision'):
        ledger.record_observation(producer, binding={'revision': 'c' * 40})
    c = ledger.record_observation(consumer, binding={'revision': REV})
    row = ledger.compare(p['id'], c['id'], {'version': 1, 'kind': 'identity'}, POLICY)
    assert row['result']['verdict'] == 'DRIFT' and row['approval'] is None and row['result']['blocking_eligible'] is False
    assert ledger.compare(p['id'], c['id'], {'version': 1, 'kind': 'identity'}, POLICY) == row
    with pytest.raises(ContractError, match='Both observations must be recorded'):
        ledger.compare(p['id'], 'nope', {'version': 1, 'kind': 'identity'}, POLICY)
    with pytest.raises(ContractError, match='Only a reviewer'):
        ledger.approve_blocking(row['id'], actor='worker:implementation', policy_revision='d' * 40, reason='x')
    with pytest.raises(ContractError, match='Git revision of the deployment policy'):
        ledger.approve_blocking(row['id'], actor='conductor', policy_revision='HEAD', reason='x')
    approved = ledger.approve_blocking(row['id'], actor='conductor', policy_revision='d' * 40, reason='release gate for orders->billing')
    assert approved['result']['blocking_eligible'] is True and approved['approval']['actor'] == 'conductor'
    assert ledger.approve_blocking(row['id'], actor='lead:improvement', policy_revision='e' * 40, reason='again') == approved
    ok = ledger.compare(p['id'], c['id'], {'version': 1, 'kind': 'value_map', 'value_map': {'PAID_LATE': 'PAID'}}, POLICY)
    assert ok['result']['verdict'] == 'NEEDS_TRANSFORM'
    with pytest.raises(ContractError, match='Only a DRIFT comparison'):
        ledger.approve_blocking(ok['id'], actor='conductor', policy_revision='d' * 40, reason='x')
    with store.transaction() as tx:
        assert len(tx.scan(OBSERVATIONS)) == 2 and len(tx.scan(COMPARISONS)) == 2


def test_imported_ledger_keeps_prior_drift_when_the_tail_is_corrupt():
    store = MemoryStore()
    ledger = SeamLedger(store)
    lines = [json.dumps({'seam_id': 'orders-billing', 'verdict': 'DRIFT', 'producer': 'a', 'consumer': 'b', 'at': '2026-09-10T00:00:00Z'}),
             json.dumps({'seam_id': 'orders-billing', 'verdict': 'OK', 'producer': 'a', 'consumer': 'b', 'at': '2026-09-10T01:00:00Z'}),
             '{"seam_id": "orders-billing", "verdict": "OK", "producer": "a"',  # truncated write
             json.dumps({'seam_id': 'x', 'verdict': 'CLEAN', 'producer': 'a', 'consumer': 'b', 'at': 't'})]  # unknown verdict
    row = ledger.import_jsonl('\n'.join(lines) + '\n', source_label='upstream/events.jsonl')
    audit = row['audit']
    assert audit['status'] == 'partial' and audit['valid'] == 2 and audit['corrupt'] == 2 and audit['corrupt_lines'] == [3, 4]
    assert audit['verdicts']['DRIFT'] == 1 and audit['verdicts']['OK'] == 1, 'the earlier DRIFT survives a corrupt tail'
    assert row['records'][2]['state'] == 'corrupt' and 'JSONDecodeError' in row['records'][2]['reason']
    assert ledger.import_jsonl('\n'.join(lines) + '\n', source_label='upstream/events.jsonl') == row
    clean = ledger.import_jsonl(lines[0] + '\n', source_label='clean')
    assert clean['audit']['status'] == 'complete' and clean['authority'].startswith('imported claims')
    assert audit_records([])['status'] == 'complete' and audit_records([])['valid'] == 0
    with store.transaction() as tx:
        assert len(tx.scan(IMPORTS)) == 2
