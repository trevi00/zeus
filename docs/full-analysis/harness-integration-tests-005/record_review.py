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
PARTITION = 'harness:tests/integration:005'
SCOPE = '7aade2df253abd62a9efe89c1a90e1e02c5da18584bb77f2210746a0445e4f6a'
REVIEW = 'docs/full-analysis/harness-integration-tests-005/review.md'

PRIMARY = {'test_sandbox_smoke': (519,
                        'i01',
                        'Actual temporary Git/worktree fixture; synthetic approval; rc-only suite reader '
                        'differs from skip-aware suite CLI.',
                        ['scripts/engine/sandbox.py',
                         'scripts/cli/sandbox_cmd.py',
                         'scripts/lib/suite_floor.py']),
 'test_scaffold_smoke': (216,
                         'i02',
                         'Template issuance, intent floor and extracted structure fixtures; specialization '
                         'and classification oracles are partial.',
                         ['scripts/cli/scaffold_cmd.py',
                          'scripts/validators/intent_doc_floor.py',
                          'scripts/engine/reverse.py',
                          'scripts/engine/extractors/python_conceptual.py',
                          'scripts/engine/extractors/python_flows.py',
                          'scripts/engine/extractors/python_convention.py',
                          'scripts/engine/extractors/intent_seed.py',
                          'scripts/engine/extractors/doc_classifier.py']),
 'test_seams_ladder_smoke': (199,
                             'i03',
                             'Synthetic streak/document identities and actual local golden fixture; '
                             'automatic blocking lacks CLI canary invocation.',
                             ['scripts/lib/seams.py',
                              'scripts/engine/graph_queries.py',
                              'scripts/cli/ladder_cmd.py',
                              'knowledge/golden/fixtures/probe_seams_blocking.py',
                              'knowledge/golden/cases.yaml']),
 'test_seams_smoke': (115,
                      'i04',
                      'Document field-set parity fixtures; current missing-source ERROR and advisory PASS '
                      'are distinct from runtime acceptance.',
                      ['scripts/lib/seams.py',
                       'scripts/engine/graph_queries.py',
                       'ontology/graph-queries.yaml']),
 'test_small_batch_smoke': (780,
                            'i05',
                            'Synthetic hook payloads, substitute push gates, transcript byte proxy and '
                            'xfail skeletons; current env restoration preserved.',
                            ['scripts/handlers/pre_tool/write_boundary.py',
                             'scripts/lib/git_flow.py',
                             'scripts/lib/external_text.py',
                             'scripts/engine/testgen.py',
                             'scripts/handlers/stop/reenforce.py',
                             'scripts/engine/skill_router.py',
                             'scripts/validators/red_flags_scan.py',
                             'agents/planner.md']),
 'test_spiral_smoke': (169,
                       'i06',
                       'Two-stage file-existence pipeline, synthetic events and actual fold/compaction; '
                       'convergence is not renewed acceptance.',
                       ['scripts/cli/cycle_cmd.py',
                        'scripts/engine/select_ready.py',
                        'scripts/engine/pipeline_loader.py',
                        'scripts/lib/derive_state.py',
                        'scripts/lib/ledger.py']),
 'test_stuck_smoke': (191,
                      'i07',
                      'Synthetic repetition patterns and temporary-home reanchor subprocess; wiring '
                      'strings do not prove delivery or positive approval.',
                      ['scripts/lib/stuck.py',
                       'scripts/engine/circuit.py',
                       'scripts/cron/re_anchor.py',
                       'scripts/cron/l2_driver.py']),
 'test_token_notify_smoke': (250,
                             'i08',
                             'Fake guardian token, queue deltas and marker-only child; fixture-missing '
                             'skip and notification receipt limits.',
                             ['scripts/cron/l2_driver.py',
                              '.claude/commands/unattended.md',
                              'tests/_isolate.py',
                              'scripts/lib/test_outcome.py']),
 'test_unattended_fence_smoke': (286,
                                 'i09',
                                 'Synthetic shell/file symmetry plus real-home unstamped CLI negative '
                                 'candidates; environment stamp is not human authentication.',
                                 ['scripts/handlers/pre_tool/write_boundary.py',
                                  'scripts/cli/spiral_cmd.py',
                                  'scripts/cli/sandbox_cmd.py',
                                  'config/policy/write-boundary.json',
                                  'scripts/lib/paths.py'])}

