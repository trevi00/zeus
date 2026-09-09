"""Record bounded inert Flutter source reads; never import the source tree."""
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
REVIEW = 'docs/full-analysis/baldrix-flutter-001/review.md'
PARTITIONS = {
    'baldrix:skills/flutter:001': 'eb181c79a3bc26353ec11eb1ad03d3bca4cf028bc17eb5e070b39c1d7cb81b05',
    'baldrix:skills/flutter:002': '533bdc65efb4a83ea0e88cc2b85156536e409450b582cc1a1ae2d8a85698e892',
}
RECEIPTS = {
    **dict.fromkeys([1, 2, 3], '7e70d9'),
    4: 'd37852', 5: ['d37852', '8f1949'], 6: 'd37852',
    7: 'f80949', 8: 'f80949', 9: '05637a', 10: '05637a',
    11: '41eb5a', 12: '41eb5a',
    **dict.fromkeys([13, 14, 15, 16], 'b2211b'),
    **dict.fromkeys([17, 18, 19], 'c7c465'),
    20: 'a3ca34', 21: '96cc0e', 22: '96cc0e',
}
SUPPORTS = {
    'skills/_pipeline/overlays/flutter.overlay.yaml': ([[1, 152]], [3, 8, 14, 15], 'f4a3c7'),
    'skills/_pipeline/stages-flutter.yaml': ([[1, 205]], [3, 8, 14, 15], 'f4a3c7'),
    'scripts/lib/frontmatter.py': ([[1, 62]], [7, 15], 'f4a3c7'),
    'scripts/handlers/prompt/skill_match.py': ([[225, 307], [340, 421]], [5, 14, 15], 'f8f9a2'),
    'scripts/validators/git_flow.py': ([[38, 111], [113, 177]], [19, 22], 'f8f9a2'),
    'scripts/lib/git_flow_override.py': ([[33, 103]], [19, 22], 'f8f9a2'),
    'scripts/lib/tech_stack.py': ([[45, 172], [175, 195]], [14, 15], ['eac558', '6b859e']),
    'scripts/lib/pipeline_stage_picker.py': ([[46, 122]], [3, 8, 14, 15], 'eac558'),
    'scripts/handlers/pre_tool/guard.py': ([[184, 252]], [19, 22], 'eac558'),
    'settings.json': ([[99, 116]], [14, 15, 19], 'eac558'),
    'scripts/tests/test_git_flow.py': ([[53, 77], [98, 138]], [19, 22], 'eac558'),
    'skills/_common/idempotency.md': ([[18, 52], [86, 126]], [2, 10, 12, 13, 20, 21], 'df9df4'),
    'skills/_common/test-driven-development.md': ([[14, 33], [53, 66], [90, 114], [191, 203]], [8], 'df9df4'),
    'skills/_common/git-flow.md': ([[37, 47], [74, 95]], [19, 22], 'df9df4'),
    'skills/_outpos/SKILL.md': ([[1, 78]], [4, 14, 15, 16, 17, 18, 21, 22], 'df9df4'),
    'scripts/lib/skill_match_render.py': ([[72, 96]], [5, 6, 15, 20], 'df9df4'),
    'scripts/lib/skill_score.py': ([[126, 270]], [15], ['df9df4', '6b859e']),
    'scripts/tests/test_mock_review_stage.py': ([[78, 94], [105, 130]], [8, 15], 'df9df4'),
    'scripts/lib/pipeline_overlay.py': ([[32, 122]], [3, 8, 14, 15], ['6b859e', 'c07135']),
    'scripts/lib/testgen.py': ([[107, 153], [240, 282]], [8], '6b859e'),
    'scripts/tests/test_tech_stack.py': ([[1, 160]], [14, 15], '6b859e'),
    'scripts/tests/test_testgen.py': ([[1, 37], [65, 83], [137, 170]], [8], 'c07135'),
}
PRIMARY_EDGES = {
    1: [6, 7, 8], 2: [4, 8, 21], 3: [8, 18], 4: [2, 5, 8, 15, 21],
    5: [6, 20], 6: [1, 5, 8], 7: [1, 8], 8: [2, 3, 5, 6, 7],
    9: [10, 11, 12, 13], 10: [9, 12, 13, 21], 11: [9, 12, 18],
    12: [9, 10, 11, 13], 13: [9, 10, 12], 14: [15, 16, 17, 18, 21, 22],
    15: [16, 17, 18, 19, 20, 21, 22], 16: [10, 17, 18, 21],
    17: [16, 18, 21], 18: [3, 11, 22], 19: [22], 20: [5, 6, 8, 12],
    21: [2, 4, 10, 16], 22: [18, 19],
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def main():
    manifest_path = SOURCE / 'manifest.json'
    ledger_path = ROOT / 'docs/full-analysis/path-ledger.json'
    partitions_path = ROOT / 'docs/full-analysis/partitions.json'
    manifest = load(manifest_path)
    assert manifest['revision'] == REVISION
    inventory = {r['path']: r for r in manifest['inventory']}
    ledger = {r['path']: (i, r) for i, r in enumerate(load(ledger_path)) if r['source'] == 'baldrix'}
    partitions = [p for p in load(partitions_path) if p['partition'] in PARTITIONS]
    assert len(partitions) == 2
    for partition in partitions:
        assert partition['scope_sha256'] == PARTITIONS[partition['partition']]
    by_path = {r['path']: p for p in partitions for r in p['paths']}
    targets = sorted(by_path)
    assert len(targets) == 22
    assert targets == sorted(p for p in inventory if p.startswith('skills/flutter/'))
    review = (ROOT / REVIEW).read_text(encoding='utf-8')
    anchors = set(re.findall(r'<a id="([^"]+)"></a>', review))
    assert anchors == {f'i{i:02d}' for i in range(1, 23)} | {'scope', 'trace', 'zeus', 'unknowns'}
    assert '삼성' in review and '사람 인수' in review and '??' not in review

    def identity(path):
        raw = (PINNED / path).read_bytes()
        raw.decode('utf-8')
        entry = inventory[path]
        index, old = ledger[path]
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        digest = sha(raw)
        assert blob == entry['object'] and len(raw) == entry['bytes']
        if entry.get('snapshot_sha256') is not None:
            assert digest == entry['snapshot_sha256']
        assert old['revision'] == REVISION and old['git_blob'] == blob
        assert old['pinned_sha256'] == digest and old['bytes'] == len(raw)
        return {
            'source': 'baldrix', 'path': path, 'revision': REVISION,
            'git_blob': blob, 'pinned_sha256': digest, 'bytes': len(raw),
            'lines': len(raw.splitlines()),
            'manifest_snapshot_sha256_present': entry.get('snapshot_sha256') is not None,
            'manifest_snapshot_sha256': entry.get('snapshot_sha256'),
            'hash_verification': 'raw_git_blob_and_bytes_vs_manifest; independent_sha256_vs_path_ledger_and_manifest_if_present',
            'path_ledger_row_index': index, 'path_ledger_row_at_recording': old,
            'path_ledger_row_sha256': sha(canonical(old)),
            'path_ledger_disposition_at_recording': old['disposition'],
            'previous_review_reuse': None, 'tests_executed': [], 'execution_verified': False,
            'transitive_closure_complete': False, 'actual_claude_review_complete': False,
            'license_review_complete': False, 'os_runtime_verified': False,
            'model_qualification_verified': False, 'human_acceptance_verified': False,
            'adoption_status': 'not_approved_not_incorporated',
        }

    files = []
    for i, path in enumerate(targets, 1):
        row = identity(path)
        assert row['path_ledger_disposition_at_recording'] == 'unreviewed'
        anchor = f'i{i:02d}'
        section = review.split(f'<a id="{anchor}"></a>', 1)[1].split('<a id=', 1)[0].strip()
        assert Path(path).name in section.split('\n')[0]
        row.update({
            'partition': by_path[path]['partition'], 'scope_sha256': by_path[path]['scope_sha256'],
            'disposition': 'semantically_reviewed', 'read_extent': 'full_body',
            'line_ranges': [[1, row['lines']]], 'read_basis': 'fresh_displayed_full_primary_body_current_review',
            'read_receipt': RECEIPTS[i], 'review_ref': f'{REVIEW}#{anchor}',
            'semantic_summary': section.split('\n\n', 1)[1],
            'caller_or_dependency_trace': [targets[n - 1] for n in PRIMARY_EDGES[i]],
            'primary_comparison_refs': [f'{REVIEW}#i{n:02d}' for n in PRIMARY_EDGES[i]],
            'test_kind': 'inert_markdown_guidance_examples_not_executed_tests',
            'denominator_basis': '22 fresh full primary bodies; code examples and checklist statements are not execution receipts.',
        })
        if i == 5:
            row['read_receipt_ranges'] = [
                {'receipt': '8f1949', 'line_ranges': [[1, 100]]},
                {'receipt': 'd37852', 'line_ranges': [[101, 270]]},
            ]
            row['truncation_handling'] = 'Original combined output omitted part of lines 1-100; fresh supplementary display closed that interval.'
        files.append(row)
    assert sum(row['bytes'] for row in files) == 208437
    supports = []
    for path, (ranges, primary_refs, receipt) in SUPPORTS.items():
        row = identity(path)
        assert all(1 <= a <= b <= row['lines'] for a, b in ranges), path
        raw_lines = (PINNED / path).read_bytes().splitlines(keepends=True)
        row.update({
            'support_id': f'S{len(supports) + 1:02d}', 'disposition': 'supporting_read_only',
            'read_extent': 'full_body_supporting' if ranges == [[1, row['lines']]] else 'explicit_ranges_only',
            'read_basis': 'fresh_displayed_supporting_intervals_current_review',
            'line_ranges': ranges, 'read_receipt': receipt,
            'counted_as_primary_body': False, 'review_ref': f'{REVIEW}#trace',
            'review_refs': [f'{REVIEW}#trace'] + [f'{REVIEW}#i{i:02d}' for i in primary_refs],
            'range_sha256': [{'start': a, 'end': b, 'sha256': sha(b''.join(raw_lines[a - 1:b]))} for a, b in ranges],
            'purpose': 'Direct matching, config, workflow, rendering or unit-oracle contract; static only.',
        })
        supports.append(row)
        for i in primary_refs:
            files[i - 1]['caller_or_dependency_trace'].append(path)
    assert len(supports) == 22
    save('files.json', files)
    save('supporting-evidence.json', supports)
    native = [p for p in inventory if p.endswith(('.dart', '.kt', '.gradle', '.swift'))]
    assert all(p.startswith('scripts/synthetic-fleet/') for p in native)
    unavailable = [
        'Original outpos-client-agent-review lib tree and original outpos-client-wating application, not acquired by this pinned manifest.',
        'study-outpos-agent-docs requirements, study/21-easypos.md and live Claude project memories; not opened.',
        'Original paygate plugin, VAN adapter/config/ValidationHelper, OTA Kotlin implementation, original pubspec/lock and host CI.',
        'Vendor PDF/interface/sample, actual Flutter/Dart/package versions and external documentation; not fetched.',
        'Actual native test suites, real device/OS/CI observations, user acceptance and license/adoption qualification.',
        'All unlisted transitive caller/config/helper/test/skill content, including testgen CLI and complete runner/gate closure.',
    ]
    save('remaining.json', {
        'primary_body_remaining': [], 'supporting_trace_remaining': unavailable,
        'availability_boundary': 'Unacquired within pinned manifest; not a claim that named external local folders do not exist.',
        'inventory_native_paths': native,
        'live_state_accessed': False, 'live_credential_stores_accessed': False,
        'inert_document_hardcoded_key_encountered': True,
        'sensitive_literal_republished': False,
        'source_execution_count': 0, 'source_import_count': 0, 'source_collection_count': 0,
        'probe_count': 0, 'network_count': 0, 'model_count': 0, 'install_count': 0,
        'actual_claude_calls': 0, 'blocked_probe_retried_or_bypassed': False,
        'full_analysis_complete': False, 'transitive_closure_complete': False,
        'actual_claude_review_complete': False, 'license_review_complete': False,
        'os_runtime_verified': False, 'model_qualification_verified': False,
        'human_acceptance_verified': False, 'adoption_approved': False,
        'review_ref': f'{REVIEW}#unknowns',
    })
    refs = [r['review_ref'] for r in files]
    refs += [ref for r in files for ref in r['primary_comparison_refs']]
    refs += [ref for r in supports for ref in r['review_refs']]
    for ref in refs:
        name, anchor = ref.split('#')
        assert f'<a id="{anchor}"></a>' in (ROOT / name).read_text(encoding='utf-8')
    verification = {
        'primary_count': 22, 'primary_bytes': 208437,
        'primary_lines': sum(r['lines'] for r in files), 'fresh_primary_count': 22,
        'prior_full_body_reused_count': 0, 'supporting_rows': 22,
        'fresh_supporting_rows': 22, 'prior_supporting_reused_rows': 0,
        'supporting_full_body_rows': sum(r['read_extent'] == 'full_body_supporting' for r in supports),
        'supporting_read_lines': sum(b - a + 1 for r in supports for a, b in r['line_ranges']),
        'review_refs_checked': len(refs), 'raw_git_blob_bytes_sha_ranges_verified': True,
        'tests_read_in_part_not_run': [p for p in SUPPORTS if p.startswith('scripts/tests/')],
        'upstream_tests_run': False, 'full_analysis_complete': False, 'adoption_approved': False,
        'inventory_discovery_receipts': ['558312', 'ccd65e', 'fb40b1'],
        'search_only_not_body_receipts': ['d6a958', 'c210c8', '87184f', '1bcc22', 'c5cd2a', 'bd8750'],
        'failed_body_display': 'd83680 cp949 UnicodeEncodeError; zero body credited; retried inert display with Python UTF-8 mode 7e70d9.',
        'search_missing_paths': ['config/', 'scripts/engine/context_loader.py', 'scripts/tests/test_pipeline_overlay.py', 'scripts/cli/testgen.py'],
        'search_missing_paths_scope': 'Attempted pinned paths absent; existing implementation found via bounded targeted searches where recorded, not whole-repository absence claims.',
        'missing_manifest_snapshot_sha256_paths': [r['path'] for r in files + supports if not r['manifest_snapshot_sha256_present']],
    }
    save('verification.json', verification)
    artifacts = ['review.md', 'record_review.py', 'files.json', 'supporting-evidence.json', 'remaining.json', 'verification.json']
    artifact_hashes = {p: sha((OUT / p).read_bytes()) for p in artifacts}
    save('checkpoint.json', {
        'partitions': list(PARTITIONS), 'partition_scopes': PARTITIONS,
        'revision': REVISION, 'zeus_head_at_start': START_HEAD,
        'status': 'bounded_static_review_complete', 'primary_files': 22, 'primary_bytes': 208437,
        'fresh_primary_files': 22, 'prior_full_body_reused_files': 0, 'supporting_rows': 22,
        'input_sha256_at_recording': {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in [manifest_path, ledger_path, partitions_path]},
        'artifact_sha256': artifact_hashes, 'scope_complete': True,
        'subsystem_complete': False, 'full_analysis_complete': False, 'transitive_closure_complete': False,
        'actual_claude_review_complete': False, 'license_review_complete': False,
        'model_qualification_verified': False, 'os_runtime_verified': False,
        'human_acceptance_verified': False, 'adoption_approved': False,
        'source_execution_count': 0, 'source_import_count': 0, 'source_collection_count': 0,
        'probe_count': 0, 'network_count': 0, 'model_count': 0, 'install_count': 0,
        'source_runtime_shared_coverage_modified': False, 'commit_or_push_performed': False,
        'review_ref': f'{REVIEW}#scope',
    })
    artifacts.append('checkpoint.json')
    for name in artifacts:
        raw = (OUT / name).read_bytes()
        body = raw.decode('utf-8')
        assert not raw.startswith(b'\xef\xbb\xbf') and b'\r' not in raw, name
        assert raw.endswith(b'\n') and not raw.endswith(b'\n\n'), name
        assert all(line == line.rstrip() for line in body.splitlines()), name
        if name.endswith('.py'):
            ast.parse(body)
        elif name.endswith('.json'):
            json.loads(body)
    save('record-validation.json', {
        'status': 'own_static_metadata_checks_passed', 'primary_count': 22, 'primary_bytes': 208437,
        'supporting_rows': 22, 'raw_blob_size_sha256_ranges_refs_prior_rows_verified': True,
        'utf8_no_bom_no_cr_exactly_one_trailing_lf_no_trailing_whitespace': True,
        'upstream_execution_count': 0, 'upstream_test_count': 0,
        'artifact_sha256': {name: sha((OUT / name).read_bytes()) for name in artifacts},
        'review_ref': f'{REVIEW}#scope',
    })
    print(json.dumps(verification, ensure_ascii=True))
    for name in ['review.md', 'files.json', 'supporting-evidence.json', 'checkpoint.json', 'record-validation.json']:
        print(name + ' sha256=' + sha((OUT / name).read_bytes()))


if __name__ == '__main__':
    main()
