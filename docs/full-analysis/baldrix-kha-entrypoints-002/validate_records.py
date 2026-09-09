"""Validate only this static review's records and immutable source identities."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
PINNED = ROOT / '.runtime/absorption/sources/baldrix/pinned'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def canonical(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def check_ref(ref):
    path, anchor = ref.split('#')
    assert f'<a id="{anchor}"></a>' in (ROOT / path).read_text(encoding='utf-8')


def main():
    files = read(OUT / 'files.json')
    supports = read(OUT / 'supporting-evidence.json')
    checkpoint = read(OUT / 'checkpoint.json')
    assert len(files) == 36 and len(supports) == 41
    assert sum(row['bytes'] for row in files) == 117515
    assert len({row['path'] for row in files}) == 36
    reused = 0
    for row in files + supports:
        raw = (PINNED / row['path']).read_bytes()
        lines = raw.splitlines(keepends=True)
        assert len(raw) == row['bytes'] and len(lines) == row['lines']
        assert digest(raw) == row['pinned_sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == row['git_blob']
        assert digest(canonical(row['path_ledger_row_at_recording'])) == row['path_ledger_row_sha256']
        assert row['execution_verified'] is False
        for start, end in row['line_ranges']:
            assert 1 <= start <= end <= len(lines)
        for chunk in row.get('range_sha256', []):
            assert digest(b''.join(lines[chunk['start'] - 1:chunk['end']])) == chunk['sha256']
        check_ref(row['review_ref'])
        for ref in row.get('review_refs', []):
            check_ref(ref)
        prior = row['previous_review_reuse']
        if prior:
            reused += 1
            prior_ledger = ROOT / prior['prior_ledger_ref']
            assert digest(prior_ledger.read_bytes()) == prior['prior_ledger_sha256']
            old = read(prior_ledger)[prior['prior_row_index']]
            assert old == prior['prior_row'] and digest(canonical(old)) == prior['prior_row_sha256']
            for key in ('revision', 'path', 'git_blob', 'pinned_sha256', 'bytes', 'line_ranges'):
                assert old[key] == row[key]
            assert old['line_ranges'] == [[1, len(lines)]]
            assert row['read_basis'] == 'prior_full_body_reused'
            assert old['read_receipt'] == prior['original_read_receipt'] == row['read_receipt']
            prior_review = ROOT / prior['prior_review_ref'].split('#')[0]
            assert digest(prior_review.read_bytes()) == prior['prior_review_sha256']
            check_ref(prior['prior_review_ref'])
    assert reused == 12
    for name, sha in checkpoint['artifact_sha256'].items():
        assert digest((OUT / name).read_bytes()) == sha
    artifacts = {}
    for path in sorted(OUT.iterdir()):
        if not path.is_file() or path.name == 'record-validation.json':
            continue
        raw = path.read_bytes()
        body = raw.decode('utf-8')
        assert not raw.startswith(b'\xef\xbb\xbf') and b'\r' not in raw
        assert raw.endswith(b'\n') and not raw.endswith(b'\n\n')
        assert all(line == line.rstrip() for line in body.splitlines())
        if path.suffix == '.py':
            ast.parse(body)
        elif path.suffix == '.json':
            json.loads(body)
        artifacts[path.name] = digest(raw)
    result = {
        'status': 'own_static_metadata_checks_passed',
        'primary_count': 36, 'primary_bytes': 117515,
        'primary_fresh_full': 30, 'primary_prior_full_body_reused': 6,
        'supporting_rows': 41, 'supporting_fresh_ranges': 35,
        'supporting_prior_full_body_reused': 6,
        'prior_bindings_verified': reused,
        'source_execution_count': 0, 'upstream_test_count': 0,
        'source_runtime_or_shared_coverage_modified': False,
        'raw_blob_size_sha256_ranges_refs_prior_rows_verified': True,
        'utf8_no_bom_no_cr_exactly_one_trailing_lf_no_trailing_whitespace': True,
        'korean_semantic_readback_receipts': ['5d3cdb', 'c79c07', '164ff2'],
        'readback_final_edit': 'i07 grammar and installed live/backup target scope clarified; source SKILL read is not denied.',
        'whole_closure_os_model_human_license_actual_claude_adoption_complete': False,
        'artifact_sha256': artifacts,
        'review_ref': 'docs/full-analysis/baldrix-kha-entrypoints-002/review.md#scope',
    }
    target = OUT / 'record-validation.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, ensure_ascii=True))
    print('record_validation_sha256=' + digest(target.read_bytes()))


if __name__ == '__main__':
    main()
