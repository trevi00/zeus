"""Byte-bound static review recorder. No upstream import or execution."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
BASE = 'docs/full-analysis/baldrix-atlas-validators-001/'
OUT = ROOT / BASE
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'
REV = 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_bytes())


def dump(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8', newline='\n')


scope = read(BASE + 'scope.json')
prior = read(BASE + 'prior-path-ledger.json')
manifest = read('.runtime/absorption/sources/baldrix/manifest.json')
assert manifest['revision'] == REV
inventory = {row['path']: row for row in manifest['inventory']}
remaining = ['Full caller/config/transitive implementation/test closure remains pending.',
             'Original imports/execution/collection/probes/network/install/Claude0.',
             'Original event logs, historical benchmark receipts, generation provenance and license unverified.',
             'Windows/Linux/WSL, qualified models, real human acceptance and Zeus adoption/equivalence pending.']


def identity(path, ranges=None):
    raw = (PIN / path).read_bytes()
    item = inventory[path]
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    assert blob == item['object'] and len(raw) == item['bytes'], path
    assert item.get('snapshot_sha256') in (None, sha(raw)), path
    lines = raw.splitlines(keepends=True)
    ranges = ranges or [[1, len(lines)]]
    for start, end in ranges:
        assert 1 <= start <= end <= len(lines), (path, start, end, len(lines))
    return {'source': 'baldrix', 'path': path, 'revision': REV, 'git_blob': blob,
            'pinned_sha256': sha(raw), 'pinned_bytes': len(raw), 'manifest_bytes': item['bytes'],
            'line_count': len(lines), 'read_ranges': ranges,
            'range_receipts': [{'start': start, 'end': end,
                                'raw_range_sha256': sha(b''.join(lines[start - 1:end]))}
                               for start, end in ranges],
            'manifest_sha256_status': 'matched' if item.get('snapshot_sha256') else 'absent_computed_only',
            'raw_git_blob_status': 'matched', 'tests_executed': [], 'remaining': remaining}


# Prior implementation bodies: explicit same-byte reuse, no fresh read claim.
module_names = [Path(path).stem.replace('-', '_') for path in scope['paths'] if '/artifacts/' in path]
module_names.append('__init__')
support_reuse = []
for number in [1, 2]:
    folder = f'docs/full-analysis/baldrix-validators-00{number}/'
    ledger_path = folder + 'files.json'
    for row in read(ledger_path):
        if Path(row['path']).stem not in module_names:
            continue
        ident = identity(row['path'])
        assert row['revision'] == REV and row['git_blob'] == ident['git_blob']
        assert row['pinned_sha256'] == ident['pinned_sha256'] and row['read_extent'] == 'full'
        review_path = row['review_ref'].split('#')[0]
        receipts = []
        for name in ['checkpoint.json', 'checkpoint-notes.md', 'final-body-notes.md', 'supporting-evidence.json']:
            target = ROOT / folder / name
            if target.exists():
                receipts.append({'ref': target.relative_to(ROOT).as_posix(), 'sha256': sha(target.read_bytes())})
        support_reuse.append({'path': row['path'], 'identity': ident, 'ledger_ref': ledger_path,
                              'ledger_sha256': sha((ROOT / ledger_path).read_bytes()),
                              'original_row': row, 'read_ranges': [[1, ident['line_count']]],
                              'review_document_ref': review_path,
                              'review_selector': row['review_ref'].partition('#')[2],
                              'review_document_sha256': sha((ROOT / review_path).read_bytes()),
                              'original_receipt_refs': receipts,
                              'prior_full_body_reused': True, 'fresh_read_claim': False,
                              'counted_as_primary': False})
assert len(support_reuse) == 29
dump('supporting-reuse.json', support_reuse)

specs = [
    ('scripts/validators/__init__.py', [[1, 123]], [1, 26, 32, 33, 34], '338d60'),
    ('scripts/lib/staging_guard.py', [[1, 83]], [27, 31, 36, 38], '338d60'),
    ('scripts/lib/insight_index.py', [[88, 152]], [17, 30, 35, 37], '338d60'),
    ('scripts/tests/run_all.py', [[166, 279]], [1, 32, 33, 34], '338d60'),
    ('.github/workflows/ci.yml', [[1, 88]], [1, 4, 33, 34], '338d60'),
    ('scripts/cli/atlas_index.py', [[49, 94], [202, 231]], [1, 2, 3], '539dbc'),
    ('scripts/cli/validate_project.py', [[43, 76], [142, 199]], [4, 5, 6, 8, 9, 10, 11, 12, 18, 20, 21, 23, 29, 32, 33], '539dbc'),
    ('scripts/tests/test_atlas_frontmatter.py', [[1, 115]], [2], '539dbc'),
    ('scripts/tests/test_staging_guard.py', [[1, 128]], [27, 31, 36, 38], '539dbc'),
    ('scripts/lib/paths.py', [[190, 240]], [1, 2, 3], '539dbc'),
]
support = []
for path, ranges, indexes, chunk in specs:
    row = identity(path, ranges)
    row.update(read_method='fresh supporting ranges', read_extent='full'
               if ranges == [[1, row['line_count']]] else 'partial',
               tool_output_chunk=chunk, primary_indexes=indexes, counted_as_primary=False,
               review_ref=BASE + f'file-reviews.md#file-{indexes[0]:02}')
    support.append(row)
dump('supporting-evidence.json', support)

notes = (OUT / 'file-reviews.md').read_text(encoding='utf-8')
assert len(re.findall(r'<a id="file-\d+"></a>', notes)) == 38
files = []
for index, old in enumerate(prior, 1):
    path = old['path']
    row = identity(path)
    assert old['disposition'] == 'unreviewed'
    assert old['git_blob'] == row['git_blob'] and old['bytes'] == row['pinned_bytes']
    assert old['pinned_sha256'] in (None, row['pinned_sha256'])
    partition = next(entry for entry in scope['partitions'] if {'source': 'baldrix', 'path': path} in entry['paths'])
    start = notes.index(f'<a id="file-{index:02}"></a>')
    end = notes.find('<a id="file-', start + 1)
    row.update(partition=partition['partition'], scope_sha256=partition['scope_sha256'],
               disposition='semantically_reviewed', primary_status='body_reviewed_call_test_trace_pending',
               read_extent='full', read_method='fresh_full_body_read', prior_full_body_reused=False,
               tool_output_chunk='c34a69' if index <= 12 else '92af01' if index <= 29 else '1c0e43' if index <= 35 else '305f21',
               prior_path_ledger_row=old, prior_path_ledger_snapshot_sha256=scope['ledger_sha256'],
               prior_snapshot_ref=BASE + 'prior-path-ledger.json',
               review_ref=BASE + f'file-reviews.md#file-{index:02}',
               semantic_rationale=notes[start:end if end >= 0 else None].strip(),
               supporting_refs=[BASE + 'supporting-evidence.json', BASE + 'supporting-reuse.json'],
               generated_duplicate_status='Templated authored documentation; generator and original history not proven. Individually read, no duplicate exemption.',
               test_limits='No original execution. Freshly read 6 frontmatter and 7 staging-guard test functions; historical PASS is data only.',
               source_executed=False, adoption_decision='defer; behavior-specific adaptation candidates only',
               whole_analysis_complete=False, transitive_closure_complete=False, adoption_ready=False,
               actual_claude_review_complete=False, license_complete=False,
               platform_validation_complete=False, model_qualification_complete=False, human_acceptance_complete=False,
               zeus_mapping='Git eight-stage definitions and PG runtime receipt/denominator/qualification/human acceptance; no current implementation equivalence claim.')
    files.append(row)
dump('files.json', files)
dump('remaining.json', {'primary_body_unread': [], 'remaining': remaining})
dump('read-receipts.json', {'primary_full_read_chunks': ['c34a69', '92af01', '1c0e43', '305f21'],
                           'fresh_support_chunks': ['338d60', '539dbc'],
                           'prior_semantic_evidence_read_chunks': ['bf6b79', '59854b'],
                           'scope_and_rules_chunks': ['df7195', '459691', '3b51cc'],
                           'owned_korean_readback_chunk': '4754b3: review and38per-file sections, untruncated; final wording narrows unregistered registry call only',
                           'search_limits': [
                               {'chunk': '8faba4', 'result': 'scripts/validate_project.py absent; corrected path scripts/cli/validate_project.py discovered in2b74c1, fresh ranges539dbc.'},
                               {'chunk': '2b74c1', 'result': 'No artifact-validators- literal in pinned scripts py/sh. This bounded search did not establish a generator; no duplicate exemption.'},
                               {'chunk': '8faba4', 'result': 'No atlas/validators or Cycle A literal in atlas_index.py. Collector/index consumer ranges read539dbc; no automatic activation enforcement claimed.'}],
                           'source_execution_import_collection_probe_network_install_count': 0,
                           'actual_claude_count': 0})
dump('checkpoint.json', {'partitions': [entry['partition'] for entry in scope['partitions']],
                        'revision': REV, 'starting_head': scope['starting_head'],
                        'primary_paths': 38, 'primary_bytes': 84994, 'primary_fresh_full_body_read': 38,
                        'primary_full_body_reused': 0, 'prior_primary_unreviewed': 38, 'primary_body_unread': [],
                        'supporting_prior_full_body_reuse': 29, 'supporting_fresh_paths': 10,
                        'supporting_reuse_fresh_overlap': ['scripts/validators/__init__.py'],
                        'supporting_fresh_full': sum(row['read_extent'] == 'full' for row in support),
                        'supporting_fresh_partial': sum(row['read_extent'] == 'partial' for row in support),
                        'source_tests_fresh_body_read': 2, 'source_test_functions_fresh_read': 13,
                        'tests_executed': 0, 'source_execution_import_collection_probe_network_install_count': 0,
                        'actual_claude_review_complete': False, 'whole_analysis_complete': False,
                        'transitive_closure_complete': False, 'adoption_ready': False,
                        'license_complete': False, 'platform_validation_complete': False,
                        'model_qualification_complete': False, 'human_acceptance_complete': False,
                        'remaining': remaining, 'files_sha256': sha((OUT / 'files.json').read_bytes()),
                        'review_sha256': sha((OUT / 'review.md').read_bytes())})
print('Recorded38 primary fresh full; reused29 implementation bodies; source execution0.')
