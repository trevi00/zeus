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
PARTITION = 'baldrix:scripts/tests:003'
SCOPE = '02f6d31998fe908f65b4fb8992ace15129545762b961a3e5de605b05b08491a5'
REVIEW = 'docs/full-analysis/baldrix-tests-003/review.md'
START_HEAD = '2458b8fd73616d4cd28d5e7a2f9a0457c72b9fc4'

# These are displayed, actually read source intervals, not discovered search hits.
SUPPORT = {
    'scripts/lib/calibration/proposer.py': ([[127, 184], [186, 295]], ['i01']),
    'scripts/lib/critic_policy.py': ([[97, 227]], ['i01', 'i21', 'i23']),
    'scripts/cli/critic_policy_override.py': ([[1, 87]], ['i23']),
    'scripts/handlers/pre_tool/critic_policy_advisor.py': ([[35, 110]], ['i22']),
    'scripts/cli/calibration_review.py': ([[32, 79], [129, 164]], ['i01']),
    'scripts/lib/canary.py': ([[62, 113], [115, 242]], ['i02']),
    'scripts/lib/changelog_io.py': ([[18, 114]], ['i03']),
    'scripts/cron/check_brain_push.py': ([[56, 122]], ['i04', 'i25']),
    'scripts/validators/claim_verifier.py': ([[127, 210]], ['i07']),
    'scripts/lib/handoff_drift.py': ([[149, 183]], ['i08']),
    'scripts/validators/code_blind_proceed.py': ([[38, 65]], ['i08']),
    'scripts/lib/completion_gate.py': ([[49, 109], [147, 252]], ['i13']),
    'scripts/engine/orchestrator.py': ([[557, 619]], ['i13']),
    'scripts/lib/breakers/composite.py': ([[226, 339]], ['i14']),
    'scripts/lib/resident_store.py': ([[140, 192]], ['i18']),
    'scripts/lib/coverage_gate.py': ([[32, 79]], ['i15']),
    'scripts/handlers/pre_tool/dart_strict_type_advisor.py': (
        [[20, 145], [156, 186]], ['i29'],
    ),
    'scripts/validators/ci.py': ([[1, 197]], ['i06']),
    'scripts/validators/codegen.py': ([[1, 217]], ['i09']),
    'scripts/validators/collab.py': ([[1, 68]], ['i10']),
    'scripts/validators/contract.py': ([[1, 244]], ['i17']),
    'scripts/validators/convention.py': ([[1, 97]], ['i19']),
    'scripts/lib/cooldown.py': ([[1, 44]], ['i20']),
    'scripts/validators/commit_layer_adjacency.py': (
        [[35, 118], [151, 200]], ['i12'],
    ),
    'scripts/validators/context_coupling.py': ([[50, 155]], ['i16']),
    'scripts/lib/criticism_dedup.py': ([[130, 243]], ['i24']),
    'scripts/lib/validators/cross_ref.py': ([[78, 181]], ['i26']),
    'scripts/cli/meeting_ingest.py': ([[47, 57]], ['i15']),
    'scripts/lib/ground_or_drop.py': ([[29, 87]], ['i15']),
    'scripts/lib/cucumber_scaffolder.py': ([[84, 151]], ['i27']),
    'scripts/lib/dart_scaffolder.py': ([[30, 109]], ['i28']),
    'scripts/lib/testgen.py': ([[199, 241]], ['i28']),
    'scripts/cli/greenfield_spec_emit.py': ([[62, 152]], ['i28']),
    'scripts/cron/run_ledger_compaction.py': ([[62, 148]], ['i25']),
    'scripts/cron/run_pollution_cleanup.py': ([[48, 122]], ['i25']),
    'scripts/lib/paths.py': (
        [[12, 34], [100, 139], [159, 239]], ['i03', 'i13', 'i22'],
    ),
    'scripts/tests/run_units.py': (
        [[39, 46], [75, 99], [130, 166], [330, 387]], ['trace', 'i05', 'i29'],
    ),
    'scripts/lib/axis_scores_log.py': ([[97, 126]], ['i13']),
    'scripts/handlers/stop/autopilot_continue.py': ([[635, 685]], ['i13']),
    'scripts/handlers/post_tool/agent_outcome_audit.py': ([[426, 450]], ['i22']),
    'scripts/cli/resident.py': ([[212, 225], [270, 275]], ['i18']),
    'settings.json': ([[179, 211]], ['i22', 'i29']),
    'agents/harness-git-master.md': ([[70, 103]], ['i05']),
    'commands/harness-debate.md': ([[42, 62], [118, 145]], ['i11']),
    'scripts/example-fleet/fleet.absent.yaml': ([[1, 10]], ['i15']),
    'scripts/example-fleet/seams.absent.spec.yaml': ([[1, 13]], ['i15']),
    'skills/_pipeline/overlays/dart.overlay.yaml': ([[1, 27]], ['i28']),
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
    assert len(anchors) == 33
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
            'tests_executed': [],
        }

    files = []
    for i, target in enumerate(partition['paths'], 1):
        path = target['path']
        row = identity(path)
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
            'os_runtime_verified': False, 'human_acceptance_verified': False,
        })
        files.append(row)
    assert len(files) == 29
    assert sum(r['bytes'] for r in files) == partition['bytes'] == 191922
    assert len({r['path'] for r in files}) == 29
    supports = []
    for i, (path, (ranges, refs)) in enumerate(SUPPORT.items(), 1):
        row = identity(path)
        for a, b in ranges:
            assert 1 <= a <= b <= row['lines'], (path, a, b)
        for ref in refs:
            assert ref in anchors
        row.update({
            'support_id': f'S{i:02d}', 'disposition': 'supporting_read_only',
            'line_ranges': ranges, 'read_extent': 'explicit_ranges_only',
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
            'All unlisted source intervals and transitive dependencies remain unreviewed here.',
            'run_all and conftest full semantics and isolation are independent root scope.',
            'Connected fleet fixture service bodies, extractor and bundle assembler full trace.',
            'Completion inline self-check body and axis reader full schema/provenance chain.',
            'Seven other command bodies, scheduler, brain remote effects, atomic helper implementation.',
            'Actual Claude independent review, licenses, Windows/Linux/WSL execution.',
            'Actual service/device/replay, alpha/live deployment and human acceptance.',
            'Zeus adoption and implementation equivalence.',
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
        'primary_files': 29, 'primary_bytes': 191922,
        'primary_lines': verification['primary_lines'],
        'supporting_rows': len(supports), 'previous_review_reuse': None,
        'input_sha256_at_recording': inputs, 'artifact_sha256': artifacts,
        'scope_complete': True, 'subsystem_complete': False,
        'full_analysis_complete': False, 'adoption_approved': False,
        'actual_claude_review_complete': False, 'license_review_complete': False,
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
