"""Record completed static reads; do not execute or import reviewed source."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
PINNED = SOURCE / 'pinned'
REVISION = 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2'
START_HEAD = '5acaeced22de71ae3eb8584643e00557762745c0'
REVIEW = 'docs/full-analysis/baldrix-gsd-templates-001/review.md'
SCOPES = {
    'baldrix:get-shit-done/templates:001': '13d2fb78c5c165cb62bba7643505dbd05ce21470e236a388cd08ca8c8d0f1fc5',
    'baldrix:get-shit-done/templates:002': '27bbbcb4ae7b0252a6d8449f1d419d413a843c5cca22043511d0408c6a8d9966',
}
PRIMARY_RECEIPTS = [
    '535a41', '535a41', '535a41', '535a41',
    '56c19b', '56c19b', '56c19b', ['56c19b', '92d49f'], '56c19b',
    '92d49f', '92d49f', '116e72', '116e72', '116e72', '116e72',
    'a3fbb6', 'a3fbb6', 'a3fbb6', 'a3fbb6', 'a3fbb6', 'a3fbb6', 'a3fbb6', 'a3fbb6',
    ['6f2e52', '91118f'], '6f2e52', '6f2e52', '6f2e52',
    '91118f', '91118f', '91118f', '91118f', '91118f',
    'ad40be', 'ad40be', 'ad40be', 'ad40be',
    'fdf5d1', 'fdf5d1', 'fdf5d1', 'fdf5d1', 'fdf5d1', 'f519f7', 'f519f7',
]
# Intervals were displayed and read this turn; no prior semantic reuse.
SUPPORT = {
    'get-shit-done/bin/lib/template.cjs': ([[1, 222]], ['trace', 'i24', 'i37', 'i38', 'i39', 'i40', 'i43'], ['24763e']),
    'get-shit-done/bin/lib/phase.cjs': ([[652, 812]], ['trace', 'i03', 'i27', 'i35', 'i43'], ['24763e']),
    'get-shit-done/bin/lib/uat.cjs': ([[1, 282]], ['trace', 'i03', 'i43'], ['24763e', '74a3d1']),
    'get-shit-done/bin/lib/core.cjs': ([[211, 368]], ['trace', 'i14'], ['24763e', '74a3d1']),
    'get-shit-done/workflows/verify-work.md': ([[1, 28], [85, 115], [250, 445]], ['trace', 'i03', 'i43'], ['74a3d1']),
    'get-shit-done/workflows/execute-plan.md': ([[374, 435]], ['trace', 'i24', 'i40', 'i42'], ['74a3d1']),
    'get-shit-done/bin/lib/commands.cjs': ([[405, 468]], ['trace', 'i37', 'i38', 'i39', 'i40'], ['74a3d1', '05e343']),
    'get-shit-done/bin/lib/state.cjs': ([[363, 407]], ['trace', 'i35', 'i36'], ['74a3d1']),
    'get-shit-done/bin/lib/profile-output.cjs': ([[526, 636], [730, 790], [911, 1027]], ['trace', 'i06', 'i19', 'i41'], ['c0e215']),
    'get-shit-done/bin/lib/frontmatter.cjs': ([[305, 309], [358, 381]], ['trace', 'i24', 'i37', 'i38', 'i39', 'i40'], ['c0e215']),
    'get-shit-done/bin/lib/verify.cjs': ([[1, 170]], ['trace', 'i24', 'i40'], ['c0e215']),
    'get-shit-done/bin/lib/config.cjs': ([[1, 42], [180, 270], [330, 405]], ['trace', 'i14'], ['c0e215', '05e343', 'config-final-read']),
    'get-shit-done/workflows/complete-milestone.md': ([[1, 90], [443, 501]], ['trace', 'i22', 'i23', 'i34'], ['3defe9']),
    'get-shit-done/workflows/plan-phase.md': ([[346, 387], [580, 640]], ['trace', 'i05', 'i24', 'i25', 'i33'], ['3defe9', '05e343']),
    'get-shit-done/workflows/validate-phase.md': ([[94, 147]], ['trace', 'i05', 'i33'], ['3defe9']),
    'get-shit-done/workflows/secure-phase.md': ([[20, 42], [62, 131]], ['trace', 'i02'], ['3defe9']),
    'get-shit-done/workflows/discuss-phase.md': ([[848, 874], [1017, 1071]], ['trace', 'i15', 'i21'], ['3defe9']),
    'get-shit-done/workflows/resume-project.md': ([[60, 103]], ['trace', 'i16'], ['3defe9']),
    'get-shit-done/workflows/pause-work.md': ([[95, 143]], ['trace', 'i16'], ['3defe9']),
    'agents/kha-codebase-mapper.md': ([[1, 43], [140, 192]], ['trace', 'i07', 'i08', 'i09', 'i10', 'i11', 'i12', 'i13'], ['682a8c']),
    'agents/kha-phase-researcher.md': ([[383, 415], [477, 485], [599, 623]], ['trace', 'i05', 'i33'], ['682a8c']),
    'agents/kha-debugger.md': ([[1090, 1142]], ['trace', 'i01', 'i18'], ['682a8c']),
    'agents/kha-planner.md': ([[995, 1012]], ['trace', 'i34'], ['682a8c']),
    'get-shit-done/workflows/new-project.md': ([[300, 351], [650, 680], [710, 720], [750, 760], [790, 825], [945, 992]], ['trace', 'i26', 'i28', 'i29', 'i30', 'i31', 'i32'], ['682a8c']),
    'agents/kha-ui-researcher.md': ([[209, 222]], ['trace', 'i04'], ['682a8c']),
    'agents/kha-ui-checker.md': ([[205, 232]], ['trace', 'i04'], ['682a8c']),
    'get-shit-done/workflows/discovery-phase.md': ([[1, 34], [100, 119]], ['trace', 'i20'], ['682a8c']),
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(name: str, value) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def main() -> None:
    manifest_path = SOURCE / 'manifest.json'
    partition_path = ROOT / 'docs/full-analysis/partitions.json'
    ledger_path = ROOT / 'docs/full-analysis/path-ledger.json'
    manifest = read_json(manifest_path)
    assert manifest['revision'] == REVISION
    inventory = {row['path']: row for row in manifest['inventory']}
    partitions = [row for row in read_json(partition_path) if row['partition'] in SCOPES]
    assert {p['partition'] for p in partitions} == set(SCOPES)
    partitions.sort(key=lambda row: row['partition'])
    for partition in partitions:
        assert partition['scope_sha256'] == SCOPES[partition['partition']]
    ledger = {row['path']: (i, row) for i, row in enumerate(read_json(ledger_path)) if row['source'] == 'baldrix'}
    review = (ROOT / REVIEW).read_text(encoding='utf-8')
    anchors = set(re.findall(r'<a id="([^"]+)"></a>', review))
    assert anchors == {'scope', 'trace', 'zeus', 'unknowns'} | {f'i{i:02d}' for i in range(1, 44)}
    assert '실제 사람' in review and '삼성' in review and '??' not in review

    def identity(path: str) -> dict:
        raw = (PINNED / path).read_bytes()
        raw.decode('utf-8')
        entry = inventory[path]
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
        digest = sha(raw)
        assert blob == entry['object'] and len(raw) == entry['bytes'], path
        if entry.get('snapshot_sha256') is not None:
            assert digest == entry['snapshot_sha256'], path
        index, old = ledger[path]
        assert old['revision'] == REVISION and old['git_blob'] == blob, path
        assert old['bytes'] == len(raw) and old['pinned_sha256'] == digest, path
        return {
            'source': 'baldrix', 'path': path, 'revision': REVISION,
            'pinned_sha256': digest, 'git_blob': blob, 'bytes': len(raw), 'lines': len(raw.splitlines()),
            'manifest_snapshot_sha256_present': entry.get('snapshot_sha256') is not None,
            'manifest_snapshot_sha256': entry.get('snapshot_sha256'),
            'hash_verification': 'raw_git_blob_size_and_separate_sha256_compared_to_manifest_when_present_and_path_ledger',
            'path_ledger_row_index': index, 'path_ledger_disposition_at_recording': old['disposition'],
            'path_ledger_row_at_recording': old,
            'path_ledger_row_sha256': sha(json.dumps(old, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')),
            'upstream_disposition_unchanged': entry['disposition'], 'previous_review_reuse': None,
            'tests_executed': [],
        }

    files = []
    for partition in partitions:
        for target in partition['paths']:
            i = len(files) + 1
            path = target['path']
            row = identity(path)
            assert row['path_ledger_disposition_at_recording'] == 'unreviewed', path
            anchor = f'i{i:02d}'
            section = review.split(f'<a id="{anchor}"></a>', 1)[1].split('<a id=', 1)[0]
            assert Path(path).name in section
            row.update({
                'partition': partition['partition'], 'disposition': 'semantically_reviewed',
                'read_extent': 'full_body', 'line_ranges': [[1, row['lines']]],
                'read_basis': 'fresh_displayed_full_primary_body_current_review',
                'read_receipt': PRIMARY_RECEIPTS[i - 1], 'review_ref': f'{REVIEW}#{anchor}',
                'semantic_summary': section.strip().split('\n\n', 1)[1].strip(),
                'finding_sections': [anchor, 'trace', 'zeus', 'unknowns'],
                'caller_or_dependency_trace': [name for name, (_, refs, _) in SUPPORT.items() if anchor in refs],
                'denominator_basis': '43 template bodies read fresh. Template placeholders, commands, declared PASS and summary presence are not executed tests, actual human acceptance or deployment evidence.',
                'test_kind': 'template_contract_not_test_suite', 'tests_read_in_part': [],
                'external_sources_verified': 0, 'external_claims_verified': 0,
                'adoption_status': 'not_approved_not_incorporated',
                'execution_verified': False, 'transitive_closure_complete': False,
                'actual_claude_review_complete': False, 'license_review_complete': False,
                'model_qualification_verified': False, 'os_runtime_verified': False,
                'human_acceptance_verified': False,
            })
            files.append(row)
    assert len(files) == len({row['path'] for row in files}) == len(PRIMARY_RECEIPTS) == 43
    assert sum(row['bytes'] for row in files) == sum(p['bytes'] for p in partitions) == 226301
    partition_counts = {}
    for partition in partitions:
        rows = [row for row in files if row['partition'] == partition['partition']]
        assert len(rows) == len(partition['paths'])
        assert sum(row['bytes'] for row in rows) == partition['bytes']
        partition_counts[partition['partition']] = {'files': len(rows), 'bytes': sum(row['bytes'] for row in rows)}
    supports = []
    for i, (path, (ranges, refs, receipts)) in enumerate(SUPPORT.items(), 1):
        row = identity(path)
        for a, b in ranges:
            assert 1 <= a <= b <= row['lines'], (path, a, b)
        assert set(refs) <= anchors
        row.update({
            'support_id': f'S{i:02d}', 'disposition': 'supporting_read_only',
            'line_ranges': ranges,
            'read_extent': 'full_body_supporting' if ranges == [[1, row['lines']]] else 'explicit_ranges_only',
            'read_basis': 'fresh_displayed_supporting_intervals_current_review',
            'read_receipt': receipts,
            'review_ref': f'{REVIEW}#{refs[0]}', 'review_refs': [f'{REVIEW}#{ref}' for ref in refs],
            'counted_as_primary_body': False,
            'range_sha256': [
                {'start': a, 'end': b, 'sha256': sha(b''.join((PINNED / path).read_bytes().splitlines(keepends=True)[a - 1:b]))}
                for a, b in ranges
            ],
            'purpose': 'Fresh bounded direct template producer, workflow consumer, parser, schema and state authority trace; no original execution.',
        })
        supports.append(row)
    assert len(supports) == 27
    write_json('files.json', files)
    write_json('supporting-evidence.json', supports)
    write_json('remaining.json', {
        'primary_body_remaining': [],
        'supporting_trace_remaining': [
            'Unlisted intervals, complete transitive consumer/config/test closure and actual template loader paths for copilot/debug-subagent/planner-subagent prompt files.',
            'Actual CJS UAT/human-heading parsing, template generation/select/validation/summary round trips and regression reproduction.',
            'Tool authorization, runtime hook registration, all config consumers and atomic crash/concurrency behavior.',
            'Independent user approval identity, artifact revision, expiration and PG transition consumer.',
            'Actual Windows/Linux/WSL/browser/service execution, alpha/live deploy/rollback and real human acceptance.',
            'Samsung phone/tablet Device Farm SDK/MCP/live/replay are deferred.',
            'External sources, versions, present applicability, attribution, license and full research closure.',
            'Session collector consent, privacy, retention and profile writer full closure; no collection performed.',
            'Astra/Sol/Terra qualifications, actual Claude independent review, Zeus implementation adoption and equivalence.',
        ],
        'upstream_executions': 0, 'upstream_imports': 0, 'collections': 0, 'probes': 0,
        'network_calls': 0, 'installs': 0, 'model_calls': 0, 'actual_claude_calls': 0,
        'live_state_accessed': False, 'credentials_accessed': False, 'blocked_probe_retried': False,
        'full_analysis_complete': False, 'transitive_closure_complete': False, 'adopted': False,
        'actual_claude_review_complete': False, 'license_review_complete': False,
        'model_qualification_verified': False, 'os_runtime_verified': False, 'human_acceptance_verified': False,
        'review_ref': f'{REVIEW}#unknowns',
    })
    refs = [row['review_ref'] for row in files] + [ref for row in supports for ref in row['review_refs']]
    for ref in refs:
        path, anchor = ref.split('#')
        assert (ROOT / path).is_file()
        assert f'<a id="{anchor}"></a>' in (ROOT / path).read_text(encoding='utf-8')
    verification = {
        'primary_count': len(files), 'primary_bytes': sum(row['bytes'] for row in files),
        'primary_lines': sum(row['lines'] for row in files), 'partition_counts': partition_counts,
        'supporting_rows': len(supports), 'supporting_read_lines': sum(b - a + 1 for ranges, _, _ in SUPPORT.values() for a, b in ranges),
        'prior_reuse_rows': 0, 'review_refs_checked': len(refs),
        'raw_blob_size_sha256_verified': True, 'range_bounds_verified': True,
        'utf8_decoding_verified': True, 'korean_sentinel_verified': True,
        'missing_manifest_snapshot_sha256_paths': [row['path'] for row in files + supports if not row['manifest_snapshot_sha256_present']],
        'upstream_tests_run': False, 'external_claims_verified': 0,
        'full_read_gap_repairs': {
            'get-shit-done/templates/codebase/concerns.md': 'Truncated 56c19b was supplemented with fresh lines 1-144 in 92d49f; displayed 142-310 completed the body.',
            'get-shit-done/templates/phase-prompt.md': 'Truncated 6f2e52 was supplemented with fresh lines 520-610 in 91118f; displayed 1-529 completed the body.',
        },
        'search_only_not_body': ['1f21fc', '381ed0', '398fe7', 'c8aadf', 'fdd299', 'c17857', '551d83'],
        'search_limits': 'Windows literal glob error and truncated file listing are not negative evidence of total test absence. Direct bounded test identifier search had no target test matches. No test bodies executed.',
        'config_final_read_receipt': 'Fresh config.cjs numbered lines 330-405 displayed after 05e343; functions output returned only output text, so no chunk id was retained.',
    }
    write_json('verification.json', verification)
    for name in ('review.md', 'record_review.py', 'files.json', 'supporting-evidence.json', 'remaining.json', 'verification.json'):
        raw = (OUT / name).read_bytes()
        raw.decode('utf-8')
        assert raw.endswith(b'\n') and not raw.endswith(b'\n\n') and b'\r' not in raw, name
    inputs = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p.read_bytes()) for p in (manifest_path, partition_path, ledger_path)}
    artifacts = {name: sha((OUT / name).read_bytes()) for name in (
        'review.md', 'files.json', 'supporting-evidence.json', 'remaining.json', 'verification.json', 'record_review.py',
    )}
    write_json('checkpoint.json', {
        'partitions': list(SCOPES), 'partition_scopes': SCOPES, 'revision': REVISION,
        'zeus_head_at_start': START_HEAD, 'status': 'bounded_static_review_complete',
        'primary_files': 43, 'primary_bytes': 226301, 'primary_lines': verification['primary_lines'],
        'partition_counts': partition_counts, 'supporting_rows': len(supports), 'previous_review_reuse': None,
        'input_sha256_at_recording': inputs, 'artifact_sha256': artifacts,
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
    print('review_sha256=' + artifacts['review.md'])
    print('checkpoint_sha256=' + sha((OUT / 'checkpoint.json').read_bytes()))


if __name__ == '__main__':
    main()
