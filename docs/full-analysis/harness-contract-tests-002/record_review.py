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
PARTITION = 'harness:tests/contract:002'
SCOPE = 'c37d3a1abd837d3363cb8a505568d945cf99b91d27d0e64e006203ec3863b4e0'
REVIEW = 'docs/full-analysis/harness-contract-tests-002/review.md'

PRIMARY = {'test_code_context_smoke': (104,
                             'i01',
                             'Synthetic module graph and actual lint registration; partial '
                             'import/parser oracles.',
                             ['scripts/lib/code_context.py', 'scripts/validators/harness_lint.py']),
 'test_commit_scope_contract': (127,
                                'i02',
                                'Two pipeline output declarations and prose delivery; no Git '
                                'enforcement.',
                                ['scripts/cron/commit_scope.py', 'scripts/cron/l2_driver.py']),
 'test_consume_gate_contract': (195,
                                'i03',
                                'Synthetic reachability and queued payload; fail-open plus conditional '
                                'operation axis.',
                                ['scripts/cron/consume_gate.py', 'scripts/cron/l2_driver.py']),
 'test_contract_visibility_contract': (179,
                                       'i04',
                                       'AST success-print heuristic differs from executed assertion '
                                       'denominator.',
                                       ['scripts/lib/test_outcome.py']),
 'test_coverage_bootstrap': (95,
                             'i05',
                             'Optional coverage startup on one unit pattern; instrumentation is not '
                             'successful suite acceptance.',
                             ['scripts/cli/coverage_cmd.py']),
 'test_dba_projection_contract': (145,
                                  'i06',
                                  'Fake PG projection; zero-stage heartbeat conditional path is '
                                  'untested.',
                                  ['scripts/cron/dba_projection.py', 'infra/fleet/docker-compose.yml']),
 'test_delegation_cap_attribution_smoke': (144,
                                           'i07',
                                           'Actual delegate event with synthetic binding; cap predicate '
                                           'shadowed in test.',
                                           ['scripts/cli/step_cmd.py', 'scripts/engine/tick.py']),
 'test_disarm_says_what_happened_contract': (159,
                                             'i08',
                                             'Stub stage fold and payload oracle; not pipeline-order or '
                                             'process-stop proof.',
                                             ['scripts/cli/run_cmd.py']),
 'test_domain_lead_delivery_contract': (140,
                                        'i09',
                                        'One current role card and plan fields; not all cards or agent '
                                        'receipt.',
                                        ['scripts/cli/step_cmd.py',
                                         'scripts/cli/roster_cmd.py',
                                         'scripts/lib/decomposition.py']),
 'test_driver_caps_smoke': (98,
                            'i10',
                            'Declared integer limits; no live spawn/budget or provider verification.',
                            ['scripts/cron/l2_driver.py']),
 'test_dropped_print_contract': (482,
                                 'i11',
                                 'Printer and temporary CLI fixture; mutation exceptions and partial '
                                 'denominator limits.',
                                 ['scripts/cli/spiral_cmd.py', 'scripts/cli/arming_cmd.py']),
 'test_entrance_reconfirm_contract': (196,
                                      'i12',
                                      'Real suite fixture but shadowed reconfirm decision; current '
                                      'sandbox defense exists.',
                                      ['scripts/engine/sandbox.py']),
 'test_entrypoint_import': (140,
                            'i13',
                            'Fresh child state import plan; path-set diff not full side-effect '
                            'isolation.',
                            ['tests/_isolate.py']),
 'test_env_seal_smoke': (379,
                         'i14',
                         'Current dual caller sealing; branch four only restores HOME and can remove '
                         'other environment values.',
                         ['scripts/cli/sandbox_cmd.py', 'scripts/cli/autoheart_cmd.py']),
 'test_evidence_freshness_contract': (407,
                                      'i15',
                                      'Date fixtures and conditional live candidates; future dates and '
                                      'missing paths not authentic evidence.',
                                      ['scripts/lib/evidence_freshness.py',
                                       'scripts/cli/spiral_cmd.py']),
 'test_extractor_canary_contract': (280,
                                    'i16',
                                    'Synthetic extraction plus stubbed gate outcomes; current DEFER and '
                                    'SELF_BLIND preserved.',
                                    ['scripts/cli/autoheart_cmd.py',
                                     'scripts/cli/extractor_canary_cmd.py']),
 'test_fleet_contracts_smoke': (299,
                                'i17',
                                'Source strings and optional external repo observations; no '
                                'protocol/device runtime.',
                                ['scripts/engine/fleet_contracts.py']),
 'test_fleet_mount_boundary_contract': (121,
                                        'i18',
                                        'Compose short mount string contract; not effective Docker '
                                        'permissions.',
                                        ['infra/fleet/docker-compose.yml']),
 'test_gate_dump_contract': (219,
                             'i19',
                             'Machine check declarations and counts; current lint flags structured and '
                             'defers derived deficits.',
                             ['scripts/cli/gate_dump_cmd.py', 'scripts/validators/harness_lint.py'])}

