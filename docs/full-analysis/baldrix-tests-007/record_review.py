"""Record bounded static reads. Never import or execute the reviewed source."""
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
PARTITION = 'baldrix:scripts/tests:007'
SCOPE = '8efc3be2a990a1a6f88519655c8e234e6472eae5e7fce22d06910dcbc81b4d1b'
REVIEW = 'docs/full-analysis/baldrix-tests-007/review.md'
START_HEAD = '18c91d6aaebf0ee2105daa822b1027cb73dcab44'

# Fresh displayed semantic reads; search hits/AST locations are excluded.
SUPPORT = {
    'scripts/engine/jury_advisory.py': ([[35, 171]], ['i01']),
    'scripts/cli/kha_alias.py': ([[174, 272]], ['i02']),
    'scripts/cli/kha_migrate.py': ([[145, 291]], ['i03']),
    'scripts/cli/kha_normalize.py': ([[296, 340]], ['i04']),
    'scripts/lib/l2_facts.py': (
        [[126, 228], [286, 359], [380, 442], [474, 501], [504, 562]], ['i05', 'i06'],
    ),
    'scripts/lib/l2_promoter.py': ([[65, 146], [149, 163], [166, 364]], ['i06', 'i07']),
    'scripts/lib/ledger_compaction.py': ([[1, 80]], ['i08']),
    'scripts/lib/telemetry_log.py': ([[13, 57]], ['i09', 'i17']),
    'scripts/validators/logical.py': ([[65, 139]], ['i10']),
    'scripts/lib/meta_rules.py': ([[274, 364]], ['i12']),
    'scripts/lib/milestone_gate.py': (
        [[128, 157], [193, 225], [249, 406]], ['i13', 'i16', 'i19', 'i21', 'i22'],
    ),
    'scripts/cli/milestone_close.py': ([[45, 121]], ['i14']),
    'scripts/cli/milestone_verdict.py': (
        [[85, 114], [151, 227]], ['i14', 'i19', 'i21', 'i22'],
    ),
    'scripts/lib/milestone_spine.py': (
        [[38, 58], [110, 152], [169, 191], [212, 355]],
        ['i14', 'i15', 'i17', 'i19', 'i20', 'i21', 'i22', 'trace'],
    ),
    'scripts/lib/milestone_liveness.py': (
        [[49, 69], [105, 241]], ['i14', 'i17'],
    ),
    'scripts/cli/milestone_feedback.py': ([[74, 181]], ['i15']),
    'scripts/lib/axis_scores_log.py': ([[57, 166]], ['i16', 'i21', 'i22', 'trace']),
    'scripts/cli/milestone_step.py': (
        [[103, 133], [220, 627]], ['i13', 'i18', 'i19', 'i21', 'i22'],
    ),
    'scripts/cli/milestone_rewind.py': ([[72, 107], [118, 267]], ['i19', 'i20']),
    'scripts/lib/milestone_checklist.py': (
        [[187, 190], [292, 330], [394, 450]], ['i13', 'i21', 'i22'],
    ),
    'scripts/lib/milestone_materials.py': (
        [[182, 263], [266, 288], [308, 344], [383, 434], [437, 480]], ['i18', 'i21'],
    ),
    'scripts/lib/paths.py': ([[12, 19], [79, 141]], ['i05', 'i09', 'i14', 'i16', 'trace']),
    'scripts/cron/run_l2_promotion.py': ([[110, 185]], ['i06']),
    'scripts/cron/run_ledger_compaction.py': ([[70, 139]], ['i08']),
    'scripts/lib/mirror_drift.py': ([[45, 89], [113, 225], [256, 284]], ['i23']),
    'scripts/lib/mirror_extractors/base.py': ([[70, 190]], ['i23']),
    'scripts/lib/mirror_extractors/__init__.py': ([[22, 77]], ['i23']),
    'scripts/lib/mirror_extractors/rust.py': ([[24, 49]], ['i23']),
    'scripts/lib/mirror_extractors/pathglob.py': ([[26, 37]], ['i23']),
    'scripts/handlers/session/init.py': ([[392, 403]], ['i23']),
    'scripts/tests/run_units.py': (
        [[39, 194], [217, 311], [314, 403]], ['trace', 'i09', 'i10', 'i11', 'i23'],
    ),
    'scripts/tests/run_all.py': ([[166, 188], [207, 258]], ['trace', 'i10']),
    'commands/harness-milestone.md': (
        [[27, 99], [117, 148]], ['i15', 'i19', 'i21', 'i22', 'trace'],
    ),
    'commands/harness-debate.md': ([[57, 66]], ['i01', 'trace']),
    'get-shit-done/bin/lib/__tests__/merge-back.test.cjs': ([[1, 245]], ['i11']),
    'scripts/tests/conftest.py': ([[1, 83]], ['i14', 'i16', 'i17', 'i20', 'trace']),
    'scripts/validators/__init__.py': ([[34, 92]], ['i10', 'trace']),
    'scripts/lib/event_store.py': ([[30, 117]], ['i17', 'i20']),
    'get-shit-done/bin/gsd-tools.cjs': ([[474, 481]], ['i11']),
    'get-shit-done/bin/lib/merge-back.cjs': ([[205, 267]], ['i11']),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(name: str, value) -> None:
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8', newline='\n',
    )


