"""Record bounded static reads; never import or execute the reviewed source."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = ROOT / '.runtime/absorption/sources/harness'
PINNED = SOURCE / 'pinned'
REVISION = 'a3f8b3be9a0a389329de6e16a6c7db81782041a3'
PARTITION = 'harness:tests/integration:004'
SCOPE = 'a2f4e64585fba3f48a8eb84ea7014eda4d89b6dc7cb52b2f7a229c7cd330b577'
REVIEW = 'docs/full-analysis/harness-integration-tests-004/review.md'

PRIMARY = {'test_mutation_baseline_smoke': (245,
                                  'i01',
                                  'Actual fixture Git/worktree runner; current baseline guard and fake CLI '
                                  'report separated.',
                                  ['scripts/engine/mutation.py',
                                   'scripts/engine/sandbox.py',
                                   'scripts/cli/quality_cmd.py',
                                   'ontology/contracts.yaml']),
 'test_ownership_vitals_smoke': (194,
                                 'i02',
                                 'Synthetic ownership metrics and actual fixture incident writer; deferred '
                                 'dispatcher remains.',
                                 ['scripts/lib/ownership_vitals.py',
                                  'scripts/lib/ownership_events.py',
                                  'scripts/cli/incident_cmd.py',
                                  'scripts/validators/harness_lint.py',
                                  'scripts/cli/health_cmd.py']),
 'test_params_smoke': (165,
                       'i03',
                       'Registry fallback and direction fixtures; detector receipt does not preserve queried '
                       'settings.',
                       ['scripts/lib/params.py',
                        'config/params.json',
                        'scripts/engine/pollution.py',
                        'scripts/engine/sandbox.py']),
 'test_polish_smoke': (194,
                       'i04',
                       'Fixture hook install/remove, injected heartbeat errors, synthetic human gates and '
                       'path-only completion.',
                       ['scripts/cli/delegate_cmd.py',
                        'scripts/handlers/stop/heartbeat.py',
                        'scripts/cli/health_cmd.py',
                        'scripts/cli/completion_cmd.py',
                        'scripts/lib/completion_line.py']),
 'test_pollution_smoke': (156,
                          'i05',
                          'Burst heuristics and tombstones, not authenticated classification of production '
                          'events.',
                          ['scripts/engine/pollution.py',
                           'scripts/cli/pollution_cmd.py',
                           'scripts/lib/params.py']),
 'test_preconditions_smoke': (152,
                              'i06',
                              'Text/JSON fingerprints and file gate rerun; unknown syntax and scan errors '
                              'have limits.',
                              ['scripts/lib/preconditions.py',
                               'scripts/engine/staleness.py',
                               'scripts/engine/pipeline_loader.py',
                               'scripts/engine/gate_runner.py',
                               'scripts/engine/tick.py']),
 'test_probe_smoke': (158,
                      'i07',
                      'Machine anchor counterfactual and synthetic residual pass; no authenticated human '
                      'acceptance.',
                      ['scripts/engine/counterfactual.py',
                       'scripts/cli/residual_cmd.py',
                       'scripts/cli/probe_cmd.py']),
 'test_prompt_rollup_smoke': (198,
                              'i08',
                              'Real fixture SQLite with current first-write failure guard; zero-row receipt '
                              'not directly exercised.',
                              ['scripts/handlers/stop/prompt_rollup.py',
                               'scripts/handlers/prompt/promptlog.py',
                               'scripts/cli/prompts_cmd.py']),
 'test_promptlog_smoke': (277,
                          'i09',
                          'SQLite recording and clustering plus min/paired cost statistics, not full '
                          'prompt-path SLO.',
                          ['scripts/handlers/prompt/promptlog.py',
                           'scripts/cli/prompts_cmd.py',
                           'scripts/lib/prompt_clusters.py']),
 'test_proposal_retire_smoke': (316,
                                'i10',
                                'Autonomous negative stamp and early CLI refusals; missing stamp is not '
                                'positive human proof.',
                                ['scripts/lib/backlog.py',
                                 'scripts/lib/ledger.py',
                                 'scripts/cli/spiral_cmd.py',
                                 'scripts/handlers/pre_tool/write_boundary.py']),
 'test_provenance_stamp_smoke': (225,
                                 'i11',
                                 'Fake Guardian proof and current three-state provenance; brief lacks arming '
                                 'proof parity.',
                                 ['scripts/lib/approval_proof.py',
                                  'scripts/lib/arming.py',
                                  'scripts/lib/ledger.py',
                                  'scripts/cron/re_anchor.py']),
 'test_reanchor_binding_smoke': (216,
                                 'i12',
                                 'Actual fixture compose subprocess with current project filtering; '
                                 'proofless approvals still displayed.',
                                 ['scripts/cron/re_anchor.py', 'scripts/lib/completion_line.py']),
 'test_recall_retrieval_canary': (303,
                                  'i13',
                                  'Fixed corpus query-hit rate and duplicate FTS arms, not actual recall '
                                  'consumer acceptance.',
                                  ['scripts/engine/recall.py']),
 'test_repair_tier_smoke': (158,
                            'i14',
                            'Fixture FAIL families and directive tokens; cumulative counts not consecutive '
                            'repair execution.',
                            ['scripts/lib/repair_tier.py',
                             'scripts/engine/gate_runner.py',
                             'scripts/engine/tick.py']),
 'test_rlm_smoke': (131,
                    'i15',
                    'Actual stdio kernel if executed; secret env filtering not OS sandbox or enforced model '
                    'depth.',
                    ['scripts/engine/rlm_kernel.py', 'scripts/handlers/rlm_launcher.sh', '.mcp.json']),
 'test_role_attribution_smoke': (280,
                                 'i16',
                                 'Actual CLI dispatch records and synthetic render cites, no agent spawn or '
                                 'return.',
                                 ['scripts/cli/step_cmd.py',
                                  'scripts/lib/roster.py',
                                  'scripts/engine/tick.py']),
 'test_roster_contract_smoke': (120,
                                'i17',
                                'Roster full prompt contract differs from truncated step delivery; current '
                                'delivery reader reads HOME ledger.',
                                ['scripts/cli/roster_cmd.py',
                                 'scripts/cli/agentsmd_cmd.py',
                                 'scripts/lib/roster.py',
                                 'scripts/cli/step_cmd.py'])}

SUPPORT = {'scripts/engine/mutation.py': [(60, 153)],
 'scripts/cli/quality_cmd.py': [(20, 48), (74, 183)],
 'scripts/lib/ownership_vitals.py': [(22, 77)],
 'scripts/lib/ownership_events.py': [(24, 74)],
 'scripts/cli/incident_cmd.py': [(33, 138)],
 'scripts/lib/params.py': [(46, 158)],
 'scripts/cli/delegate_cmd.py': [(36, 147)],
 'scripts/handlers/stop/heartbeat.py': [(1, 45)],
 'scripts/lib/preconditions.py': [(33, 100)],
 'scripts/engine/staleness.py': [(18, 46)],
 'scripts/engine/counterfactual.py': [(25, 109)],
 'scripts/engine/pollution.py': [(49, 121)],
 'scripts/handlers/prompt/promptlog.py': [(47, 133)],
 'scripts/handlers/stop/prompt_rollup.py': [(63, 196)],
 'scripts/lib/approval_proof.py': [(64, 136)],
 'scripts/cron/re_anchor.py': [(59, 247)],
 'scripts/engine/recall.py': [(31, 45), (129, 147)],
 'scripts/lib/repair_tier.py': [(34, 82)],
 'scripts/engine/rlm_kernel.py': [(27, 155), (181, 237)],
 'scripts/lib/backlog.py': [(46, 77), (206, 238)],
 'scripts/lib/arming.py': [(368, 415)],
 'scripts/cli/spiral_cmd.py': [(570, 649)],
 'scripts/cli/step_cmd.py': [(23, 27), (37, 74), (198, 215), (288, 345), (438, 498)],
 'scripts/cli/roster_cmd.py': [(40, 222)],
 'scripts/cli/agentsmd_cmd.py': [(53, 86)],
 'scripts/cli/health_cmd.py': [(648, 738)],
 'scripts/validators/harness_lint.py': [(99, 121), (437, 495)],
 'scripts/cli/completion_cmd.py': [(80, 104)],
 'scripts/lib/completion_line.py': [(63, 87)],
 'scripts/engine/gate_runner.py': [(129, 178)],
 'scripts/engine/tick.py': [(100, 119), (188, 214), (300, 326)],
 'scripts/cli/prompts_cmd.py': [(49, 54), (72, 127)],
 'scripts/lib/prompt_clusters.py': [(45, 101)],
 'scripts/engine/sandbox.py': [(74, 83), (172, 252)],
 'scripts/engine/pipeline_loader.py': [(366, 378)],
 'scripts/lib/roster.py': [(1, 27)],
 'config/params.json': [(1, 19)],
 'ontology/contracts.yaml': [(539, 548)],
 'scripts/handlers/rlm_launcher.sh': [(1, 13)],
 '.mcp.json': [(1, 8)],
 'scripts/cli/residual_cmd.py': [(88, 113)],
 'scripts/cli/probe_cmd.py': [(20, 114)],
 'scripts/cli/pollution_cmd.py': [(22, 69)],
 'scripts/handlers/pre_tool/write_boundary.py': [(706, 725), (838, 897), (1036, 1046)],
 'scripts/lib/ledger.py': [(279, 320)]}
PRIOR_DIR = ROOT / 'docs/full-analysis/harness-integration-tests-001'
REUSE_PATHS = {'config/paths.yaml',
 'scripts/cli/suite_cmd.py',
 'scripts/lib/derive_state.py',
 'scripts/lib/ledger.py',
 'scripts/lib/paths.py',
 'scripts/lib/test_outcome.py',
 'tests/_isolate.py'}
ZEUS = {}
REMAINING = [
    'Upstream execution and runtime failure reproduction; no execution is authorized in this review.',
    'Full transitive callers, fixtures, policies, tests and deployment closure.',
    'Authenticated human acceptance and real product/device evidence.',
    'Windows, Linux, WSL, concurrency, reset and process isolation matrix.',
    'Actual independent Claude review managed by root.',
    'License and redistribution review; adoption approval and Zeus implementation.',
]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    manifest_raw = (SOURCE / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest['revision'] == REVISION
    inventory = {row['path']: row for row in manifest['inventory']}
    partitions_raw = (ROOT / 'docs/full-analysis/partitions.json').read_bytes()
    partition = next(row for row in json.loads(partitions_raw) if row['partition'] == PARTITION)
    expected = [f'tests/integration/{name}.py' for name in PRIMARY]
    assert partition['paths'] == [{'source': 'harness', 'path': p} for p in expected]
    assert partition['scope_sha256'] == SCOPE and partition['bytes'] == 173845
    review_raw = (OUT / 'review.md').read_bytes()
    review = review_raw.decode('utf-8')
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
    for name, (lines, anchor, summary, trace) in PRIMARY.items():
        row = source_row(f'tests/integration/{name}.py', [(1, lines)], anchor)
        assert row['lines'] == lines
        row.update({
            'partition': PARTITION, 'disposition': 'semantically_reviewed',
            'read_extent': 'full_body', 'semantic_summary': summary,
            'finding_sections': [anchor, 'trace', 'zeus', 'unknowns'],
            'caller_or_dependency_trace': trace,
            'test_kind': 'helper_shim' if name == '_isolate' else 'standalone_smoke_script',
            'declared_entrypoint': 'Standalone __main__ script; dynamic check denominator; early-return and skip semantics detailed per file',
            'denominator_basis': 'Full source body; emitted checks are conditional/dynamic and not executed.',
            'tests_read_in_part': [f'tests/integration/{name}.py'] if name != '_isolate' else [],
            'test_limits': 'Static oracle/fixture/caller analysis only; asserts are not PASS or human acceptance.',
            'remaining': REMAINING,
            'adoption_status': 'not_approved_not_incorporated',
        })
        files.append(row)
    assert len(files) == 17 and sum(row['bytes'] for row in files) == 173845
    support = []
    for path, ranges in SUPPORT.items():
        row = source_row(path, ranges, 'trace')
        row.update({'read_extent': 'listed_line_ranges_only', 'counted_in_partition_coverage': False})
        support.append(row)
    prior_raw = (PRIOR_DIR / 'supporting-evidence.json').read_bytes()
    prior_rows = json.loads(prior_raw)
    reused = 0
    zeus_count = 0
    for old in prior_rows:
        if old['source'] != 'zeus' and old['path'] not in REUSE_PATHS:
            continue
        path = old['path']
        raw = ((ROOT if old['source'] == 'zeus' else PINNED) / path).read_bytes()
        expected_sha = old.get('pinned_sha256') or old['sha256']
        assert sha256(raw) == expected_sha
        row = (source_row(path, old['line_ranges'], 'trace')
               if old['source'] == 'harness' else dict(old))
        if old['source'] == 'zeus':
            zeus_count += 1
            row['review_ref'] = f'{REVIEW}#zeus'
        row.update({
            'read_extent': 'listed_line_ranges_only',
            'read_basis': 'same_bytes_prior_read_ranges_reused',
            'counted_in_partition_coverage': False,
            'prior_ref': old['review_ref'],
            'previous_review_reuse': {
                'review_ref': old['review_ref'],
                'supporting_ledger': 'docs/full-analysis/harness-integration-tests-001/supporting-evidence.json',
                'supporting_ledger_sha256': sha256(prior_raw),
                'path': path, 'sha256': expected_sha,
                'revision': old.get('revision'), 'source_row': old,
                'line_ranges': old['line_ranges'],
                'same_bytes_verified_current_review': True,
            },
        })
        support.append(row)
        reused += 1
    assert reused == len(REUSE_PATHS) + 4
    write('files.json', files)
    write('supporting-evidence.json', support)
    write('remaining.json', {
        'partition': PARTITION, 'primary_body_remaining': [],
        'remaining': REMAINING,
        'specific_partial_traces': [
            'Mutation exact replacement sites, equivalent mutants, worktree concurrency and baseline outcome classification.',
            'Ownership tail dispatcher, all live contracts/cards, actual incident and human response.',
            'Parameter direction policy, detector receipt binding, nonfinite input and concurrent updates.',
            'Delegate mixed hook preservation, runtime pins and Windows/Linux/WSL execution.',
            'Precondition errors and raw-byte/environment fidelity, counterfactual crash restoration.',
            'Prompt logging loss notification, retention policy, second digest write, backdated concurrent rows.',
            'Proposal retirement positive human proof, signed artifact/version and brief versus arming parity.',
            'Actual recall backend and judged retrieval relevance, PG hybrid and real model qualification.',
            'RLM execution limits, process tree cleanup and device replay, complete role contract delivery.',
        ],
        'review_ref': f'{REVIEW}#unknowns',
    })
    write('checkpoint.json', {
        'partition': PARTITION, 'source': 'harness', 'revision': REVISION,
        'scope_sha256': SCOPE, 'manifest_sha256': sha256(manifest_raw),
        'partitions_sha256': sha256(partitions_raw),
        'primary_file_count': len(files), 'primary_bytes': 173845,
        'primary_lines': sum(row['lines'] for row in files),
        'primary_full_body_read': True, 'standalone_test_scripts': 17, 'helper_shims': 0,
        'support_harness_count': len(SUPPORT) + len(REUSE_PATHS), 'support_zeus_count': zeus_count,
        'support_is_partial_not_primary_coverage': True, 'prior_support_reuse_count': reused,
        'manifest_snapshot_sha256_missing': [row['path'] for row in files + support
                                            if row['source'] == 'harness'
                                            and not row['manifest_snapshot_sha256_present']],
        'review_sha256': sha256(review_raw), 'review_ref': f'{REVIEW}#scope',
        'original_executions': 0, 'original_imports': 0, 'probes': 0, 'upstream_tests_executed': 0,
        'model_calls': 0, 'network_calls': 0, 'installs': 0, 'blocked_probe_retried_or_bypassed': False,
        'source_runtime_or_shared_coverage_modified': False, 'committed_or_pushed': False,
        'local_recording_only': True, 'bounded_static_review_complete': True,
        'full_analysis_complete': False, 'subsystem_transition_closure_complete': False,
        'human_acceptance_passed': False, 'device_acceptance_passed': False,
        'license_review_complete': False, 'adoption_approved': False, 'implemented': False,
        'actual_claude_independent_review': 'pending_root_managed',
        'artifact_sha256': {name: sha256((OUT / name).read_bytes()) for name in
                            ('files.json', 'supporting-evidence.json', 'remaining.json', 'record_review.py')},
        'remaining': REMAINING,
    })
    write('verification.json', {
        'scope_match': True, 'primary_hash_size_git_blob_checks': True,
        'support_hash_size_git_blob_checks': True, 'explicit_anchor_checks': True,
        'primary_count': len(files), 'primary_bytes': 173845,
        'support_count': len(support), 'review_sha256': sha256(review_raw),
        'method': 'Own stdlib metadata recorder only; no source import/execution.',
        'upstream_tests_executed': 0, 'upstream_pass_claimed': False,
    })
    print(json.dumps({'files': len(files), 'bytes': 173845, 'supports': len(support),
                      'missing_manifest_sha': [row['path'] for row in files + support
                                               if row['source'] == 'harness'
                                               and not row['manifest_snapshot_sha256_present']],
                      'review_sha256': sha256(review_raw)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
