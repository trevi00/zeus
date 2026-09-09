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
PARTITION = 'baldrix:scripts/tests:010'
SCOPE = '9a43ced16c69b93a7b7302ff42c2893cf4b4ae0fe3b36286c4b29791bbe14e71'
REVIEW = 'docs/full-analysis/baldrix-tests-010/review.md'
START_HEAD = '1b910a1e929fc45b9e259930f0316f516dac5e18'

# Fresh displayed semantic reads; search hits/AST locations are excluded.
SUPPORT = {'scripts/cli/resident.py': ([[82, 267], [292, 403]], ['i01', 'i02', 'i03']),
 'scripts/lib/resident_store.py': ([[104, 183], [242, 301], [370, 457]], ['i01', 'i02']),
 'scripts/cron/scheduler_driver.py': ([[75, 128], [165, 232], [269, 336], [448, 552], [554, 643]],
                                      ['i12', 'trace']),
 'scripts/tests/conftest.py': ([[1, 83]], ['trace', 'i01', 'i08', 'i18', 'i23']),
 'scripts/tests/run_units.py': ([[39, 403]], ['trace', 'i01', 'i11', 'i12', 'i13', 'i23']),
 'scripts/lib/paths.py': ([[79, 141]], ['trace', 'i01', 'i08', 'i12', 'i18', 'i23']),
 'scripts/lib/golden_signals.py': ([[77, 84], [128, 140], [220, 301]], ['i02']),
 'scripts/lib/breaker.py': ([[51, 82]], ['i01', 'i02']),
 'scripts/cli/reverse_engineer.py': ([[34, 112], [115, 203]], ['i04']),
 'scripts/lib/reverse_prd_checkpoint.py': ([[1, 99]], ['i05']),
 'scripts/lib/review_reminder.py': ([[1, 89]], ['i06']),
 'scripts/handlers/post_tool/reviewer.py': ([[309, 423], [550, 611], [679, 698]], ['i06', 'i07']),
 'scripts/cli/decisions.py': ([[61, 86]], ['i01', 'i02']),
 'scripts/lib/rewind.py': ([[53, 87], [90, 175], [188, 310], [318, 435]], ['i08']),
 'scripts/cli/sensor_anomaly.py': ([[75, 86], [119, 150], [310, 336], [380, 480]], ['i18']),
 'scripts/lib/router_eval.py': ([[48, 208]], ['i10']),
 'scripts/cli/router_eval.py': ([[46, 108]], ['i10']),
 'evals/router/baseline.json': ([[1, 12]], ['i10']),
 'scripts/lib/roles.py': ([[66, 150]], ['i09']),
 'scripts/lib/role_security.py': ([[34, 98]], ['i09', 'i20']),
 'scripts/lib/role_refactor.py': ([[90, 122]], ['i09']),
 'scripts/lib/role_dba.py': ([[41, 92]], ['i09']),
 'scripts/lib/role_orchestrator.py': ([[128, 137]], ['i09']),
 'scripts/lib/rust_scaffolder.py': ([[31, 82]], ['i11']),
 'scripts/lib/testgen.py': ([[133, 166], [270, 305]], ['i11']),
 'scripts/cli/greenfield_spec_emit.py': ([[62, 151]], ['i11']),
 'scripts/lib/stub_faker_lint.py': ([[171, 228], [266, 294]], ['i11']),
 'scripts/cli/seam_gate.py': ([[46, 114]], ['i13']),
 'scripts/cli/seam_scan.py': ([[52, 141]], ['i13', 'i14']),
 'scripts/lib/seams/parity.py': ([[1, 71]], ['i14']),
 'scripts/validators/self_model_drift.py': ([[89, 111], [147, 168], [183, 271]], ['i15']),
 'scripts/cli/selfmod.py': ([[67, 126], [172, 199], [228, 286]], ['i16']),
 'scripts/lib/settings_guard.py': ([[30, 163]], ['i20']),
 'scripts/lib/validators/semantic.py': ([[171, 292]], ['i17']),
 'scripts/lib/similarity.py': ([[1, 45]], ['i21']),
 'scripts/lib/skill_candidate_detector.py': ([[25, 209], [261, 389], [466, 584], [614, 623]],
                                             ['i23']),
 'scripts/handlers/post_tool/skill_candidate_extractor.py': ([[1, 52]], ['i23']),
 'scripts/handlers/session/init.py': ([[50, 74],
                                       [108, 136],
                                       [193, 218],
                                       [350, 386],
                                       [636, 675],
                                       [775, 839]],
                                      ['i19']),
 'scripts/validators/skeleton.py': ([[1, 120]], ['i22']),
 'scripts/lib/seams/java_socket.py': ([[47, 105]], ['i14']),
 'scripts/lib/seams/dart_socket.py': ([[95, 135]], ['i14']),
 'scripts/validators/seam_parity_drift.py': ([[29, 103]], ['i14']),
 'scripts/lib/insight_index.py': ([[161, 199], [289, 342]], ['i23']),
 'scripts/engine/debate.py': ([[65, 91]], ['i21']),
 'scripts/cron/run_role_cycle.py': ([[49, 117]], ['i01']),
 'scripts/lib/seams/proto.py': ([[1, 93]], ['i14']),
 'scripts/handlers/prompt/skill_match.py': ([[256, 308], [335, 418]], ['i10']),
 '.claude/tech-stack.yaml': ([[1, 11]], ['i10']),
 'evals/router/scenarios.jsonl': ([[1, 18]], ['i10']),
 'skills/_pipeline/overlays/rust.overlay.yaml': ([[1, 80]], ['i11']),
 'scripts/handlers/post_tool/agent_outcome_audit.py': ([[190, 238], [295, 327]], ['i17'])}


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
        methods = [
            {'class': c.name, 'name': n.name, 'line': n.lineno, 'end_line': n.end_lineno}
            for c in tree.body if isinstance(c, ast.ClassDef)
            for n in c.body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')
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
            'declared_test_methods': methods,
            'declared_test_method_count': len(methods),
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
    assert sum(r['bytes'] for r in files) == partition['bytes'] == 198027
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
            'Unlisted resident contract parser/atomic writer/alert transport and role-cycle last-row binding.',
            'Full router runtime budget/phase/cross-skill dispatch and independent scenario labelling.',
            'Reverse extraction/validation pipeline closure; Rust compiler/cargo and real acceptance.',
            'Scheduler real jobs, GC, install/service triggers, concurrent ownership and crash recovery.',
            'Seam helper/parser/transform closure and real fleet transport; actual approval consumers.',
            'Full graduation scans, replay/event hash semantics, detector reflection parser and activation.',
            'Unlisted settings, credentials and live state were not opened; no permission claim verified.',
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
        'primary_files': 23, 'primary_bytes': 198027,
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
