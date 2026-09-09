"""Record only inert review metadata; never execute or import upstream."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
BASE = 'docs/full-analysis/baldrix-kha-entrypoints-001/'
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


inventory = {row['path']: row for row in read('.runtime/absorption/sources/baldrix/manifest.json')['inventory']}
scope = read(BASE + 'scope.json')
prior = read(BASE + 'prior-path-ledger.json')
reuse = read(BASE + 'reuse-candidates.json')
remaining = ['Unlisted direct/transitive implementation/config/caller/tests remain pending.',
             'Source execution/import/collection/probe/network/install and actual Claude are zero.',
             'License, Windows/Linux/WSL, qualified models, real human acceptance remain pending.',
             'Whole subsystem closure, Zeus equivalence and adoption approval are false.']


def identity(path, ranges):
    raw = (PIN / path).read_bytes()
    item = inventory[path]
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    assert blob == item['object'] and len(raw) == item['bytes'], path
    assert item.get('snapshot_sha256') in (None, sha(raw)), path
    lines = raw.splitlines(keepends=True)
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


def bound_prior(ledger_path, row):
    review_path = row['review_ref'].split('#')[0]
    folder = (ROOT / ledger_path).parent
    evidence = []
    for name in ['read-receipts.json', 'read-plan.json', 'checkpoint.json', 'validation.json',
                 'verification-receipt.json']:
        path = folder / name
        if path.exists():
            evidence.append({'ref': path.relative_to(ROOT).as_posix(), 'sha256': sha(path.read_bytes())})
    ranges = row['read_ranges']
    ranges = [[entry['start'], entry['end']] if isinstance(entry, dict) else entry for entry in ranges]
    ident = identity(row['path'], ranges)
    assert row['revision'] == REV and row['git_blob'] == ident['git_blob']
    assert row['pinned_sha256'] == ident['pinned_sha256']
    return {'ledger_ref': ledger_path, 'ledger_sha256': sha((ROOT / ledger_path).read_bytes()),
            'original_row': row, 'review_ref': row['review_ref'],
            'review_sha256': sha((ROOT / review_path).read_bytes()), 'original_receipt_refs': evidence,
            'read_ranges': ranges, 'fresh_read_claim': False}


# Reuse prior exact workflow and helper evidence, not a new read/coverage claim.
workflow_names = ['add-phase', 'next', 'analyze-dependencies', 'cleanup', 'audit-milestone',
                  'health', 'audit-uat', 'note', 'add-todo', 'discuss-phase',
                  'discuss-phase-assumptions', 'discuss-phase-power', 'complete-milestone',
                  'do', 'execute-phase', 'explore', 'forensics', 'add-tests', 'help', 'import',
                  'insert-phase', 'list-workspaces', 'map-codebase', 'manager',
                  'milestone-summary', 'new-milestone', 'new-project', 'new-workspace']
support_reuse = []
for number in [1, 2, 3]:
    folder = f'docs/full-analysis/baldrix-gsd-workflows-00{number}/'
    for row in read(folder + 'files.json'):
        if Path(row['path']).stem in workflow_names:
            support_reuse.append(bound_prior(folder + 'files.json', row))
    name = 'supporting-evidence.json' if number == 3 else 'supporting.json'
    for row in read(folder + name):
        if not row['path'].startswith('skills/'):
            support_reuse.append(bound_prior(folder + name, row))
dump('supporting-reuse.json', support_reuse)

fresh_specs = [
    ('scripts/validators/ai_spec_eval_coverage.py', [[71, 237]], [3], ['1c5f64', 'c83fdb']),
    ('scripts/tests/test_ai_spec_eval_coverage.py', [[1, 214]], [3], ['c83fdb', 'ac9609']),
    ('get-shit-done/bin/lib/phase.cjs', [[87, 153]], [9], ['1c5f64', '41348f']),
    ('get-shit-done/bin/lib/commands.cjs', [[38, 56]], [9, 15], ['1c5f64']),
    ('get-shit-done/workflows/plant-seed.md', [[1, 169]], [11], ['1c5f64']),
    ('get-shit-done/bin/lib/intel.cjs', [[1, 122], [183, 344], [389, 474]], [25],
     ['41348f', 'c83fdb', 'ac9609']),
    ('agents/kha-debugger.md', [[900, 941], [992, 1128], [1360, 1385]], [16], ['41348f']),
    ('get-shit-done/bin/gsd-tools.cjs', [[978, 1044]], [25], ['c83fdb']),
]
support = []
for path, ranges, indexes, chunks in fresh_specs:
    row = identity(path, ranges)
    row.update(read_method='fresh direct supporting ranges', read_extent='full'
               if ranges == [[1, row['line_count']]] else 'partial',
               primary_indexes=indexes, tool_output_chunks=chunks, counted_as_primary=False,
               review_ref=BASE + 'file-reviews.md#file-' + f'{indexes[0]:02}')
    support.append(row)
dump('supporting-evidence.json', support)

files = []
notes = (OUT / 'file-reviews.md').read_text(encoding='utf-8')
assert len(re.findall(r'<a id="file-\d+"></a>', notes)) == 33
for index, old in enumerate(prior, 1):
    path = old['path']
    assert old['disposition'] == 'unreviewed'
    total = len((PIN / path).read_bytes().splitlines())
    row = identity(path, [[1, total]])
    assert row['git_blob'] == old['git_blob'] and row['pinned_sha256'] == old['pinned_sha256']
    prior_read = None
    if path in reuse:
        candidate = reuse[path]
        prior_read = bound_prior(candidate['ledger_ref'], candidate['original_row'])
        assert prior_read['read_ranges'] == [[1, total]]
    start = notes.index(f'<a id="file-{index:02}"></a>')
    end = notes.find('<a id="file-', start + 1)
    rationale = notes[start:end if end >= 0 else None].strip()
    row.update(disposition='semantically_reviewed', primary_status='body_reviewed_call_test_trace_pending',
               read_extent='full', read_method='prior_full_body_reused' if prior_read else 'fresh_full_body_read',
               prior_full_body_reused=bool(prior_read), prior_reuse=prior_read,
               fresh_supplemental_ranges=[[1, 24]] if prior_read else [],
               fresh_supplemental_range_receipts=identity(path, [[1, 24]])['range_receipts'] if prior_read else [],
               fresh_supplemental_tool_chunk='45170d' if prior_read else None,
               fresh_full_tool_chunk=None if prior_read else ('6390d0' if index in [3, 9, 11] else '793b7f'),
               prior_path_ledger_row=old, prior_path_ledger_snapshot_sha256=scope['ledger_sha256'],
               prior_snapshot_ref=BASE + 'prior-path-ledger.json',
               scope_sha256=scope['scope_sha256'], review_ref=BASE + f'file-reviews.md#file-{index:02}',
               semantic_rationale=rationale,
               test_limits='Static only. Fifteen synthetic validator test functions read, none run; other tests closure pending.',
               source_executed=False, adoption_decision='defer; preserve defenses as adaptation proposals only',
               whole_analysis_complete=False, transitive_closure_complete=False, adoption_ready=False,
               actual_claude_review_complete=False, license_complete=False,
               platform_validation_complete=False, model_qualification_complete=False,
               human_acceptance_complete=False,
               zeus_mapping='Git approved eight-stage definitions; PG runtime attempts, evidence, leases and human acceptance. No current equivalence claim.',
               supporting_refs=[BASE + 'supporting-evidence.json', BASE + 'supporting-reuse.json'])
    files.append(row)
dump('files.json', files)
partitions = read('docs/full-analysis/partitions.json')
dump('partition-membership.json', [{'path': path, 'partitions': [entry['partition'] for entry in partitions
      if {'source': 'baldrix', 'path': path} in entry['paths']]} for path in scope['paths']])
dump('remaining.json', {'primary_body_unread': [], 'remaining': remaining})
dump('read-receipts.json', {
    'fresh_full_primary_chunks': ['6390d0', '793b7f'], 'fresh_header_supplement_chunk': '45170d',
    'failed_read': {'chunk': 'db6ee4', 'error': 'cp949 UnicodeEncodeError after first two lines; no full-read credit',
                    'recovered_by': '6390d0 using python -X utf8, source never executed'},
    'metadata_check_failure': {'chunk': 'bd6f94', 'error': 'Checker matched its own literal three question marks.',
                               'correction': 'Build sentinel with chr(63)*3; no original bytes or semantic scope changed.'},
    'review_readback_chunks': ['70d84c', '3c6c98'],
    'owned_korean_full_readback': {'chunk': '3b7ac7', 'result': 'review.md and all 33 per-file sections read back without truncation; Korean meaning retained',
                                  'earlier_failed_chunk': 'd34e6c', 'failure': 'PowerShell quoting broke inline Python readback; no write or source execution'},
    'prior_review_reads': 'def6b3 was truncated; relevant omitted sections read separately, not full fresh review claim.',
    'search_receipts': [{'chunk': '6379e8', 'query': 'AI-SPEC literal in skill/workflow plan-phase',
                         'result': 'no matches; no whole-consumer absence proof'},
                        {'chunk': 'ac9609', 'query': 'seed case-insensitive lines in new-milestone.md', 'result': []},
                        {'chunk': 'f6eb89', 'query': 'intelStatus in bin *test*, ROOT CAUSE CANDIDATES in scripts/tests',
                         'result': 'no matches; names/other locations remain pending'}],
    'source_execution_count': 0, 'source_collection_count': 0,
    'source_network_install_import_probe_count': 0, 'actual_claude_count': 0})
dump('checkpoint.json', {'scope': 'skills directory lexicographic kha-add-phase through kha-new-workspace inclusive',
                        'revision': REV, 'zeus_head_at_start': '7eaa42737d0cce4e675c9f309c215ce1e1d97ed4',
                        'scope_sha256': scope['scope_sha256'], 'primary_paths': 33, 'primary_bytes': 118053,
                        'prior_primary_unreviewed': 33, 'fresh_primary_full_body_read': 7,
                        'prior_full_body_reused': 26, 'fresh_header_supplements': 26,
                        'primary_body_unread': [], 'fresh_supporting_paths': 8,
                        'fresh_supporting_full_bodies': 2, 'fresh_supporting_partial_bodies': 6,
                        'source_test_functions_read_not_run': 15, 'tests_executed': 0,
                        'source_execution_import_collection_probe_network_install_count': 0,
                        'whole_analysis_complete': False, 'transitive_closure_complete': False,
                        'actual_claude_review_complete': False, 'license_complete': False,
                        'platform_validation_complete': False, 'model_qualification_complete': False,
                        'human_acceptance_complete': False, 'adoption_ready': False,
                        'remaining': remaining, 'files_sha256': sha((OUT / 'files.json').read_bytes()),
                        'review_sha256': sha((OUT / 'review.md').read_bytes())})
print('Recorded 33 primary dispositions: 7 fresh full reads, 26 byte-bound prior full reuses; source execution0.')
