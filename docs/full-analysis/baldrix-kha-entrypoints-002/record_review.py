"""Record static body reviews and explicitly byte-bound prior full-body reuse."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
PINNED = SOURCE / 'pinned'
REVISION = 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2'
START_HEAD = '7eaa42737d0cce4e675c9f309c215ce1e1d97ed4'
REVIEW = 'docs/full-analysis/baldrix-kha-entrypoints-002/review.md'
PRIOR = 'docs/full-analysis/baldrix-gsd-workflows-005'
PRIOR_REVIEW_SHA = '213f2d1ff4653736ff92f9d9719c87cece5f16b8aee46edb76396c9c44b52237'
REUSED = {
    'kha-revert-work': ('i03', 'undo'),
    'kha-review-ui': ('i02', 'ui-review'),
    'kha-self-update': ('i04', 'update'),
    'kha-spec-ui-phase': ('i01', 'ui-phase'),
    'kha-validate-nyquist-phase': ('i05', 'validate-phase'),
    'kha-verify-uat': ('i07', 'verify-work'),
}
FRESH_RECEIPTS = {
    **dict.fromkeys(range(1, 7), '06d2c4'),
    **dict.fromkeys(range(7, 12), 'beada3'),
    **dict.fromkeys([12, 13, 15, 16, 18], '562537'),
    **dict.fromkeys([19, 20, 21, 23, 24, 25, 27], '72c5ba'),
    **dict.fromkeys([28, 29, 30, 31, 32, 34, 36], '63be3f'),
}
# Each interval was freshly displayed and read. Other ranges are not covered.
WORKFLOWS = {
    'pause-work': ([[61, 103], [204, 224]], [1], 'ba4d88'),
    'resume-project': ([[62, 113]], [13], 'ba4d88'),
    'list-phase-assumptions': ([[129, 150]], [2], 'ba4d88'),
    'plan-milestone-gaps': ([[100, 151]], [3], 'ba4d88'),
    'plan-phase': ([[771, 794], [868, 934]], [4, 12], 'ba4d88'),
    'pr-branch': ([[72, 129]], [5], 'ba4d88'),
    'stats': ([[11, 60]], [6], 'ba4d88'),
    'audit-fix': ([[13, 125]], [8], 'ba4d88'),
    'code-review-fix': ([[91, 136], [180, 230], [345, 379]], [9], 'ba4d88'),
    'remove-phase': ([[41, 110]], [10], 'ba4d88'),
    'remove-workspace': ([[11, 90]], [11], 'ba4d88'),
    'code-review': ([[307, 341], [381, 412]], [15], 'e695ec'),
    'review': ([[13, 69], [141, 187]], [16], 'e695ec'),
    'quick': ([[24, 95], [787, 820]], [18], 'e695ec'),
    'autonomous': ([[15, 77], [792, 845], [975, 1012]], [19], 'e695ec'),
    'fast': ([[24, 77]], [20], 'e695ec'),
    'scan': ([[27, 101]], [21], 'e695ec'),
    'session-report': ([[11, 69]], [23], 'e695ec'),
    'settings': ([[171, 249]], [24, 25], 'e695ec'),
    'progress': ([[138, 195], [295, 339]], [27], 'e695ec'),
    'ship': ([[38, 161]], [28], 'c4671c'),
    'docs-update': ([[196, 220], [332, 370], [948, 997]], [29], 'c4671c'),
    'check-todos': ([[102, 162]], [31], 'c4671c'),
    'profile-user': ([[18, 144], [416, 435]], [32], ['c4671c', '645ac1']),
    'secure-phase': ([[35, 164]], [34], 'c4671c'),
}
HELPERS = {
    'get-shit-done/bin/lib/config.cjs': ([[405, 459]], [24, 25], '645ac1'),
    'get-shit-done/bin/lib/model-profiles.cjs': ([[1, 33]], [24, 25], '645ac1'),
    'get-shit-done/bin/lib/init.cjs': ([[538, 586], [636, 695], [1369, 1438]], [11, 12, 35], ['645ac1', '8bec35']),
    'get-shit-done/bin/lib/phase.cjs': ([[313, 390], [587, 650]], [10, 30], ['645ac1', '8bec35']),
    'get-shit-done/bin/lib/workstream.cjs': ([[279, 367]], [36], '645ac1'),
    'get-shit-done/bin/lib/commands.cjs': ([[250, 278], [315, 347], [808, 944]], [1, 3, 6, 30, 31, 34], ['645ac1', '8bec35']),
    'get-shit-done/bin/lib/core.cjs': ([[648, 665], [1303, 1334]], [4, 12, 24, 25, 36], '8bec35'),
    'scripts/cli/phase_graph.py': ([[1, 86]], [4], '645ac1'),
    'scripts/tests/test_phase_graph_builder.py': ([[1, 87], [165, 192]], [4], ['645ac1', '8bec35']),
    'scripts/tests/test_phase_graph_query.py': ([[1, 75], [97, 119]], [4], ['645ac1', '8bec35']),
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(row) -> bytes:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(name: str, value) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def selected(path: str) -> bool:
    parts = path.split('/')
    return len(parts) >= 3 and parts[0] == 'skills' and parts[1].startswith('kha-') and parts[1] > 'kha-new-workspace'


def main() -> None:
    manifest_path = SOURCE / 'manifest.json'
    partition_path = ROOT / 'docs/full-analysis/partitions.json'
    ledger_path = ROOT / 'docs/full-analysis/path-ledger.json'
    manifest = read_json(manifest_path)
    assert manifest['revision'] == REVISION
    inventory = {r['path']: r for r in manifest['inventory']}
    all_ledger = read_json(ledger_path)
    ledger = {r['path']: (i, r) for i, r in enumerate(all_ledger) if r['source'] == 'baldrix'}
    targets = sorted(p for p in inventory if selected(p))
    assert len(targets) == 36 and all(p.endswith('/SKILL.md') for p in targets)
    assert targets == sorted(p for p in ledger if selected(p))
    partitions = [p for p in read_json(partition_path) if any(x['source'] == 'baldrix' and x['path'] in targets for x in p['paths'])]
    assert len(partitions) == 36 and all(len(p['paths']) == 1 for p in partitions)
    by_path = {p['paths'][0]['path']: p for p in partitions}
    review = (ROOT / REVIEW).read_text(encoding='utf-8')
    anchors = set(re.findall(r'<a id="([^"]+)"></a>', review))
    assert anchors == {'scope', 'trace', 'zeus', 'unknowns'} | {f'i{i:02d}' for i in range(1, 37)}
    assert '실제 사람' in review and '삼성' in review and '??' not in review
    assert sha((ROOT / PRIOR / 'review.md').read_bytes()) == PRIOR_REVIEW_SHA

    def identity(path: str) -> dict:
        raw = (PINNED / path).read_bytes()
        raw.decode('utf-8')
        entry = inventory[path]
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        digest = sha(raw)
        assert blob == entry['object'] and len(raw) == entry['bytes'], path
        if entry.get('snapshot_sha256') is not None:
            assert digest == entry['snapshot_sha256'], path
        index, old = ledger[path]
        assert old['revision'] == REVISION and old['git_blob'] == blob and old['pinned_sha256'] == digest
        assert old['bytes'] == len(raw)
        return {
            'source': 'baldrix', 'path': path, 'revision': REVISION,
            'pinned_sha256': digest, 'git_blob': blob, 'bytes': len(raw), 'lines': len(raw.splitlines()),
            'manifest_snapshot_sha256_present': entry.get('snapshot_sha256') is not None,
            'manifest_snapshot_sha256': entry.get('snapshot_sha256'),
            'hash_verification': 'raw_git_blob_bytes_and_separate_sha256_compared_to_manifest_when_present_and_path_ledger',
            'path_ledger_row_index': index, 'path_ledger_disposition_at_recording': old['disposition'],
            'path_ledger_row_at_recording': old, 'path_ledger_row_sha256': sha(canonical(old)),
            'upstream_disposition_unchanged': entry['disposition'], 'tests_executed': [],
            'execution_verified': False, 'transitive_closure_complete': False,
            'actual_claude_review_complete': False, 'license_review_complete': False,
            'model_qualification_verified': False, 'os_runtime_verified': False,
            'human_acceptance_verified': False, 'adoption_status': 'not_approved_not_incorporated',
        }

    def prior_binding(path: str, filename: str, anchor: str) -> dict:
        prior_path = ROOT / PRIOR / filename
        rows = read_json(prior_path)
        matches = [(i, r) for i, r in enumerate(rows) if r['path'] == path]
        assert len(matches) == 1
        index, old = matches[0]
        raw = (PINNED / path).read_bytes()
        assert old['revision'] == REVISION and old['pinned_sha256'] == sha(raw)
        assert old['git_blob'] == hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        assert old['bytes'] == len(raw) and old['line_ranges'] == [[1, len(raw.splitlines())]]
        assert old['read_extent'] in ('full_body', 'full_body_supporting')
        ref = f'{PRIOR}/review.md#{anchor}'
        assert ref in old.get('review_refs', [old['review_ref']])
        return {
            'prior_ledger_ref': f'{PRIOR}/{filename}', 'prior_ledger_sha256': sha(prior_path.read_bytes()),
            'prior_row_index': index, 'prior_row_sha256': sha(canonical(old)),
            'prior_row': old, 'prior_review_ref': ref, 'prior_review_sha256': PRIOR_REVIEW_SHA,
            'original_read_receipt': old['read_receipt'], 'original_line_ranges': old['line_ranges'],
            'reuse_qualification': 'identical_revision_raw_blob_bytes_sha256_full_body_and_per_file_semantic_caller_risk_review',
        }

    files = []
    for i, path in enumerate(targets, 1):
        row = identity(path)
        assert row['path_ledger_disposition_at_recording'] == 'unreviewed'
        name = path.split('/')[1]
        anchor = f'i{i:02d}'
        section = review.split(f'<a id="{anchor}"></a>', 1)[1].split('<a id=', 1)[0].strip()
        assert f'{name}/SKILL.md' in section
        reuse = prior_binding(path, 'supporting-evidence.json', REUSED[name][0]) if name in REUSED else None
        row.update({
            'partition': by_path[path]['partition'], 'scope_sha256': by_path[path]['scope_sha256'],
            'disposition': 'semantically_reviewed', 'read_extent': 'full_body',
            'line_ranges': [[1, row['lines']]],
            'read_basis': 'prior_full_body_reused' if reuse else 'fresh_displayed_full_primary_body_current_review',
            'read_receipt': reuse['original_read_receipt'] if reuse else FRESH_RECEIPTS[i],
            'previous_review_reuse': reuse, 'review_ref': f'{REVIEW}#{anchor}',
            'semantic_summary': section.split('\n\n', 1)[1],
            'caller_or_dependency_trace': [],
            'test_kind': 'entry_skill_declaration_not_executed_test_suite',
            'denominator_basis': '36 primary: 30 fresh full reads, 6 exact prior full-body reused; 0 source execution.',
        })
        files.append(row)
    assert sum(r['bytes'] for r in files) == 117515
    assert len([r for r in files if r['previous_review_reuse']]) == 6

    supports = []

    def support(path, ranges, refs, receipt, reuse=None):
        row = identity(path)
        assert all(1 <= a <= b <= row['lines'] for a, b in ranges)
        raw_lines = (PINNED / path).read_bytes().splitlines(keepends=True)
        row.update({
            'support_id': f'S{len(supports) + 1:02d}', 'disposition': 'supporting_read_only',
            'line_ranges': ranges, 'read_extent': 'full_body_supporting' if ranges == [[1, row['lines']]] else 'explicit_ranges_only',
            'read_basis': 'prior_full_body_reused' if reuse else 'fresh_displayed_supporting_intervals_current_review',
            'read_receipt': receipt, 'previous_review_reuse': reuse,
            'review_ref': f'{REVIEW}#trace', 'review_refs': [f'{REVIEW}#trace'] + [f'{REVIEW}#i{i:02d}' for i in refs],
            'counted_as_primary_body': False,
            'range_sha256': [{'start': a, 'end': b, 'sha256': sha(b''.join(raw_lines[a - 1:b]))} for a, b in ranges],
            'purpose': 'Direct entry/workflow/helper/config/test contract comparison; no source execution.',
        })
        supports.append(row)
        for i in refs:
            files[i - 1]['caller_or_dependency_trace'].append(path)

    for name, (ranges, refs, receipt) in WORKFLOWS.items():
        support(f'get-shit-done/workflows/{name}.md', ranges, refs, receipt)
    for path, (ranges, refs, receipt) in HELPERS.items():
        support(path, ranges, refs, receipt)
    for name, (anchor, workflow) in REUSED.items():
        path = f'get-shit-done/workflows/{workflow}.md'
        reuse = prior_binding(path, 'files.json', anchor)
        i = next(i for i, row in enumerate(files, 1) if row['path'] == f'skills/{name}/SKILL.md')
        support(path, reuse['original_line_ranges'], [i], reuse['original_read_receipt'], reuse)
    assert len(supports) == 41
    write_json('files.json', files)
    write_json('supporting-evidence.json', supports)
    write_json('remaining.json', {
        'primary_body_remaining': [],
        'supporting_trace_remaining': [
            'All source ranges not explicitly listed; complete loader/caller/helper/config/test/hook closure.',
            'Actual command execution, graph test complete bodies and runner collection, PR/installer/rollback/device/OS observations.',
            'Authoritative approval actor/spec/artifact hashes, PG task generation/lease, interruption and concurrency recovery.',
            'Actual Claude independence, model qualifications, license/dependency/source attribution and acceptance.',
            'Samsung phone/tablet Device Farm SDK/MCP/live/replay remains deferred.',
        ],
        'upstream_executions': 0, 'upstream_imports': 0, 'collections': 0, 'probes': 0,
        'network_calls': 0, 'installs': 0, 'model_calls': 0, 'actual_claude_calls': 0,
        'live_state_accessed': False, 'credentials_accessed': False, 'blocked_probe_retried': False,
        'full_analysis_complete': False, 'transitive_closure_complete': False, 'adopted': False,
        'actual_claude_review_complete': False, 'license_review_complete': False,
        'model_qualification_verified': False, 'os_runtime_verified': False, 'human_acceptance_verified': False,
        'review_ref': f'{REVIEW}#unknowns',
    })
    refs = [r['review_ref'] for r in files] + [ref for r in supports for ref in r['review_refs']]
    for row in files + supports:
        if row['previous_review_reuse']:
            refs.append(row['previous_review_reuse']['prior_review_ref'])
    for ref in refs:
        path, anchor = ref.split('#')
        assert f'<a id="{anchor}"></a>' in (ROOT / path).read_text(encoding='utf-8')
    fresh = [r for r in files if not r['previous_review_reuse']]
    reused = [r for r in files if r['previous_review_reuse']]
    verification = {
        'primary_count': len(files), 'primary_bytes': sum(r['bytes'] for r in files),
        'primary_lines': sum(r['lines'] for r in files),
        'fresh_primary_count': len(fresh), 'fresh_primary_bytes': sum(r['bytes'] for r in fresh),
        'fresh_primary_lines': sum(r['lines'] for r in fresh),
        'prior_full_body_reused_count': len(reused), 'prior_full_body_reused_bytes': sum(r['bytes'] for r in reused),
        'prior_full_body_reused_lines': sum(r['lines'] for r in reused),
        'supporting_rows': len(supports), 'fresh_supporting_rows': 35, 'prior_full_supporting_reused_rows': 6,
        'fresh_supporting_read_lines': sum(b - a + 1 for r in supports if not r['previous_review_reuse'] for a, b in r['line_ranges']),
        'prior_supporting_reused_lines': sum(b - a + 1 for r in supports if r['previous_review_reuse'] for a, b in r['line_ranges']),
        'review_refs_checked': len(refs), 'raw_blob_size_sha256_verified': True,
        'range_bounds_verified': True, 'prior_rows_full_extent_and_raw_identity_verified': True,
        'upstream_tests_run': False, 'tests_read_in_part': [p for p in HELPERS if '/tests/' in p],
        'search_only_not_body': ['214a29', '89e8be', '74c3e2', 'bec13e'],
        'failed_search_not_counted': 'bd2d52: PowerShell brace-list parsing error; no source execution or body coverage.',
        'missing_manifest_snapshot_sha256_paths': [r['path'] for r in files + supports if not r['manifest_snapshot_sha256_present']],
        'full_analysis_complete': False, 'adoption_approved': False,
    }
    write_json('verification.json', verification)
    artifact_names = ['review.md', 'record_review.py', 'files.json', 'supporting-evidence.json', 'remaining.json', 'verification.json']
    for name in artifact_names:
        raw = (OUT / name).read_bytes()
        content = raw.decode('utf-8')
        assert raw.endswith(b'\n') and not raw.endswith(b'\n\n') and b'\r' not in raw
        assert all(line == line.rstrip() for line in content.splitlines()), name
        if name.endswith('.py'):
            ast.parse(content)
    artifact_sha = {name: sha((OUT / name).read_bytes()) for name in artifact_names}
    inputs = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p.read_bytes()) for p in (manifest_path, partition_path, ledger_path)}
    write_json('checkpoint.json', {
        'partitions': [p['partition'] for p in partitions],
        'partition_scopes': {p['partition']: p['scope_sha256'] for p in partitions},
        'revision': REVISION, 'zeus_head_at_start': START_HEAD,
        'selection': 'Baldrix skills/kha-* directory name lexicographically greater than kha-new-workspace',
        'status': 'bounded_static_review_complete', 'primary_files': 36, 'primary_bytes': 117515,
        'fresh_primary_files': 30, 'prior_full_body_reused_files': 6,
        'supporting_rows': 41, 'fresh_supporting_rows': 35, 'prior_full_supporting_reused_rows': 6,
        'input_sha256_at_recording': inputs, 'artifact_sha256': artifact_sha,
        'scope_complete': True, 'subsystem_complete': False, 'full_analysis_complete': False,
        'transitive_closure_complete': False, 'adoption_approved': False,
        'actual_claude_review_complete': False, 'license_review_complete': False,
        'model_qualification_verified': False, 'os_runtime_verified': False, 'human_acceptance_verified': False,
        'source_execution_count': 0, 'source_import_count': 0, 'collection_count': 0,
        'probe_count': 0, 'network_count': 0, 'model_count': 0, 'install_count': 0,
        'live_state_accessed': False, 'credentials_accessed': False,
        'blocked_probe_retried_or_bypassed': False, 'source_runtime_shared_coverage_modified': False,
        'commit_or_push_performed': False, 'review_ref': f'{REVIEW}#scope',
    })
    print(json.dumps(verification, ensure_ascii=True))
    print('review_sha256=' + artifact_sha['review.md'])
    print('checkpoint_sha256=' + sha((OUT / 'checkpoint.json').read_bytes()))


if __name__ == '__main__':
    main()
