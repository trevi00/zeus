"""Record this bounded static review without importing or executing upstream code."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = ROOT / '.runtime/absorption/sources/harness'
PINNED = SOURCE / 'pinned'
REVISION = 'a3f8b3be9a0a389329de6e16a6c7db81782041a3'
PARTITION = 'harness:scripts/validators:001'
SCOPE = '344c8c3b818ff6312beacc781f0029c39ae531956048b4834eb74a5dd5c7e0bb'
REVIEW = 'docs/full-analysis/harness-validators-001/review.md'

# Every listed primary body was displayed in full; no upstream module is loaded.
PRIMARY = {
    'candidate_binding': (135, 'v01', 'First document marker versus last global pipeline candidate.',
                          ['pipelines/harness-selfimprove.yaml', 'scripts/lib/paths.py'], []),
    'ddl_dry_run': (57, 'v02', 'Configured database SQL execution followed by rollback.',
                    ['pipelines/core.yaml', 'scripts/lib/profile.py', 'scripts/engine/checks.py'], []),
    'harness_lint': (2092, 'v03', 'Twenty-five checks; mixed static scans, subprocess and side effects.',
                     ['scripts/cli/autoheart_cmd.py', 'scripts/lib/git_flow.py',
                      'scripts/handlers/pre_tool/write_boundary.py', 'scripts/lib/judgment_paths.py',
                      'scripts/engine/gate_runner.py', 'config/retriever.yaml'],
                     ['tests/contract/test_harness_lint.py',
                      'tests/contract/test_lint_contracts_smoke.py',
                      'tests/contract/test_gate_executable_contract.py', 'tests/_isolate.py']),
    'heredoc_guard': (138, 'v04', 'Quoted delimiter and backslash/backtick heuristic over selected files.',
                      ['config/policy/validator-ladder.json', 'scripts/engine/pr4.py'],
                      ['tests/contract/test_heredoc_guard_contract.py']),
    'intent_doc_floor': (98, 'v05', 'Origin/placeholder/anchor/evidence-path document floor.',
                         ['pipelines/reverse-onboarding.yaml'],
                         ['tests/integration/test_scaffold_smoke.py']),
    'isolation_deferred': (153, 'v06', 'Declared rerun location and caller-supplied skip count cap.',
                           ['scripts/cli/autoheart_cmd.py', 'scripts/cli/suite_cmd.py',
                            'scripts/lib/test_outcome.py'],
                           ['tests/contract/test_isolation_deferred_contract.py']),
    'ledger_semantics': (163, 'v07', 'Synthetic projection poison plus selected live-ledger invariants.',
                         ['scripts/lib/ledger.py', 'scripts/lib/paths.py',
                          'scripts/validators/harness_lint.py'],
                         ['tests/integration/test_integrity_smoke.py']),
    'ontology_validator': (218, 'v08', 'Schema, graph identity, enum and structural evidence checks.',
                            ['ontology/schema.json', 'scripts/lib/paths.py', 'pipelines/core.yaml',
                             'scripts/validators/harness_lint.py'],
                            ['tests/contract/test_ontology_smoke.py']),
    'pattern_decisions': (61, 'v09', 'Fixed six pattern headings and decision/reference/reason markers.',
                           ['config/policy/validator-ladder.json', 'scripts/engine/pr4.py'], []),
    'red_flags_scan': (53, 'v10', 'Required heading substring in selected skill Markdown.',
                       ['config/policy/validator-ladder.json', 'scripts/engine/pr4.py'],
                       ['tests/integration/test_small_batch_smoke.py']),
    'repair_evidence': (187, 'v11', 'Any pending item, NO-REPAIR marker or selected dirty file.',
                        ['pipelines/harness-selfimprove.yaml'],
                        ['tests/contract/test_repair_evidence_contract.py']),
    'settings_wiring': (297, 'v12', 'Hook shape, launcher, registry and synthetic spawn checks.',
                        ['.claude/settings.json', 'scripts/handlers/dispatch.sh',
                         'scripts/handlers/registry.py', 'scripts/cli/health_cmd.py',
                         'scripts/validators/harness_lint.py'],
                        ['tests/integration/test_health_smoke.py']),
    'todo_scan': (78, 'v13', 'Python marker scan with own-file exclusion and selected roots.',
                  ['config/policy/validator-ladder.json', 'scripts/engine/pr4.py',
                   'scripts/cli/ladder_cmd.py', 'scripts/cron/l2_driver.py'],
                  ['tests/contract/test_ladder_sweep_contract.py']),
    'tradeoff_lint': (244, 'v14', 'Tradeoff fence shape and closed metric/operator vocabulary.',
                      ['ontology/metrics.yaml', 'scripts/engine/checks.py', 'pipelines/core.yaml',
                       'config/paths.yaml'], ['tests/contract/test_tradeoff_lint_contract.py']),
    'usecase_lint': (84, 'v15', 'UC section and AC/GWT marker checks, not executable scenarios.',
                     ['pipelines/core.yaml', 'scripts/engine/gate_runner.py'],
                     ['tests/integration/test_engine_smoke.py']),
}

# Inclusive supporting ranges displayed and read during this review, not prior reuse.
SUPPORT = {
    'scripts/engine/checks.py': [(1, 66), (160, 215)],
    'scripts/lib/profile.py': [(1, 24)],
    'scripts/lib/ledger.py': [(321, 336), (417, 429)],
    'scripts/cli/autoheart_cmd.py': [(129, 176), (949, 963), (1050, 1086)],
    'scripts/cli/health_cmd.py': [(403, 424)],
    'scripts/cli/suite_cmd.py': [(358, 376), (404, 441), (443, 452), (605, 618)],
    'scripts/lib/test_outcome.py': [(45, 85)],
    'config/policy/validator-ladder.json': [(1, 66)],
    'scripts/engine/pr4.py': [(43, 143)],
    'tests/contract/test_isolation_deferred_contract.py': [(55, 96)],
    'tests/contract/test_repair_evidence_contract.py': [(65, 129)],
    'tests/integration/test_health_smoke.py': [(30, 96)],
    'tests/integration/test_integrity_smoke.py': [(30, 79)],
    'tests/integration/test_engine_smoke.py': [(187, 202)],
    'tests/integration/test_scaffold_smoke.py': [(117, 155)],
    'tests/contract/test_harness_lint.py': [(1, 40)],
    'tests/contract/test_heredoc_guard_contract.py': [(75, 155)],
    'pipelines/core.yaml': [(36, 57), (165, 201), (253, 272)],
    'pipelines/reverse-onboarding.yaml': [(35, 72)],
    'pipelines/harness-selfimprove.yaml': [(81, 96), (159, 180), (257, 272)],
    'tests/contract/test_tradeoff_lint_contract.py': [(126, 158), (220, 239)],
    'ontology/metrics.yaml': [(1, 89)],
    'tests/contract/test_ontology_smoke.py': [(102, 145), (154, 187), (239, 261)],
    'tests/integration/test_small_batch_smoke.py': [(75, 107)],
    'tests/contract/test_ladder_sweep_contract.py': [(220, 246)],
    'scripts/handlers/dispatch.sh': [(1, 25)],
    '.claude/settings.json': [(1, 98)],
    'scripts/lib/paths.py': [(24, 61), (122, 123)],
    'config/paths.yaml': [(1, 32)],
    'scripts/engine/gate_runner.py': [(28, 51), (88, 165)],
    'scripts/lib/judgment_paths.py': [(73, 129)],
    'scripts/lib/git_flow.py': [(31, 38), (71, 87)],
    'scripts/cron/l2_driver.py': [(408, 426)],
    'tests/contract/test_lint_contracts_smoke.py': [(228, 264), (390, 455), (776, 791)],
    'ontology/schema.json': [(196, 262), (306, 369)],
    'scripts/handlers/pre_tool/write_boundary.py': [(660, 710)],
    'scripts/cli/ladder_cmd.py': [(88, 113)],
    'tests/contract/test_gate_executable_contract.py': [(125, 148)],
    'tests/_isolate.py': [(37, 118)],
    'scripts/handlers/registry.py': [(27, 90)],
    'config/retriever.yaml': [(1, 15)],
}
ZEUS = {
    'src/codex_harness/domain/sdd.py': [(8, 22), (169, 202)],
    'src/codex_harness/application/sdd.py': [(159, 184)],
    'src/codex_harness/domain/model_routing.py': [(24, 39)],
    'AGENTS.md': [(1, 17)],
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8')


def main() -> None:
    manifest_raw = (SOURCE / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest['revision'] == REVISION
    inventory = {row['path']: row for row in manifest['inventory']}
    partitions_raw = (ROOT / 'docs/full-analysis/partitions.json').read_bytes()
    partition = next(row for row in json.loads(partitions_raw)
                     if row['partition'] == PARTITION)
    expected = [f'scripts/validators/{name}.py' for name in PRIMARY]
    assert partition['paths'] == [{'source': 'harness', 'path': p} for p in expected]
    assert partition['scope_sha256'] == SCOPE and partition['bytes'] == 194961
    review = (OUT / 'review.md').read_text(encoding='utf-8')
    assert '\ufffd' not in review
    for anchor in ['scope', 'trace', 'zeus', 'unknowns'] + [v[1] for v in PRIMARY.values()]:
        assert f'id="{anchor}"' in review

    def source_row(path: str, ranges: list[tuple[int, int]], anchor: str) -> dict:
        raw = (PINNED / path).read_bytes()
        item = inventory[path]
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        sha = sha256(raw)
        lines = len(raw.decode('utf-8').splitlines())
        assert item['type'] == 'blob' and item['object'] == blob
        assert item['bytes'] == len(raw)
        snap = item.get('snapshot_sha256')
        assert snap is None or snap == sha
        assert all(1 <= a <= b <= lines for a, b in ranges)
        return {
            'source': 'harness', 'path': path, 'revision': REVISION,
            'pinned_sha256': sha, 'git_blob': blob, 'bytes': len(raw), 'lines': lines,
            'manifest_snapshot_sha256_present': snap is not None,
            'manifest_snapshot_sha256': snap,
            'hash_verification': ('git_blob_and_bytes_and_snapshot_sha256'
                                  if snap else 'git_blob_and_bytes; fresh_sha256_only'),
            'upstream_disposition_unchanged': item['disposition'],
            'line_ranges': ranges, 'review_ref': f'{REVIEW}#{anchor}',
            'read_basis': 'displayed_and_read_current_review',
            'previous_review_reuse': None, 'tests_executed': [],
        }

    files = []
    for name, (lines, anchor, summary, trace, tests) in PRIMARY.items():
        row = source_row(f'scripts/validators/{name}.py', [(1, lines)], anchor)
        assert row['lines'] == lines
        row.update({
            'partition': PARTITION, 'disposition': 'semantically_reviewed',
            'read_extent': 'full_body', 'semantic_summary': summary,
            'finding_sections': [anchor, 'zeus', 'unknowns'],
            'caller_or_dependency_trace': trace, 'tests_read_in_part': tests,
            'test_limits': 'Selected test ranges only; no execution or acceptance evidence.',
            'remaining': ['Full transitive caller/config/test closure',
                          'Runtime and transition validation', 'License/adoption review',
                          'Actual independent Claude review'],
            'adoption_status': 'not_approved_not_incorporated',
        })
        files.append(row)
    assert len(files) == 15 and sum(row['bytes'] for row in files) == 194961
    support = []
    for path, ranges in SUPPORT.items():
        row = source_row(path, ranges, 'trace')
        row.update({'read_extent': 'listed_line_ranges_only',
                    'counted_in_partition_coverage': False})
        support.append(row)
    for path, ranges in ZEUS.items():
        raw = (ROOT / path).read_bytes()
        lines = len(raw.decode('utf-8').splitlines())
        assert all(1 <= a <= b <= lines for a, b in ranges), (path, lines)
        support.append({
            'source': 'zeus', 'path': path, 'revision': 'working_tree_not_source_manifest',
            'sha256': sha256(raw), 'bytes': len(raw), 'lines': lines, 'line_ranges': ranges,
            'read_extent': 'listed_line_ranges_only', 'review_ref': f'{REVIEW}#zeus',
            'read_basis': 'displayed_and_read_current_review', 'previous_review_reuse': None,
            'counted_in_partition_coverage': False, 'tests_executed': [],
        })
    write('files.json', files)
    write('supporting-evidence.json', support)
    write('checkpoint.json', {
        'partition': PARTITION, 'source': 'harness', 'revision': REVISION,
        'scope_sha256': SCOPE, 'manifest_sha256': sha256(manifest_raw),
        'partitions_sha256': sha256(partitions_raw),
        'primary_file_count': len(files), 'primary_bytes': 194961,
        'primary_full_body_read': True, 'support_harness_count': len(SUPPORT),
        'support_zeus_count': len(ZEUS), 'support_is_partial_not_primary_coverage': True,
        'prior_support_reuse_count': 0,
        'manifest_snapshot_sha256_missing': [row['path'] for row in files + support
                                            if row['source'] == 'harness'
                                            and not row['manifest_snapshot_sha256_present']],
        'status': 'static_body_review_complete_execution_and_closure_pending',
        'review_ref': f'{REVIEW}#scope',
        'review_sha256': sha256((OUT / 'review.md').read_bytes()),
        'upstream_execution_count': 0, 'tests_executed': [], 'model_invocation_count': 0,
        'source_instructions_inherited': False, 'blocked_probe_retried_or_bypassed': False,
        'source_modified': False, 'runtime_modified': False, 'shared_coverage_modified': False,
        'commit_or_push_performed': False, 'full_analysis_complete': False,
        'subsystem_complete': False, 'adoption_approved': False, 'acceptance_complete': False,
        'transition_closure_complete': False, 'license_review_complete': False,
        'claude_cross_review': 'root_managed_pending',
        'device_farm_and_samsung_execution': 'deferred_not_implemented_or_verified',
        'remaining': ['All transitive implementations/configurations/tests',
                      'Actual Windows/Linux/WSL execution and DB effect validation',
                      'Authenticated human acceptance', 'PG authority integration',
                      'License and independent review', 'Adoption decision'],
    })
    print(json.dumps({'primary_files': len(files), 'primary_bytes': 194961,
                      'support_files': len(support), 'upstream_executions': 0}))


if __name__ == '__main__':
    main()
