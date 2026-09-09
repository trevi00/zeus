"""Record metadata for displayed static reads; never import reviewed source."""
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
PARTITION = 'baldrix:agents:003'
SCOPE = 'c181b712b1a775cbee3a81518412422d4723aa58a75da6fa347d9556798fddcb'
REVIEW = 'docs/full-analysis/baldrix-agents-003/review.md'
START_HEAD = '73f2c8848c0002df8dac3cc00f59566abfaa4134'

# Only complete displayed intervals are counted. No prior evidence reuse.
SUPPORT = {
    'get-shit-done/workflows/secure-phase.md': ([[1, 164]], ['trace', 'i05']),
    'get-shit-done/workflows/ui-phase.md': ([[98, 265]], ['trace', 'i07', 'i08']),
    'get-shit-done/workflows/ui-review.md': ([[1, 130]], ['trace', 'i06']),
    'scripts/cli/onboard_stack.py': ([[1, 391]], ['trace', 'i12']),
    'get-shit-done/bin/lib/verify.cjs': ([[108, 219], [283, 402]], ['trace', 'i01', 'i10']),
    'get-shit-done/bin/lib/frontmatter.cjs': ([[305, 313], [348, 381]], ['trace', 'i01']),
    'get-shit-done/workflows/new-project.md': ([[630, 835], [1000, 1140]], ['trace', 'i02', 'i03', 'i04']),
    'get-shit-done/workflows/execute-phase.md': ([[950, 1060]], ['trace', 'i10']),
    'get-shit-done/workflows/profile-user.md': ([[130, 225], [240, 335]], ['trace', 'i09']),
    'scripts/tests/test_onboard_stack.py': ([[1, 165]], ['trace', 'i12']),
    'get-shit-done/bin/lib/profile-pipeline.cjs': ([[400, 536]], ['trace', 'i09']),
    'get-shit-done/bin/lib/model-profiles.cjs': ([[1, 70]], ['trace', 'i01', 'i02', 'i03', 'i04', 'i06', 'i07', 'i08', 'i10']),
    'scripts/handlers/post_tool/agent_outcome_audit.py': ([[1, 128], [260, 320]], ['trace', 'i12']),
    'scripts/cli/agents_normalize.py': ([[1, 80]], ['trace']),
    'scripts/tests/test_agents_normalize.py': ([[1, 130]], ['trace']),
    'get-shit-done/workflows/plan-phase.md': ([[580, 705]], ['trace', 'i01']),
    'settings.json': ([[241, 277]], ['trace']),
    'scripts/lib/validators/structural.py': ([[175, 292]], ['trace', 'i12']),
}
READ_RECEIPTS = {
    'primary': [
        ['168e1f', '1bfc67', '4a6947'], 'a66171', '66f383', '6b8ab9',
        '66f383', '5c2be7', 'a4513d', '05f3e7', 'a9833a',
        ['37f963', '9aa740'], 'a9833a', 'a9833a',
    ],
    'supporting': ['1296fe', '775bd6', 'a865e1', 'c6c132', '5d8298', '16bfe1', 'b6dfab'],
    'note': '7d873b encoding-failed read was repeated in a865e1. Search-only output and nonexistent path candidate agent_output_schema.py are not body coverage. All supporting rows are fresh reads; contiguous displayed intervals are merged.',
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    partition = next(row for row in read_json(partition_path) if row['partition'] == PARTITION)
    assert partition['scope_sha256'] == SCOPE
    ledger = {row['path']: (i, row) for i, row in enumerate(read_json(ledger_path)) if row['source'] == 'baldrix'}
    review = (ROOT / REVIEW).read_text(encoding='utf-8')
    anchors = set(re.findall(r'<a id="([^"]+)"></a>', review))
    assert anchors == {'scope', 'trace', 'zeus', 'unknowns'} | {f'i{i:02d}' for i in range(1, 13)}
    assert '\uc2e4\uc81c \uc0ac\ub78c' in review and '\uc0bc\uc131' in review and '??' not in review

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
    for i, target in enumerate(partition['paths'], 1):
        path = target['path']
        row = identity(path)
        assert row['path_ledger_disposition_at_recording'] == 'unreviewed', path
        anchor = f'i{i:02d}'
        section = review.split(f'<a id="{anchor}"></a>', 1)[1].split('<a id=', 1)[0]
        assert Path(path).name in section
        row.update({
            'partition': PARTITION, 'disposition': 'semantically_reviewed',
            'read_extent': 'full_body', 'line_ranges': [[1, row['lines']]],
            'read_basis': 'fresh_displayed_full_primary_body_current_review',
            'read_receipt': READ_RECEIPTS['primary'][i - 1],
            'review_ref': f'{REVIEW}#{anchor}',
            'semantic_summary': section.strip().split('\n\n', 1)[1].strip(),
            'finding_sections': [anchor, 'trace', 'zeus', 'unknowns'],
            'caller_or_dependency_trace': [name for name, (_, refs) in SUPPORT.items() if anchor in refs],
            'denominator_basis': 'Twelve agent definitions read in full. Workflow declarations, schema checks and 15 support test functions are not executed tests, qualified model behavior or human acceptance.',
            'external_sources_verified': 0, 'external_claims_verified': 0,
            'test_kind': 'agent_contract_not_test_suite',
            'tests_read_in_part': ['scripts/tests/test_onboard_stack.py'] if i == 12 else [],
            'adoption_status': 'not_approved_not_incorporated',
            'execution_verified': False, 'transitive_closure_complete': False,
            'actual_claude_review_complete': False, 'license_review_complete': False,
            'model_qualification_verified': False, 'os_runtime_verified': False,
            'human_acceptance_verified': False,
        })
        files.append(row)
    assert len(files) == len({row['path'] for row in files}) == 12
    assert sum(row['bytes'] for row in files) == partition['bytes'] == 190117
    assert sum(row['lines'] for row in files) == 5474
    supports = []
    for i, (path, (ranges, refs)) in enumerate(SUPPORT.items(), 1):
        row = identity(path)
        for a, b in ranges:
            assert 1 <= a <= b <= row['lines'], (path, a, b)
        assert set(refs) <= anchors
        row.update({
            'support_id': f'S{i:02d}', 'disposition': 'supporting_read_only',
            'line_ranges': ranges,
            'read_extent': 'full_body_supporting' if ranges == [[1, row['lines']]] else 'explicit_ranges_only',
            'read_basis': 'fresh_displayed_supporting_intervals_current_review',
            'review_ref': f'{REVIEW}#{refs[0]}', 'review_refs': [f'{REVIEW}#{ref}' for ref in refs],
            'counted_as_primary_body': False,
            'range_sha256': [
                {'start': a, 'end': b, 'sha256': sha(b''.join((PINNED / path).read_bytes().splitlines(keepends=True)[a - 1:b]))}
                for a, b in ranges
            ],
            'purpose': 'Actual prose consumer, matching, validator, registry, test and runner trace; no execution.',
        })
        supports.append(row)
    write_json('files.json', files)
    write_json('supporting-evidence.json', supports)
    pending = {
        'primary_body_remaining': [],
        'supporting_trace_remaining': [
            'Unlisted intervals and complete transitive consumer/configuration/test closure.',
            'Pre-tool authorization, sandbox, actual Agent/Task mapping and live hook registration.',
            'External source snapshots, versions, attribution, present applicability and license.',
            'Model resolver precedence and Astra/Sol/Terra qualification against real scenarios.',
            'Independent approval identity, artifact revision, expiration and PG transition consumer.',
            'Actual Windows/Linux/WSL/browser/service execution and real human task acceptance.',
            'Samsung phone/tablet and Device Farm SDK/MCP/live/replay remain deferred.',
            'Git helper, deployment receipts, alpha/live promotion and rollback runtime.',
            'Session collector privacy scope, retention and artifact writer full closure; no collection done.',
            'Actual Claude independent review, Zeus implementation adoption and equivalence.',
        ],
        'upstream_executions': 0, 'upstream_imports': 0, 'probes': 0, 'network_calls': 0,
        'installs': 0, 'model_calls': 0, 'live_state_accessed': False, 'credentials_accessed': False,
        'blocked_probe_retried': False, 'full_analysis_complete': False,
        'transitive_closure_complete': False, 'adopted': False, 'review_ref': f'{REVIEW}#unknowns',
    }
    write_json('remaining.json', pending)
    refs = [row['review_ref'] for row in files] + [ref for row in supports for ref in row['review_refs']]
    for ref in refs:
        path, anchor = ref.split('#')
        assert (ROOT / path).is_file()
        assert f'<a id="{anchor}"></a>' in (ROOT / path).read_text(encoding='utf-8')
    verification = {
        'primary_count': 12, 'primary_bytes': 190117, 'primary_lines': 5474,
        'supporting_rows': len(supports), 'prior_reuse_rows': 0, 'review_refs_checked': len(refs),
        'raw_blob_size_sha256_verified': True, 'range_bounds_verified': True,
        'utf8_decoding_verified': True, 'korean_sentinel_verified': True,
        'own_python_lf': b'\r' not in Path(__file__).read_bytes(),
        'missing_manifest_snapshot_sha256': sum(not row['manifest_snapshot_sha256_present'] for row in files + supports),
        'upstream_tests_run': False, 'external_claims_verified': 0, 'read_receipts': READ_RECEIPTS,
    }
    write_json('verification.json', verification)
    inputs = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p.read_bytes()) for p in (manifest_path, partition_path, ledger_path)}
    artifacts = {name: sha((OUT / name).read_bytes()) for name in (
        'review.md', 'files.json', 'supporting-evidence.json', 'remaining.json', 'verification.json', 'record_review.py',
    )}
    write_json('checkpoint.json', {
        'partition': PARTITION, 'scope_sha256': SCOPE, 'revision': REVISION,
        'zeus_head_at_start': START_HEAD, 'status': 'bounded_static_review_complete',
        'primary_files': 12, 'primary_bytes': 190117, 'primary_lines': 5474,
        'supporting_rows': len(supports), 'previous_review_reuse': None,
        'input_sha256_at_recording': inputs, 'artifact_sha256': artifacts,
        'scope_complete': True, 'subsystem_complete': False, 'full_analysis_complete': False,
        'adoption_approved': False, 'actual_claude_review_complete': False, 'license_review_complete': False,
        'model_qualification_verified': False, 'os_runtime_verified': False, 'human_acceptance_verified': False,
        'source_execution_count': 0, 'source_import_count': 0, 'probe_count': 0, 'network_count': 0,
        'model_count': 0, 'install_count': 0, 'live_state_accessed': False, 'credentials_accessed': False,
        'blocked_probe_retried_or_bypassed': False, 'source_runtime_shared_coverage_modified': False,
        'commit_or_push_performed': False, 'review_ref': f'{REVIEW}#scope',
    })
    print(json.dumps(verification, ensure_ascii=True))
    print('review_sha256=' + artifacts['review.md'])
    print('checkpoint_sha256=' + sha((OUT / 'checkpoint.json').read_bytes()))


if __name__ == '__main__':
    main()