SUPPORT = {'infra/fleet/docker-compose.yml': [(1, 231)],
 'scripts/cli/arming_cmd.py': [(1, 160)],
 'scripts/cli/autoheart_cmd.py': [(773, 804), (850, 920), (1377, 1408)],
 'scripts/cli/coverage_cmd.py': [(41, 158)],
 'scripts/cli/extractor_canary_cmd.py': [(191, 267)],
 'scripts/cli/gate_dump_cmd.py': [(88, 178)],
 'scripts/cli/roster_cmd.py': [(44, 81)],
 'scripts/cli/run_cmd.py': [(158, 253)],
 'scripts/cli/sandbox_cmd.py': [(47, 70), (143, 172)],
 'scripts/cli/spiral_cmd.py': [(37, 48), (215, 290), (309, 391), (493, 530), (660, 679)],
 'scripts/cli/step_cmd.py': [(23, 36), (198, 216), (265, 345)],
 'scripts/cron/commit_scope.py': [(58, 127)],
 'scripts/cron/consume_gate.py': [(57, 141)],
 'scripts/cron/dba_projection.py': [(54, 108)],
 'scripts/cron/l2_driver.py': [(893, 978), (1480, 1588), (1748, 1764), (1902, 1934)],
 'scripts/engine/fleet_contracts.py': [(345, 398)],
 'scripts/engine/sandbox.py': [(172, 263), (313, 417)],
 'scripts/engine/tick.py': [(125, 152)],
 'scripts/lib/code_context.py': [(24, 128)],
 'scripts/lib/decomposition.py': [(55, 88)],
 'scripts/lib/evidence_freshness.py': [(96, 127), (141, 226)],
 'scripts/validators/harness_lint.py': [(518, 544), (1661, 1793)]}
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
    expected = [f'tests/contract/{name}.py' for name in PRIMARY]
    assert partition['paths'] == [{'source': 'harness', 'path': p} for p in expected]
    assert partition['scope_sha256'] == SCOPE and partition['bytes'] == 193934
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
        row = source_row(f'tests/contract/{name}.py', [(1, lines)], anchor)
        assert row['lines'] == lines
        row.update({
            'partition': PARTITION, 'disposition': 'semantically_reviewed',
            'read_extent': 'full_body', 'semantic_summary': summary,
            'finding_sections': [anchor, 'trace', 'zeus', 'unknowns'],
            'caller_or_dependency_trace': trace,
            'test_kind': 'helper_shim' if name == '_isolate' else 'standalone_smoke_script',
            'declared_entrypoint': 'Standalone __main__ script; dynamic check denominator; early-return and skip semantics detailed per file',
            'denominator_basis': 'Full source body; emitted checks are conditional/dynamic and not executed.',
            'tests_read_in_part': [f'tests/contract/{name}.py'] if name != '_isolate' else [],
            'test_limits': 'Static oracle/fixture/caller analysis only; asserts are not PASS or human acceptance.',
            'remaining': REMAINING,
            'adoption_status': 'not_approved_not_incorporated',
        })
        files.append(row)
    assert len(files) == 19 and sum(row['bytes'] for row in files) == 193934
    support = []
    for path, ranges in SUPPORT.items():
        row = source_row(path, ranges, 'trace')
        row.update({'read_extent': 'listed_line_ranges_only', 'counted_in_partition_coverage': False})
        support.append(row)
    prior_raw = (PRIOR_DIR / 'supporting-evidence.json').read_bytes()
    prior_rows = json.loads(prior_raw)
    reused = 0
    zeus_count = 0
    for prior_row_index, old in enumerate(prior_rows):
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
                'review_sha256': sha256((ROOT / old['review_ref'].split('#')[0]).read_bytes()),
                'supporting_ledger_row_index_zero_based': prior_row_index,
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
            'Complete sandbox/canary/delegation caller and authenticated approval transition closure.',
            'Fleet extractor parser bodies, actual protocol/device behavior and human scenario semantic fidelity.',
            'All compose and shell semantics, effective mounts, runtime service health and environment restoration.',
            'Actual deployment triggers, production state and PostgreSQL transition consumers.',
        ],
        'review_ref': f'{REVIEW}#unknowns',
    })
    write('checkpoint.json', {
        'partition': PARTITION, 'source': 'harness', 'revision': REVISION,
        'scope_sha256': SCOPE, 'manifest_sha256': sha256(manifest_raw),
        'partitions_sha256': sha256(partitions_raw),
        'primary_file_count': len(files), 'primary_bytes': 193934,
        'primary_lines': sum(row['lines'] for row in files),
        'primary_full_body_read': True, 'standalone_test_scripts': 19, 'helper_shims': 0,
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
        'primary_count': len(files), 'primary_bytes': 193934,
        'support_count': len(support), 'review_sha256': sha256(review_raw),
        'method': 'Own stdlib metadata recorder only; no source import/execution.',
        'upstream_tests_executed': 0, 'upstream_pass_claimed': False,
    })
    print(json.dumps({'files': len(files), 'bytes': 193934, 'supports': len(support),
                      'missing_manifest_sha': [row['path'] for row in files + support
                                               if row['source'] == 'harness'
                                               and not row['manifest_snapshot_sha256_present']],
                      'review_sha256': sha256(review_raw)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
