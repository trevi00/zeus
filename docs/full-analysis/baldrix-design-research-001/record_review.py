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
PARTITION = 'baldrix:reference/design-research:001'
SCOPE = '108b627caf57123c5728307b7d0a8d1ff38ff6d606a287508f18055fdce588ad'
REVIEW = 'docs/full-analysis/baldrix-design-research-001/review.md'
START_HEAD = '852564f34e738997c19cf4af917450572d029e6c'

# Only complete displayed intervals are counted. No prior evidence reuse.
SUPPORT = {
    'agents/harness-designer.md': ([[1, 102]], ['trace', 'i03', 'i05']),
    'agents/harness-design-critic.md': ([[1, 63]], ['trace', 'i05']),
    'skills/_common/design-craft.md': ([[1, 65], [170, 174]], ['i03', 'trace']),
    'skills/_common/design-systems-tokens.md': ([[1, 78]], ['i01', 'i05', 'trace']),
    'skills/_common/design-review.md': ([[1, 79]], ['trace', 'i04', 'i05']),
    'skills/_common/design-critic-gate.md': ([[1, 84]], ['trace', 'i05', 'i07']),
    'skills/_common/design-foundations.md': ([[1, 102]], ['i05', 'i06', 'trace']),
    'skills/_common/ux-heuristics-research.md': ([[1, 98]], ['i04', 'trace']),
    'skills/_common/app-mobile-design.md': ([[1, 84]], ['i02', 'trace']),
    'skills/_common/ux-writing.md': ([[1, 98]], ['i07', 'trace']),
    'skills/_common/motion-interaction.md': ([[1, 89]], ['i01', 'i02', 'trace']),
    'scripts/validators/design_slop_a11y.py': ([[1, 218]], ['trace', 'i01', 'i04']),
    'scripts/tests/test_design_slop_a11y.py': ([[1, 102]], ['trace']),
    'scripts/validators/__init__.py': ([[1, 123]], ['trace']),
    'skills/typescript/react/ui-design.md': ([[1, 54], [177, 195]], ['trace', 'i01']),
    'scripts/handlers/prompt/skill_match.py': ([[256, 308], [335, 418]], ['trace']),
    'scripts/lib/graduation.py': ([[1, 100]], ['trace']),
    'agents/kha-doc-writer.md': ([[550, 575]], ['trace']),
    'scripts/tests/run_units.py': ([[39, 100], [156, 186], [298, 403]], ['trace']),
}
READ_RECEIPTS = {
    'primary': ['5f9736', '9c747b', '88a378', '63b657', '9daed3', '64df56', 'f91a90'],
    'supporting': ['2b4be1', 'fbc8b0', '0c976a', '0c9633', 'cff2f4', '238f79', '2333aa'],
    'note': '2b4be1 was truncated: design-craft is recorded only from fresh bounded rereads; tokens was reread in full. Search output is not body coverage.',
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
    assert anchors == {'scope', 'trace', 'zeus', 'unknowns'} | {f'i{i:02d}' for i in range(1, 8)}
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
            'denominator_basis': 'Seven historical dossiers read. Citation entries, rules and recommendations are not validated claims, executed tests or human acceptance.',
            'external_sources_verified': 0, 'external_claims_verified': 0,
            'test_kind': 'historical_design_research_not_test_suite', 'tests_read_in_part': [],
            'adoption_status': 'not_approved_not_incorporated',
            'execution_verified': False, 'transitive_closure_complete': False,
            'actual_claude_review_complete': False, 'license_review_complete': False,
            'model_qualification_verified': False, 'os_runtime_verified': False,
            'human_acceptance_verified': False,
        })
        files.append(row)
    assert len(files) == len({row['path'] for row in files}) == 7
    assert sum(row['bytes'] for row in files) == partition['bytes'] == 160202
    assert sum(row['lines'] for row in files) == 1462
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
            'purpose': 'Actual prose consumer, matching, validator, registry, test and runner trace; no execution.',
        })
        supports.append(row)
    write_json('files.json', files)
    write_json('supporting-evidence.json', supports)
    pending = {
        'primary_body_remaining': [],
        'supporting_trace_remaining': [
            'Unlisted intervals and complete transitive consumer/configuration/test closure.',
            'Claim-by-claim external source snapshot, attribution, scope, current applicability and license.',
            'Automatic dossier-to-skill generation/change propagation and per-claim revision binding.',
            'Actual skill injection, installed module resolution, graduation state and full graduation implementation.',
            'Actual Storybook stories/config/tests and token compiler/lockfile/component versions.',
            'Actual Windows/Linux/WSL/browser/AT/service execution and real human task acceptance.',
            'Samsung phone/tablet model/OS and Device Farm SDK/MCP/live/replay remain deferred.',
            'Approval identity/artifact binding/expiration, PG transition consumer and alpha/live deployment.',
            'Actual Claude independent review and Astra/Sol/Terra qualification.',
            'Zeus implementation adoption and equivalence.',
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
        'primary_count': 7, 'primary_bytes': 160202, 'primary_lines': 1462,
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
        'primary_files': 7, 'primary_bytes': 160202, 'primary_lines': 1462,
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