SUPPORT = {'scripts/cli/spiral_cmd.py': [(571, 656)],
 'scripts/cli/sandbox_cmd.py': [(121, 172), (193, 245)],
 'scripts/engine/sandbox.py': [(172, 417), (459, 535)],
 'scripts/lib/seams.py': [(53, 174)],
 'scripts/engine/graph_queries.py': [(629, 714)],
 'scripts/cli/ladder_cmd.py': [(45, 84)],
 'knowledge/golden/fixtures/probe_seams_blocking.py': [(1, 65)],
 'scripts/cli/scaffold_cmd.py': [(22, 61)],
 'scripts/validators/intent_doc_floor.py': [(26, 74)],
 'scripts/engine/reverse.py': [(155, 212)],
 'scripts/engine/testgen.py': [(1, 70)],
 'scripts/cli/cycle_cmd.py': [(33, 84)],
 'scripts/lib/stuck.py': [(17, 128)],
 'scripts/cron/l2_driver.py': [(90, 136),
                               (1605, 1629),
                               (1687, 1713),
                               (1724, 1744),
                               (1792, 1828),
                               (1888, 1900),
                               (1936, 1981)],
 'scripts/handlers/stop/reenforce.py': [(83, 119)],
 'scripts/engine/circuit.py': [(111, 137)],
 'ontology/graph-queries.yaml': [(88, 102)],
 'knowledge/golden/cases.yaml': [(45, 51)],
 'scripts/handlers/pre_tool/write_boundary.py': [(639, 725),
                                                 (837, 849),
                                                 (883, 897),
                                                 (954, 979),
                                                 (981, 1102)],
 'scripts/cron/re_anchor.py': [(143, 247)],
 'scripts/lib/suite_floor.py': [(42, 89)],
 'scripts/lib/git_flow.py': [(21, 87)],
 'scripts/engine/skill_router.py': [(210, 239), (317, 343), (377, 397)],
 'scripts/engine/select_ready.py': [(42, 99)],
 'scripts/engine/pipeline_loader.py': [(300, 322), (361, 381), (416, 452)],
 'config/policy/validator-ladder.json': [(45, 51)],
 'config/policy/write-boundary.json': [(1, 59)],
 'agents/planner.md': [(1, 17)],
 '.claude/commands/unattended.md': [(1, 13)],
 'scripts/engine/extractors/python_conceptual.py': [(52, 93)],
 'scripts/engine/extractors/python_flows.py': [(60, 95)],
 'scripts/engine/extractors/python_convention.py': [(32, 72)],
 'scripts/engine/extractors/intent_seed.py': [(53, 66)],
 'scripts/engine/extractors/doc_classifier.py': [(31, 50)],
 'scripts/validators/red_flags_scan.py': [(14, 44)],
 'scripts/lib/external_text.py': [(14, 39)]}
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
    assert partition['scope_sha256'] == SCOPE and partition['bytes'] == 145150
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
    assert len(files) == 9 and sum(row['bytes'] for row in files) == 145150
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
            'Complete sandbox autoheart gates, Guardian authentication and notification relay acknowledgement.',
            'Extractor parser helpers, template/skill content, testgen execution and scenario semantic fidelity.',
            'All shell grammar variants, launch registrations, live approval channels and environment restoration.',
            'Actual deployment triggers, production state and PostgreSQL transition consumers.',
        ],
        'review_ref': f'{REVIEW}#unknowns',
    })
    write('checkpoint.json', {
        'partition': PARTITION, 'source': 'harness', 'revision': REVISION,
        'scope_sha256': SCOPE, 'manifest_sha256': sha256(manifest_raw),
        'partitions_sha256': sha256(partitions_raw),
        'primary_file_count': len(files), 'primary_bytes': 145150,
        'primary_lines': sum(row['lines'] for row in files),
        'primary_full_body_read': True, 'standalone_test_scripts': 9, 'helper_shims': 0,
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
        'primary_count': len(files), 'primary_bytes': 145150,
        'support_count': len(support), 'review_sha256': sha256(review_raw),
        'method': 'Own stdlib metadata recorder only; no source import/execution.',
        'upstream_tests_executed': 0, 'upstream_pass_claimed': False,
    })
    print(json.dumps({'files': len(files), 'bytes': 145150, 'supports': len(support),
                      'missing_manifest_sha': [row['path'] for row in files + support
                                               if row['source'] == 'harness'
                                               and not row['manifest_snapshot_sha256_present']],
                      'review_sha256': sha256(review_raw)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
