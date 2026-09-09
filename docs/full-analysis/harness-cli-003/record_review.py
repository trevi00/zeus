"""Record only this static review; never import or execute upstream code."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = ROOT / '.runtime/absorption/sources/harness'
PINNED = SOURCE / 'pinned'
REVISION = 'a3f8b3be9a0a389329de6e16a6c7db81782041a3'
PARTITION = 'harness:scripts/cli:003'
SCOPE = 'c653c4b6f02f2d7573f86ef4934a2564e8b85021c25eff0413e4b1e99c399516'
REVIEW = 'docs/full-analysis/harness-cli-003/review.md'

PRIMARY = {
    'invariants': ('C06', 'Text declaration/use/test-label census; attributed mutation command.',
                   ['scripts/engine/mutation.py', 'config/paths.yaml'],
                   ['tests/contract/test_inv_bite_smoke.py']),
    'judge': ('C05', 'Provider pool dispatch, guarded advisory votes and axis/quorum projection.',
              ['scripts/lib/evaluator.py', 'scripts/lib/codex_provider.py'],
              ['tests/integration/test_jury_quorum_smoke.py']),
    'ladder': ('C01', 'Validator policy sweep, status, promotion, demotion and threshold adjustment.',
               ['scripts/engine/pr4.py', 'scripts/engine/golden.py',
                'config/policy/validator-ladder.json'],
               ['tests/integration/test_ladder_smoke.py']),
    'mirror': ('C08', 'Knowledge index and kickoff coverage projection writes.',
               ['scripts/engine/mirror.py'], ['tests/integration/test_mirror_smoke.py']),
    'ontology': ('C08', 'Index generation then subprocess validation; cached node/edge query.',
                 ['scripts/engine/ontology_index.py', 'config/paths.yaml'], []),
    'pollution': ('C11', 'Burst-based pollution diagnosis and dry-run/execute tombstone contract.',
                  ['scripts/engine/pollution.py', 'scripts/lib/derive_state.py'],
                  ['tests/integration/test_pollution_smoke.py']),
    'probe': ('C06', 'Counterfactual output mutation/restoration and blindspot declaration surface.',
              ['scripts/engine/counterfactual.py'], ['tests/integration/test_probe_smoke.py']),
    'prompts': ('C07', 'Prompt SQLite statistics, clustering, manual pruning and weekly rollup.',
                ['scripts/handlers/stop/prompt_rollup.py', 'scripts/handlers/prompt/promptlog.py'],
                ['tests/integration/test_prompt_rollup_smoke.py']),
    'quality': ('C06,C09', 'Golden/mutation runner exits and skill-usage versus stage-verdict correlation.',
                ['scripts/engine/golden.py', 'scripts/engine/mutation.py',
                 'scripts/engine/skill_router.py'], []),
    'recall': ('C08', 'Incremental FTS index and advisory retrieval with snippet scanning.',
               ['scripts/engine/recall.py'], []),
    'residual': ('C02', 'Human residual listing and operator gate-check writes.',
                 ['scripts/engine/gate_runner.py', 'scripts/lib/derive_state.py'],
                 ['tests/integration/test_cli_smoke.py']),
    'roster': ('C09', 'Role-card rendering, textual callsite census and dispatch tally.',
               ['scripts/cli/step_cmd.py'], ['tests/integration/test_roster_contract_smoke.py']),
    'run': ('C04', 'Validated pipeline arming, binding projection, disarm event and status.',
            ['scripts/lib/guardian_contract.py', 'scripts/lib/derive_state.py',
             'scripts/cron/l2_driver.py'], ['tests/integration/test_cli_smoke.py']),
    'safety': ('C10', 'Time-window hook decision/post-event correlation and denominator reporting.',
               ['scripts/lib/hook_journal.py', 'scripts/handlers/stop/prompt_rollup.py'], []),
    'sandbox': ('C03', 'Patch classification, suite floor, environment seal, parking and promotion.',
                ['scripts/engine/sandbox.py', 'scripts/handlers/pre_tool/write_boundary.py',
                 'scripts/lib/hook_protocol.py'], []),
    'scaffold': ('C10', 'Common/stack template inventory and non-overwrite issuance.',
                 ['config/paths.yaml'], ['tests/integration/test_scaffold_smoke.py']),
    'skill_eval': ('C09', 'Synthetic self-routing, declaration, slice and axis delivery evaluation.',
                   ['scripts/lib/skill_eval.py', 'scripts/engine/skill_router.py',
                    'scripts/engine/pipeline_loader.py', 'scripts/cli/autoheart_cmd.py',
                    'config/retriever.yaml'], ['tests/contract/test_skill_eval.py']),
    'skills': ('C09', 'Frontmatter/corpus contract audit and mixed JSON/human CLI result.',
               ['config/paths.yaml', 'config/retriever.yaml'], []),
}

# Inclusive line ranges actually displayed and read. Final endpoints are explicit.
SUPPORT = {
    'scripts/lib/evaluator.py': [(72, 113), (169, 255), (431, 504)],
    'scripts/engine/gate_runner.py': [(28, 51), (88, 165)],
    'scripts/lib/derive_state.py': [(33, 147), (182, 230)],
    'scripts/lib/guardian_contract.py': [(36, 72)],
    'scripts/cron/l2_driver.py': [(670, 718), (1105, 1136)],
    'scripts/engine/sandbox.py': [(172, 221), (253, 283), (340, 446), (497, 545)],
    'scripts/lib/codex_provider.py': [(107, 158), (221, 297), (414, 464)],
    'scripts/handlers/pre_tool/write_boundary.py': [(825, 865)],
    'scripts/lib/hook_protocol.py': [(36, 46), (74, 79)],
    'scripts/engine/pr4.py': [(83, 221)],
    'scripts/engine/mirror.py': [(50, 147)],
    'scripts/engine/pollution.py': [(66, 121)],
    'scripts/engine/counterfactual.py': [(44, 109)],
    'scripts/engine/recall.py': [(88, 147)],
    'scripts/engine/golden.py': [(31, 76)],
    'scripts/handlers/stop/prompt_rollup.py': [(63, 187)],
    'scripts/handlers/prompt/promptlog.py': [(47, 101)],
    'scripts/lib/hook_journal.py': [(130, 231)],
    'scripts/engine/skill_router.py': [(157, 186), (210, 260), (299, 397)],
    'scripts/lib/skill_eval.py': [(36, 121), (177, 209)],
    'tests/integration/test_ladder_smoke.py': [(70, 148)],
    'tests/integration/test_cli_smoke.py': [(118, 159)],
    'tests/integration/test_jury_quorum_smoke.py': [(55, 105), (125, 200)],
    'tests/contract/test_skill_eval.py': [(186, 244)],
    'tests/contract/test_inv_bite_smoke.py': [(30, 117)],
    'tests/integration/test_roster_contract_smoke.py': [(25, 97)],
    'tests/integration/test_scaffold_smoke.py': [(90, 120)],
    'config/policy/validator-ladder.json': [(1, 66)],
    'config/paths.yaml': [(1, 32)],
    'scripts/cli/step_cmd.py': [(151, 212), (440, 459)],
    'scripts/cli/autoheart_cmd.py': [(263, 280)],
    'scripts/engine/pipeline_loader.py': [(37, 43)],
    'tests/integration/test_prompt_rollup_smoke.py': [(73, 145)],
    'tests/integration/test_pollution_smoke.py': [(70, 147)],
    'tests/integration/test_mirror_smoke.py': [(66, 115)],
    'tests/integration/test_probe_smoke.py': [(116, 145)],
    'scripts/engine/ontology_index.py': [(253, 288)],
    'config/retriever.yaml': [(1, 15)],
    'scripts/engine/mutation.py': [(85, 153)],
}
ZEUS = {
    'src/codex_harness/domain/model_routing.py': [(1, 39)],
    'src/codex_harness/domain/sdd.py': [(1, 24), (137, 202)],
    'src/codex_harness/application/sdd.py': [(104, 130), (159, 191)],
    'src/codex_harness/application/releases.py': [(65, 145)],
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def blob(raw: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def write(name: str, data: object) -> None:
    assert Path(name).name == name
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')


def main() -> None:
    manifest_raw = (SOURCE / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest['revision'] == REVISION
    inventory = {r['path']: r for r in manifest['inventory']}
    partition_raw = (ROOT / 'docs/full-analysis/partitions.json').read_bytes()
    part = next(p for p in json.loads(partition_raw) if p['partition'] == PARTITION)
    assert part['scope_sha256'] == SCOPE and part['bytes'] == 171177
    expected = {f'scripts/cli/{name}_cmd.py' for name in PRIMARY}
    assert expected == {r['path'] for r in part['paths']} and len(expected) == 18

    def source_row(path: str) -> dict:
        raw = (PINNED / path).read_bytes()
        inv = inventory[path]
        sha, git = digest(raw), blob(raw)
        assert inv['type'] == 'blob' and inv['object'] == git and inv['bytes'] == len(raw), path
        present = bool(inv.get('snapshot_sha256'))
        if present:
            assert inv['snapshot_sha256'] == sha, path
        return {'source': 'harness', 'path': path, 'revision': REVISION,
                'pinned_sha256': sha, 'git_blob': git, 'bytes': len(raw),
                'lines': len(raw.decode('utf-8').splitlines()),
                'manifest_snapshot_sha256_present': present,
                'manifest_snapshot_sha256': inv.get('snapshot_sha256'),
                'hash_verification': ('manifest_sha256_git_blob_bytes' if present else
                                      'manifest_sha256_absent_git_blob_bytes_verified_sha256_computed'),
                'upstream_disposition_unchanged': inv['disposition']}

    files = []
    for path in sorted(expected):
        row = source_row(path)
        key = Path(path).stem.removesuffix('_cmd')
        section, summary, trace, tests = PRIMARY[key]
        row.update(partition=PARTITION, disposition='semantically_reviewed',
                   read_extent='full_body', line_ranges=[[1, row['lines']]],
                   semantic_summary=summary, review_ref=REVIEW,
                   finding_sections=section.split(','),
                   caller_or_dependency_trace=trace, tests_read_in_part=tests,
                   tests_executed=[],
                   test_limits=('Listed test ranges read only; synthetic fixtures are not acceptance.'
                                if tests else 'No dedicated test body selected in this bounded review.'),
                   remaining=['Upstream execution and current-runtime reproduction not performed.',
                              'Supporting trace limited to listed ranges; not complete subsystem analysis.',
                              'Windows/Linux/WSL, real-device acceptance and authenticated approval unverified.'],
                   adoption_status='not_approved_not_incorporated')
        files.append(row)
    assert sum(r['bytes'] for r in files) == 171177
    support = []
    for path, ranges in SUPPORT.items():
        row = source_row(path)
        assert all(1 <= lo <= hi <= row['lines'] for lo, hi in ranges), path
        row.update(line_ranges=ranges, read_extent='listed_line_ranges_only',
                   counted_in_partition_coverage=False, review_ref=REVIEW, tests_executed=[])
        support.append(row)
    for path, ranges in ZEUS.items():
        raw = (ROOT / path).read_bytes()
        lines = len(raw.decode('utf-8').splitlines())
        assert all(1 <= lo <= hi <= lines for lo, hi in ranges), path
        support.append({'source': 'zeus-working-tree', 'path': path,
                        'revision': 'working_tree_at_read_parent_assignment_a7ed852',
                        'pinned_sha256': digest(raw), 'git_blob': blob(raw),
                        'bytes': len(raw), 'lines': lines, 'line_ranges': ranges,
                        'hash_verification': 'working_tree_bytes_not_source_manifest',
                        'read_extent': 'listed_line_ranges_only',
                        'counted_in_partition_coverage': False, 'review_ref': REVIEW,
                        'tests_executed': []})
    write('files.json', files)
    write('supporting-evidence.json', support)
    write('checkpoint.json', {
        'partition': PARTITION, 'scope_sha256': SCOPE, 'source': 'harness',
        'revision': REVISION, 'manifest_sha256': digest(manifest_raw),
        'partitions_file_sha256_at_record': digest(partition_raw),
        'expected_files': 18, 'full_body_files': len(files), 'expected_bytes': 171177,
        'full_body_bytes': sum(r['bytes'] for r in files),
        'primary_paths_hash_verified': True,
        'supporting_files': len(support), 'upstream_supporting_files': len(SUPPORT),
        'zeus_working_tree_supporting_files': len(ZEUS),
        'manifest_sha256_missing_primary': [r['path'] for r in files
                                           if not r['manifest_snapshot_sha256_present']],
        'manifest_sha256_missing_supporting': [r['path'] for r in support
                                              if r['source'] == 'harness'
                                              and not r['manifest_snapshot_sha256_present']],
        'status': 'static_review_complete_execution_and_independent_review_pending',
        'upstream_execution_count': 0, 'tests_executed': [],
        'blocked_gate_writer_probe_retried': False, 'source_instructions_inherited': False,
        'shared_coverage_modified': False, 'source_or_runtime_modified': False,
        'commit_or_push_performed': False, 'subsystem_complete': False,
        'full_analysis_complete': False, 'adoption_approved': False,
        'acceptance_passed': False, 'device_execution': 'deferred_by_user',
        'claude_cross_review': 'root_managed_pending', 'review_ref': REVIEW,
        'unknowns': ['No upstream execution or test/probe reproduction.',
                     'Only bounded caller/config/test ranges, not entire dependency closure.',
                     'Authentication, concurrent state transitions and PG writer equivalence unexecuted.',
                     'Real deployment, rollback and Windows/Linux/WSL behavior unexecuted.',
                     'Samsung devices, Device Farm SDK/MCP/live/replay deferred; not implemented here.',
                     'Model-transfer qualification and real monetary acceptance not proven.'],
    })
    print(json.dumps({'files': len(files), 'bytes': 171177, 'supporting': len(support),
                      'metadata_hash_checks': 'passed', 'upstream_execution_count': 0}))


if __name__ == '__main__':
    main()