def main() -> None:
    manifest_path = SOURCE / 'manifest.json'
    partition_path = ROOT / 'docs/full-analysis/partitions.json'
    ledger_path = ROOT / 'docs/full-analysis/path-ledger.json'
    manifest = read_json(manifest_path)
    assert manifest['revision'] == REVISION
    inventory = {r['path']: r for r in manifest['inventory']}
    partition = next(p for p in read_json(partition_path) if p['partition'] == PARTITION)
    assert partition['scope_sha256'] == SCOPE
    ledger = read_json(ledger_path)
    path_ledger = {
        row['path']: (index, row)
        for index, row in enumerate(ledger)
        if row['source'] == 'baldrix'
    }
    review = (ROOT / REVIEW).read_text(encoding='utf-8')
    anchors = set(re.findall(r'<a id="([^"]+)"></a>', review))
    assert len(anchors) == 27
    assert '실제 사람' in review and '삼성' in review and review.count('??') == 0

    def identity(path: str) -> dict:
        raw = (PINNED / path).read_bytes()
        raw.decode('utf-8')
        entry = inventory[path]
        git_blob = hashlib.sha1(
            b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw,
        ).hexdigest()
        digest = sha(raw)
        assert git_blob == entry['object'], path
        assert len(raw) == entry['bytes'], path
        if entry.get('snapshot_sha256') is not None:
            assert digest == entry['snapshot_sha256'], path
        index, ledger_row = path_ledger[path]
        assert ledger_row['revision'] == REVISION, path
        assert ledger_row['git_blob'] == git_blob, path
        assert ledger_row['bytes'] == len(raw), path
        assert ledger_row['pinned_sha256'] == digest, path
        return {
            'source': 'baldrix', 'path': path, 'revision': REVISION,
            'pinned_sha256': digest, 'git_blob': git_blob, 'bytes': len(raw),
            'lines': len(raw.splitlines()),
            'manifest_snapshot_sha256_present': entry.get('snapshot_sha256') is not None,
            'manifest_snapshot_sha256': entry.get('snapshot_sha256'),
            'hash_verification': (
                'raw_git_blob_size_snapshot_sha256_and_path_ledger'
                if entry.get('snapshot_sha256') is not None
                else 'raw_git_blob_size_and_separate_sha256_path_ledger_manifest_sha_absent'
            ),
            'path_ledger_row_index': index,
            'path_ledger_disposition_at_recording': ledger_row['disposition'],
            'upstream_disposition_unchanged': entry['disposition'],
            'previous_review_reuse': None,
            'path_ledger_row_at_recording': ledger_row,
            'path_ledger_row_sha256': sha(json.dumps(ledger_row, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')),
            'tests_executed': [],
        }

    files = []
    for i, target in enumerate(partition['paths'], 1):
        path = target['path']
        row = identity(path)
        assert row['path_ledger_disposition_at_recording'] == 'unreviewed', path
        anchor = f'i{i:02d}'
        assert anchor in anchors
        section = review.split(f'<a id="{anchor}"></a>', 1)[1].split('<a id=', 1)[0]
        assert Path(path).name in section
        summary = section.strip().split('\n\n', 1)[1].strip()
        tree = ast.parse((PINNED / path).read_text(encoding='utf-8'))
        defs = [
            {'name': n.name, 'line': n.lineno, 'end_line': n.end_lineno}
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith('test_')
        ]
        count_claim = re.match(r'([0-9]+)개', summary)
        if count_claim:
            assert int(count_claim[1]) == len(defs), path
        row.update({
            'partition': PARTITION, 'disposition': 'semantically_reviewed',
            'read_extent': 'full_body', 'line_ranges': [[1, row['lines']]],
            'read_basis': 'displayed_and_read_current_review',
            'review_ref': f'{REVIEW}#{anchor}', 'semantic_summary': summary,
            'finding_sections': [anchor, 'trace', 'zeus', 'unknowns'],
            'caller_or_dependency_trace': [
                name for name, (_, refs) in SUPPORT.items() if anchor in refs
            ],
            'declared_test_functions': defs,
            'declared_test_function_count': len(defs),
            'denominator_basis': 'Static definitions; main lists and conditional checks described in review; not execution count.',
            'test_kind': 'synthetic_fixture_or_static_contract_or_temporary_git_as_detailed_in_review',
            'tests_read_in_part': [],
            'adoption_status': 'not_approved_not_incorporated',
            'execution_verified': False, 'transitive_closure_complete': False,
            'actual_claude_review_complete': False, 'license_review_complete': False,
            'model_qualification_verified': False,
            'os_runtime_verified': False, 'human_acceptance_verified': False,
        })
        files.append(row)
    assert len(files) == 23
    assert sum(r['bytes'] for r in files) == partition['bytes'] == 199800
    assert len({r['path'] for r in files}) == 23
    supports = []
    for i, (path, (ranges, refs)) in enumerate(SUPPORT.items(), 1):
        row = identity(path)
        for a, b in ranges:
            assert 1 <= a <= b <= row['lines'], (path, a, b)
        for ref in refs:
            assert ref in anchors
        row.update({
            'support_id': f'S{i:02d}', 'disposition': 'supporting_read_only',
            'line_ranges': ranges,
            'read_extent': ('full_body_supporting' if ranges == [[1, row['lines']]] else 'explicit_ranges_only'),
            'read_basis': 'displayed_and_read_current_review',
            'review_ref': f'{REVIEW}#{refs[0]}',
            'review_refs': [f'{REVIEW}#{ref}' for ref in refs],
            'counted_as_primary_body': False,
            'purpose': 'Direct SUT, configuration, fixture or consumer trace for cited per-file review.',
        })
        supports.append(row)
    write_json('files.json', files)
    write_json('supporting-evidence.json', supports)
    pending = {
        'primary_body_remaining': [],
        'supporting_trace_remaining': [
            'Unlisted intervals and complete transitive consumer closure are not read here.',
            'Node mergeOneWorktree/helpers and remaining node:test scenarios 246-444.',
            'Milestone self-check full bodies, full L1/cache/atomic/token/cron scheduling.',
            'Provider and evaluator qualification, real prompt dispatch and convergence.',
            'Notification delivery, concurrency, interrupted writes and rollback effects.',
            'Multi-phase progress, approval carry, latest checklist denominator, duplicate L2 edges and dirty mirror baseline require separate verification.',
            'Actual Claude independent review, licenses, Windows/Linux/WSL execution.',
            'Actual service/device/replay, alpha/live deployment and human acceptance.',
            'Zeus PG/source implementation adoption and equivalence.',
        ],
        'upstream_executions': 0, 'upstream_imports': 0, 'probes': 0,
        'network_calls': 0, 'installs': 0, 'model_calls': 0,
        'live_state_accessed': False, 'credentials_accessed': False,
        'blocked_probe_retried': False, 'full_analysis_complete': False,
        'transitive_closure_complete': False, 'adopted': False,
        'review_ref': f'{REVIEW}#unknowns',
    }
    write_json('remaining.json', pending)
    refs = [r['review_ref'] for r in files]
    refs += [ref for r in supports for ref in r['review_refs']]
    for ref in refs:
        path, anchor = ref.split('#')
        assert (ROOT / path).is_file()
        assert f'<a id="{anchor}"></a>' in (ROOT / path).read_text(encoding='utf-8')
    verification = {
        'primary_count': len(files), 'primary_bytes': sum(r['bytes'] for r in files),
        'primary_lines': sum(r['lines'] for r in files),
        'supporting_rows': len(supports), 'prior_reuse_rows': 0,
        'review_refs_checked': len(refs), 'raw_blob_size_sha256_verified': True,
        'range_bounds_verified': True, 'utf8_decoding_verified': True,
        'korean_sentinel_verified': True, 'own_python_lf': b'\r' not in Path(__file__).read_bytes(),
        'missing_manifest_snapshot_sha256': sum(
            not r['manifest_snapshot_sha256_present'] for r in files + supports
        ),
        'declared_function_counts': {Path(r['path']).name: r['declared_test_function_count'] for r in files},
        'upstream_tests_run': False,
    }
    write_json('verification.json', verification)
    inputs = {
        str(p.relative_to(ROOT)).replace('\\', '/'): sha(p.read_bytes())
        for p in (manifest_path, partition_path, ledger_path)
    }
    artifacts = {
        name: sha((OUT / name).read_bytes()) for name in (
            'review.md', 'files.json', 'supporting-evidence.json',
            'remaining.json', 'verification.json', 'record_review.py',
        )
    }
    write_json('checkpoint.json', {
        'partition': PARTITION, 'scope_sha256': SCOPE, 'revision': REVISION,
        'zeus_head_at_start': START_HEAD, 'status': 'bounded_static_review_complete',
        'primary_files': 23, 'primary_bytes': 199800,
        'primary_lines': verification['primary_lines'],
        'supporting_rows': len(supports), 'previous_review_reuse': None,
        'input_sha256_at_recording': inputs, 'artifact_sha256': artifacts,
        'scope_complete': True, 'subsystem_complete': False,
        'full_analysis_complete': False, 'adoption_approved': False,
        'actual_claude_review_complete': False, 'license_review_complete': False,
        'model_qualification_verified': False,
        'os_runtime_verified': False, 'human_acceptance_verified': False,
        'source_execution_count': 0, 'source_import_count': 0, 'probe_count': 0,
        'network_count': 0, 'model_count': 0, 'install_count': 0,
        'live_state_accessed': False, 'credentials_accessed': False,
        'blocked_probe_retried_or_bypassed': False,
        'source_runtime_shared_coverage_modified': False,
        'commit_or_push_performed': False,
        'review_ref': f'{REVIEW}#scope',
    })
    print(json.dumps(verification, ensure_ascii=True))
    print('review_sha256=' + artifacts['review.md'])
    print('checkpoint_sha256=' + sha((OUT / 'checkpoint.json').read_bytes()))


if __name__ == '__main__':
    main()
