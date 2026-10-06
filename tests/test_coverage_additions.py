"""CUT-INT rule 7: public writer outcomes on disposable coverage tables."""

import copy
import hashlib
import json
import subprocess
import sys

import pytest
from _layout import REPO as ROOT

sys.path.insert(0, str(ROOT / 'coverage'))
try:
    import additions
    import generate
finally:
    sys.path.remove(str(ROOT / 'coverage'))


@pytest.fixture
def table_root(tmp_path):
    (tmp_path / 'coverage').mkdir()
    (tmp_path / 'coverage/ledger-coverage.json').write_bytes(
        (ROOT / 'coverage/ledger-coverage.json').read_bytes())
    return tmp_path


def invoke(root, mode):
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'coverage/additions.py'),
                             mode, '--root', str(root)], capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout)


def load(root):
    return json.loads((root / 'coverage/ledger-coverage.json').read_text())


def save(root, table):
    (root / 'coverage/ledger-coverage.json').write_text(generate.dump(table))


def remove_new(root):
    table = load(root)
    table['rows'] = [r for r in table['rows'] if r['key'] not in
                     {r['key'] for r in additions.ADDITIONS[25:]}]
    table['counts']['addition'] = 25
    # Independent digest definition: test_coverage_table / owner spec.
    table['ledger_key_digest'] = hashlib.sha256('\n'.join(sorted(
        r['key'] for r in table['rows'] if r['kind'] != 'atomic_unit')).encode()).hexdigest()
    save(root, table)
    return table


def test_check_passes_on_head():
    code, output = invoke(ROOT, '--check')
    assert code == 0
    assert output['ok'] and output['addition_rows'] == 40


@pytest.mark.parametrize('fault, error', [('drift', 'owned_field_drift'), ('duplicate', 'duplicate_key'),
                                         ('undeclared', 'undeclared_addition'), ('evidence', 'evidence_form')])
@pytest.mark.parametrize('mode', ['--check', '--write'])
def test_refusal_leaves_file_unchanged(table_root, fault, error, mode):
    table = load(table_root)
    r = next(r for r in table['rows'] if r['kind'] == 'addition')
    if fault == 'drift':
        r['intent'] = 'addition:unauthorized drift'
    elif fault == 'duplicate':
        table['rows'].append(copy.deepcopy(r))
    elif fault == 'undeclared':
        r['key'] = 'addition:observation/module/unknown'
    else:
        r['evidence'] = ['unknown:bad form']
    save(table_root, table)
    path = table_root / 'coverage/ledger-coverage.json'
    before = path.read_bytes()
    code, output = invoke(table_root, mode)
    assert code == 1 and error in output['error']
    assert path.read_bytes() == before


def test_write_appends_only_and_is_idempotent(table_root):
    """CUT-INT rule 7 explicitly preserves the SOURCE skeleton (structural contract)."""
    before = remove_new(table_root)
    code, output = invoke(table_root, '--write')
    assert code == 0 and len(output['added']) == 15
    after = load(table_root)
    assert after['rows'][:len(before['rows'])] == before['rows']
    assert generate.skeleton(after) == generate.skeleton(before)
    assert {k: v for k, v in after.items() if k not in {'rows', 'counts', 'ledger_key_digest'}} == {
        k: v for k, v in before.items() if k not in {'rows', 'counts', 'ledger_key_digest'}}
    assert after['counts'] == {**before['counts'], 'addition': 40}
    for r in after['rows'][len(before['rows']):]:
        assert r['status'] == 'designed' and 'verification' not in r
    assert invoke(table_root, '--check')[0] == 0
    path = table_root / 'coverage/ledger-coverage.json'
    first = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    assert invoke(table_root, '--write')[1]['added'] == []
    assert path.read_bytes() == first and path.stat().st_mtime_ns == mtime


def test_write_recomputes_digest(table_root):
    before = remove_new(table_root)
    assert invoke(table_root, '--write')[0] == 0
    after = load(table_root)
    expected = hashlib.sha256('\n'.join(sorted(r['key'] for r in after['rows']
                                              if r['kind'] != 'atomic_unit')).encode()).hexdigest()
    assert after['ledger_key_digest'] == expected
    assert after['ledger_key_digest'] != before['ledger_key_digest']


def test_bad_seed_evidence_refuses_without_writing(table_root):
    declarations = copy.deepcopy(additions.ADDITIONS)
    declarations[-1]['evidence'] = ['unclassifiable:seed']
    path = table_root / 'coverage/ledger-coverage.json'
    before = path.read_bytes()
    with pytest.raises(additions.Refused, match='evidence_form'):
        additions.run(table_root, True, declarations)
    assert path.read_bytes() == before


@pytest.mark.parametrize('field, error', [('count', 'count_mismatch'), ('digest', 'digest_mismatch')])
def test_check_refuses_stale_metadata(table_root, field, error):
    table = load(table_root)
    if field == 'count':
        table['counts']['addition'] = 0
    else:
        table['ledger_key_digest'] = '0' * 64
    save(table_root, table)
    code, output = invoke(table_root, '--check')
    assert code == 1 and error in output['errors']


def test_maintained_values_are_preserved(table_root):
    table = load(table_root)
    r = next(r for r in table['rows'] if r['kind'] == 'addition')
    r.update(slice='S9', symbol_basis='owner updated', slice_progress='owner updated',
             evidence=['static:owner updated'])
    save(table_root, table)
    path = table_root / 'coverage/ledger-coverage.json'
    before = path.read_bytes()
    assert invoke(table_root, '--check')[0] == 0
    assert invoke(table_root, '--write')[0] == 0
    assert path.read_bytes() == before
