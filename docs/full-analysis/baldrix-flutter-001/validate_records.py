"""Independently verify this folder's static metadata without source execution."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
PINNED = ROOT / '.runtime/absorption/sources/baldrix/pinned'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    files = load(OUT / 'files.json')
    supports = load(OUT / 'supporting-evidence.json')
    assert len(files) == 22 and sum(r['bytes'] for r in files) == 208437
    assert len(supports) == 22 and len({r['path'] for r in files}) == 22
    for row in files + supports:
        raw = (PINNED / row['path']).read_bytes()
        assert row['bytes'] == len(raw) and row['pinned_sha256'] == sha(raw)
        assert row['git_blob'] == hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        assert row['revision'] == 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2'
        old = row['path_ledger_row_at_recording']
        canonical = json.dumps(old, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        assert sha(canonical) == row['path_ledger_row_sha256']
        assert row['previous_review_reuse'] is None and row['execution_verified'] is False
        lines = raw.splitlines(keepends=True)
        assert len(lines) == row['lines']
        for start, end in row['line_ranges']:
            assert 1 <= start <= end <= len(lines)
        if row['disposition'] == 'semantically_reviewed':
            assert row['line_ranges'] == [[1, len(lines)]]
            assert old['disposition'] == 'unreviewed'
        for chunk in row.get('range_sha256', []):
            assert sha(b''.join(lines[chunk['start'] - 1:chunk['end']])) == chunk['sha256']
        refs = [row['review_ref']] + row.get('review_refs', []) + row.get('primary_comparison_refs', [])
        for ref in refs:
            path, anchor = ref.split('#')
            assert f'<a id="{anchor}"></a>' in (ROOT / path).read_text(encoding='utf-8')
    checkpoint = load(OUT / 'checkpoint.json')
    for name, digest in checkpoint['artifact_sha256'].items():
        assert sha((OUT / name).read_bytes()) == digest
    artifacts = {}
    for path in sorted(OUT.iterdir()):
        if not path.is_file() or path.name == 'record-validation.json':
            continue
        raw = path.read_bytes()
        body = raw.decode('utf-8')
        assert b'\r' not in raw and not raw.startswith(b'\xef\xbb\xbf')
        assert raw.endswith(b'\n') and not raw.endswith(b'\n\n')
        assert all(line == line.rstrip() for line in body.splitlines())
        if path.suffix == '.json':
            json.loads(body)
        elif path.suffix == '.py':
            ast.parse(body)
        artifacts[path.name] = sha(raw)
    result = {
        'status': 'independent_own_metadata_checks_passed', 'primary_count': 22,
        'primary_bytes': 208437, 'primary_lines': 5075,
        'fresh_primary_full_bodies': 22, 'reused_primary_full_bodies': 0,
        'supporting_rows': 22, 'supporting_lines': 2076,
        'raw_blob_sha256_bytes_ranges_refs_prior_row_binding_verified': True,
        'utf8_no_bom_no_cr_exactly_one_trailing_lf_no_trailing_whitespace': True,
        'korean_body_readback_receipts': ['ca5e92', 'b554e3'],
        'final_body_typo_edit': 'i20: approval phrase clarified; no substantive finding changed.',
        'source_execution_count': 0, 'source_test_count': 0,
        'full_analysis_complete': False, 'adoption_approved': False,
        'artifact_sha256': artifacts,
        'review_ref': 'docs/full-analysis/baldrix-flutter-001/review.md#scope',
    }
    path = OUT / 'record-validation.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, ensure_ascii=True))
    print('record_validation_sha256=' + sha(path.read_bytes()))


if __name__ == '__main__':
    main()
