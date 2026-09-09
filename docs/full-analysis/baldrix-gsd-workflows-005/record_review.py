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
START_HEAD = '31d5091407566d4988980485246ed031784203b2'
REVIEW = 'docs/full-analysis/baldrix-gsd-workflows-005/review.md'
SCOPES = {
    'baldrix:get-shit-done/workflows:005': '0793c364d3a1426312c4800715fdd964ba23bbb7eeab42fd57b36649b4e184eb',
}
PRIMARY_RECEIPTS = [
    'b18c4d', 'b18c4d', '72f1d3', ['75ddc3', '44d13f'],
    ['44d13f', '7bcf14'], '4b255b', ['f0ece8', '36c571'],
]
# Every interval was freshly displayed and read; no prior semantic/body reuse.
SUPPORT = {
    'get-shit-done/bin/lib/uat.cjs': ([[1, 282]], ['trace', 'i06', 'i07'], ['f8e2a1', '1c6d19']),
    'get-shit-done/bin/lib/verify.cjs': ([[283, 399]], ['trace', 'i06'], ['f8e2a1']),
    'get-shit-done/bin/lib/init.cjs': ([[25, 48], [173, 226], [538, 695]], ['trace', 'i01', 'i02', 'i05', 'i07'], ['f8e2a1', '1c6d19', '77d214', '370e00', '7bcf14']),
    'get-shit-done/bin/lib/commands.cjs': ([[250, 348]], ['trace', 'i01', 'i05', 'i07'], ['f8e2a1']),
    'agents/kha-ui-checker.md': ([[153, 281]], ['trace', 'i01'], ['1c6d19']),
    'agents/kha-nyquist-auditor.md': ([[1, 171]], ['trace', 'i05'], ['1c6d19']),
    'agents/kha-ui-auditor.md': ([[330, 370], [447, 500]], ['trace', 'i02'], ['1c6d19']),
    'get-shit-done/bin/lib/core.cjs': ([[648, 686], [1303, 1342]], ['trace', 'zeus', 'i01', 'i07'], ['77d214']),
    'get-shit-done/bin/lib/config.cjs': ([[125, 150], [357, 405]], ['trace', 'i01', 'i05', 'i07'], ['77d214', 'db5f41']),
    'get-shit-done/workflows/execute-phase.md': ([[954, 1116]], ['trace', 'i06', 'i07'], ['77d214']),
    'get-shit-done/templates/VALIDATION.md': ([[1, 76]], ['trace', 'i05'], ['77d214']),
    'get-shit-done/templates/UAT.md': ([[1, 102]], ['trace', 'i07'], ['77d214']),
    'get-shit-done/bin/lib/phase.cjs': ([[652, 719], [899, 924]], ['trace', 'i06'], ['db5f41']),
    'get-shit-done/bin/gsd-tools.cjs': ([[450, 466], [540, 560], [725, 741], [785, 805]], ['trace', 'i05', 'i06', 'i07'], ['db5f41']),
    'get-shit-done/templates/phase-prompt.md': ([[603, 610]], ['trace', 'i06'], ['db5f41']),
    'agents/kha-ui-researcher.md': ([[75, 84], [99, 222], [314, 335]], ['trace', 'i01'], ['370e00']),
    'agents/kha-verifier.md': ([[494, 543]], ['trace', 'i06'], ['370e00']),
    'get-shit-done/templates/UI-SPEC.md': ([[1, 95]], ['trace', 'i01'], ['370e00']),
    'get-shit-done/templates/verification-report.md': ([[1, 37], [74, 114]], ['trace', 'i06', 'i07'], ['370e00', '7bcf14']),
    'skills/kha-spec-ui-phase/SKILL.md': ([[1, 57]], ['trace', 'i01'], ['db5f41']),
    'skills/kha-review-ui/SKILL.md': ([[1, 55]], ['trace', 'i02'], ['db5f41']),
    'skills/kha-revert-work/SKILL.md': ([[1, 61]], ['trace', 'i03'], ['db5f41']),
    'skills/kha-self-update/SKILL.md': ([[1, 59]], ['trace', 'i04'], ['db5f41']),
    'skills/kha-validate-nyquist-phase/SKILL.md': ([[1, 58]], ['trace', 'i05'], ['db5f41']),
    'skills/kha-verify-uat/SKILL.md': ([[1, 61]], ['trace', 'i07'], ['db5f41']),
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
    assert anchors == {'scope', 'trace', 'zeus', 'unknowns'} | {f'i{i:02d}' for i in range(1, 8)}
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
                'denominator_basis': '7 workflow bodies read fresh. Workflow declarations, helper static branches, text PASS and summary presence are not executed tests, actual human acceptance or deployment evidence.',
                'test_kind': 'workflow_declaration_not_executed_test_suite', 'tests_read_in_part': [],
                'external_sources_verified': 0, 'external_claims_verified': 0,
                'adoption_status': 'not_approved_not_incorporated',
                'execution_verified': False, 'transitive_closure_complete': False,
                'actual_claude_review_complete': False, 'license_review_complete': False,
                'model_qualification_verified': False, 'os_runtime_verified': False,
                'human_acceptance_verified': False,
            })
            files.append(row)
    assert len(files) == len({row['path'] for row in files}) == len(PRIMARY_RECEIPTS) == 7
    assert sum(row['bytes'] for row in files) == sum(p['bytes'] for p in partitions) == 83538
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
            'purpose': 'Fresh bounded direct skill entry, workflow/agent consumer, helper/router/config/parser/template and state authority trace; no original execution.',
        })
        supports.append(row)
    assert len(supports) == 25
    write_json('files.json', files)
    write_json('supporting-evidence.json', supports)
    write_json('remaining.json', {
        'primary_body_remaining': [],
        'supporting_trace_remaining': [
            'Unlisted intervals, complete transitive consumer/config/test/hook closure, update installer and phase-manifest writer.',
            'Actual UAT/human-heading parser, empty-denominator helper, init path, update-target, cleanup and workflow-state observations.',
            'Tool authorization, runtime hook registration, all config consumers and atomic crash/concurrency behavior.',
            'Independent user approval identity, artifact revision, expiration and PG transition consumer.',
            'Actual Windows/Linux/WSL/browser/service execution, alpha/live deploy/rollback and real human acceptance.',
            'Samsung phone/tablet Device Farm SDK/MCP/live/replay are deferred.',
            'External sources, versions, present applicability, attribution, license and full research closure.',
            'Human response identity, ambiguous response classification, interrupted batching, spec/scenario completeness and actual state consumers.',
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
        'full_read_gap_repairs': {},
        'search_only_not_body': ['0f54bb', 'b13c12', '7609ae', '2a6b55', '361b06'],
        'failed_read_not_counted': '7a6314 failed at line 2 with cp949 output encoding; complete successful fresh reads are f8e2a1 and 1c6d19.',
        'search_limits': 'No direct test bodies found in named identifier test/spec searches. Broad uat hits and truncated search output do not establish test absence. bin/install.js and update hook bodies were not obtained. No original tests ran.',
        'metadata_format_reuse': 'Previous recorder source format reused only; no prior source body or semantic finding reused.',

    }
    write_json('verification.json', verification)
    for name in ('review.md', 'record_review.py', 'build_recorder.py', 'files.json', 'supporting-evidence.json', 'remaining.json', 'verification.json'):
        raw = (OUT / name).read_bytes()
        raw.decode('utf-8')
        assert raw.endswith(b'\n') and not raw.endswith(b'\n\n') and b'\r' not in raw, name
    inputs = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p.read_bytes()) for p in (manifest_path, partition_path, ledger_path)}
    artifacts = {name: sha((OUT / name).read_bytes()) for name in (
        'review.md', 'files.json', 'supporting-evidence.json', 'remaining.json', 'verification.json', 'record_review.py', 'build_recorder.py',
    )}
    write_json('checkpoint.json', {
        'partitions': list(SCOPES), 'partition_scopes': SCOPES, 'revision': REVISION,
        'zeus_head_at_start': START_HEAD, 'status': 'bounded_static_review_complete',
        'primary_files': 7, 'primary_bytes': 83538, 'primary_lines': verification['primary_lines'],
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
