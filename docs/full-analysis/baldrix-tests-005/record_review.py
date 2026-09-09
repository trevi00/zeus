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
PARTITION = 'baldrix:scripts/tests:005'
SCOPE = '4fb3aa75d211c23ff7c41c2fcb7596f903aef8ffd33141a1ab86015f48ac98fa'
REVIEW = 'docs/full-analysis/baldrix-tests-005/review.md'
START_HEAD = 'a98f29e3cdc913445b38fcc10f9fd1eb8942ae7f'

# Fresh displayed semantic reads; search hits/AST locations are excluded.
SUPPORT = {
    'scripts/lib/evaluator_dispatcher.py': (
        [[141, 196], [231, 269], [347, 384], [387, 470], [473, 587],
         [590, 637], [1421, 1462], [2280, 2311]], ['i01', 'i02'],
    ),
    'scripts/lib/event_store.py': ([[1, 117]], ['i03']),
    'scripts/lib/observers/evidence_fab.py': ([[1, 194]], ['i04']),
    'scripts/validators/exit_contract_coverage.py': ([[1, 158]], ['i06']),
    'scripts/cli/ontology_query.py': ([[1, 100]], ['i05']),
    'scripts/cli/seam_scan.py': ([[1, 141]], ['i05', 'i11']),
    'scripts/cli/fleet_atlas.py': ([[1, 115]], ['i11']),
    'scripts/lib/file_matchers.py': ([[1, 137]], ['i10']),
    'scripts/lib/frontmatter_norm.py': ([[1, 60]], ['i13']),
    'scripts/lib/frontmatter.py': ([[1, 62]], ['i13']),
    'scripts/validators/falsy_zero.py': ([[215, 305]], ['i09']),
    'scripts/validators/flow.py': ([[1, 112]], ['i08', 'i12']),
    'scripts/lib/graduation.py': (
        [[40, 146], [199, 286], [289, 467]], ['i18', 'i19', 'i20'],
    ),
    'scripts/cli/graduate_validator.py': ([[42, 179]], ['i18', 'i20']),
    'scripts/lib/graduation_audit.py': ([[38, 130]], ['i20']),
    'scripts/lib/git_flow_override.py': ([[1, 103]], ['i15', 'i16']),
    'scripts/validators/git_flow.py': ([[64, 173]], ['i15']),
    'scripts/lib/golden_signals.py': ([[45, 123], [220, 367]], ['i17']),
    'scripts/lib/resident_store.py': ([[27, 37], [80, 183]], ['i17']),
    'scripts/cli/resident.py': ([[136, 224]], ['i17']),
    'scripts/cli/agents.py': ([[63, 90], [136, 155]], ['i17']),
    'scripts/cli/signals.py': ([[55, 96]], ['i17']),
    'scripts/cli/greenfield_spec_emit.py': ([[25, 182]], ['i21']),
    'scripts/validators/spec_roundtrip.py': ([[1, 135]], ['i21']),
    'scripts/handlers/pre_tool/guard.py': ([[143, 293]], ['i16', 'i22']),
    'scripts/engine/external_jury.py': ([[1, 272]], ['i07']),
    'scripts/lib/extractors/__init__.py': ([[1, 92]], ['i08']),
    'scripts/lib/extractors/base.py': ([[1, 94]], ['i08']),
    'scripts/tests/probe_intent_docs.py': ([[1, 59]], ['i08']),
    'scripts/cli/reverse_engineer.py': ([[62, 112], [150, 236]], ['i08']),
    'scripts/lib/testgen.py': ([[70, 104], [270, 305]], ['i21']),
    'scripts/lib/cucumber_scaffolder.py': ([[109, 150]], ['i21']),
    'skills/_pipeline/overlays/java.overlay.yaml': ([[1, 100]], ['i21']),
    'scripts/tests/run_units.py': (
        [[39, 194], [263, 301], [314, 403]], ['trace', 'i05', 'i14', 'i22'],
    ),
    'scripts/validators/__init__.py': ([[34, 123]], ['trace', 'i18', 'i19']),
    'scripts/lib/paths.py': (
        [[12, 19], [79, 141], [159, 179]], ['i01', 'i03', 'i17', 'i18', 'trace'],
    ),
    'scripts/lib/telemetry_log.py': ([[13, 57], [87, 124]], ['i03', 'i22']),
    'scripts/lib/milestone_liveness.py': ([[225, 241]], ['i17']),
    'scripts/lib/replay/constants.py': ([[1, 17]], ['i04']),
    'scripts/lib/intent_doc_floor.py': ([[1, 69]], ['i08']),
    'scripts/handlers/post_tool/reviewer.py': (
        [[38, 65], [309, 345], [580, 640]], ['i10'],
    ),
    'scripts/lib/skill_score.py': ([[210, 261]], ['i13']),
    'scripts/handlers/session/init.py': ([[350, 375]], ['i19']),
    'scripts/validators/doc_code_drift.py': ([[45, 72], [281, 304]], ['i18']),
    'scripts/validators/self_model_drift.py': ([[40, 66], [235, 255]], ['i18']),
    'scripts/lib/extractors/requirements.py': ([[1, 75]], ['i08']),
    'scripts/lib/extractors/conceptual.py': ([[1, 85]], ['i08']),
    'scripts/lib/extractors/prd.py': ([[1, 115]], ['i08']),
    'scripts/handlers/post_tool/agent_outcome_audit.py': (
        [[229, 258], [272, 312]], ['i04'],
    ),
    'scripts/engine/cli.py': ([[1, 68]], ['i03']),
    'scripts/validators/prd.py': ([[1, 98]], ['i08']),
    'scripts/lib/breakers/config.py': ([[1, 191]], ['i07']),
    'scripts/engine/dispatch_retry.py': ([[1, 70]], ['i07']),
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
    assert len(anchors) == 26
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
            'os_runtime_verified': False, 'human_acceptance_verified': False,
        })
        files.append(row)
    assert len(files) == 22
    assert sum(r['bytes'] for r in files) == partition['bytes'] == 196348
    assert len({r['path'] for r in files}) == 22
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
            'Embedded evaluator self-check middle body 1463-2279 and provider/quota implementations.',
            'All nine extractor full parser/renderer bodies, spec bundle assembler and stack execution.',
            'Composite breaker persistence/concurrency, atomic helpers and notification delivery.',
            'run_all/conftest full semantics and real fixture fleet are separate root scope.',
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
        'primary_files': 22, 'primary_bytes': 196348,
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
