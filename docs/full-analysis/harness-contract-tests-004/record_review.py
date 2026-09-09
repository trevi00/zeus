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
PARTITION = 'harness:tests/contract:004'
SCOPE = 'c07a5070598a209386d714cea07c19bc1ddeb9eea49da61c726ff4b8cf700430'
REVIEW = 'docs/full-analysis/harness-contract-tests-004/review.md'

PRIMARY = {'test_lint_contracts_smoke': (846,
                               'i01',
                               'Synthetic lint canaries, real Git/renderer fixtures and registration '
                               'checks; AST/string detection is partial.',
                               ['scripts/validators/harness_lint.py']),
 'test_note_accumulation_contract': (194,
                                     'i02',
                                     'Synthetic archive identity/revision/index fixture; hash naming '
                                     'and delayed sweep limits.',
                                     ['scripts/cron/note_archive.py', 'scripts/cron/l2_driver.py']),
 'test_ontology_smoke': (388,
                         'i03',
                         'Actual build/validator plan with synthetic records; agent denominator still '
                         'hardcoded at 15.',
                         ['scripts/engine/ontology_index.py',
                          'scripts/validators/ontology_validator.py']),
 'test_ownership_smoke': (232,
                          'i04',
                          'Declared ownership and verifier symbol existence; contract enforcement and '
                          'permissions remain separate.',
                          ['scripts/validators/harness_lint.py']),
 'test_promote_dirty_scope_contract': (159,
                                       'i05',
                                       'Real temporary Git dirty-scope helper test; promote '
                                       'approval/apply not exercised.',
                                       ['scripts/engine/sandbox.py']),
 'test_queue_gating_contract': (151,
                                'i06',
                                'Synthetic queue verdict/cache and optional live axis; unknown verdict '
                                'deliberately allowed.',
                                ['scripts/cron/youtube_queue.py', 'scripts/cron/reachability.py']),
 'test_reachability_contract': (165,
                                'i07',
                                'Synthetic kind/reachable decisions and absent-input probes; real fetch '
                                'and cap execution unverified.',
                                ['scripts/cron/reachability.py']),
 'test_repair_evidence_contract': (169,
                                   'i08',
                                   'Temporary Git output predicate; preexisting parking and declaration '
                                   'lack current-run attribution.',
                                   ['scripts/validators/repair_evidence.py',
                                    'pipelines/harness-selfimprove.yaml']),
 'test_research_collector_contract': (222,
                                      'i09',
                                      'Stubbed fetch/source and fixed markup fixtures; partial success '
                                      'heartbeat and side writes distinguished.',
                                      ['scripts/cron/research_collector.py']),
 'test_research_digest_contract': (247,
                                   'i10',
                                   'Fixed timestamp digest and CLI reader fixtures; partial-corruption '
                                   'mark-read path untested.',
                                   ['scripts/lib/research_digest.py',
                                    'scripts/cli/fleet_status_cmd.py']),
 'test_research_queue_contract': (159,
                                  'i11',
                                  'Synthetic feed batching and path parity; timestamp-free repeated '
                                  'selection and dual write window remain.',
                                  ['scripts/cron/research_queue.py', 'scripts/cron/role_supervisor.py']),
 'test_resident_roles_ledger_contract': (112,
                                         'i12',
                                         'Synthetic role registration key fold; registration is not '
                                         'effective runtime health or acceptance.',
                                         ['scripts/cli/health_cmd.py']),
 'test_role_delivery_contract': (260,
                                 'i13',
                                 'Synthetic spawn/verdict fold plus optional operational claims; '
                                 'delivered is not full completion.',
                                 ['scripts/lib/derive_state.py',
                                  'scripts/cli/health_cmd.py',
                                  'scripts/cron/role_supervisor.py']),
 'test_role_section_contract': (233,
                                'i14',
                                'Synthetic role table and conditional deployment observations; current '
                                'four-column source table exists.',
                                ['brain/spikes/role_section.py', 'config/policy/goal.md'])}

SUPPORT = {'brain/spikes/role_section.py': [(27, 123)],
 'config/policy/goal.md': [(63, 75)],
 'pipelines/harness-selfimprove.yaml': [(158, 180)],
 'scripts/cli/fleet_status_cmd.py': [(45, 151)],
 'scripts/cli/health_cmd.py': [(48, 137), (198, 224), (823, 867)],
 'scripts/cron/l2_driver.py': [(560, 599), (1443, 1458)],
 'scripts/cron/note_archive.py': [(44, 180)],
 'scripts/cron/reachability.py': [(166, 232), (259, 313)],
 'scripts/cron/research_collector.py': [(67, 137), (139, 276)],
 'scripts/cron/research_queue.py': [(70, 149)],
 'scripts/cron/role_supervisor.py': [(97, 139), (182, 251)],
 'scripts/cron/youtube_queue.py': [(105, 203)],
 'scripts/engine/ontology_index.py': [(114, 128), (253, 288)],
 'scripts/engine/sandbox.py': [(447, 535)],
 'scripts/lib/derive_state.py': [(427, 541)],
 'scripts/lib/research_digest.py': [(51, 159)],
 'scripts/validators/harness_lint.py': [(83, 129),
                                        (375, 517),
                                        (601, 632),
                                        (740, 813),
                                        (1031, 1190),
                                        (1321, 1387),
                                        (1389, 1438),
                                        (1566, 1622),
                                        (1829, 1907),
                                        (1933, 2030),
                                        (2050, 2092)],
 'scripts/validators/ontology_validator.py': [(32, 83), (108, 216)],
 'scripts/validators/repair_evidence.py': [(75, 178)]}
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
    assert partition['scope_sha256'] == SCOPE and partition['bytes'] == 187846
    path_ledger_raw = (ROOT / 'docs/full-analysis/path-ledger.json').read_bytes()
    path_rows = {row['path']: row for row in json.loads(path_ledger_raw)
                 if row['source'] == 'harness'}
    for path in expected:
        ledger_row = path_rows[path]
        raw = (PINNED / path).read_bytes()
        assert ledger_row['revision'] == REVISION
        assert ledger_row['pinned_sha256'] == sha256(raw)
        assert ledger_row['git_blob'] == inventory[path]['object']
        assert ledger_row['bytes'] == len(raw)
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
    assert len(files) == 14 and sum(row['bytes'] for row in files) == 187846
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
            'Complete lint helper, schema, graph extractor, Git/approval and deployment transition closure.',
            'Role spawner and live delivery, researcher network behavior and human scenario acceptance.',
            'All OS, path quoting, simultaneous writers, timestamp identities and crash recovery semantics.',
            'Actual deployment triggers, production state and PostgreSQL transition consumers.',
        ],
        'review_ref': f'{REVIEW}#unknowns',
    })
    write('checkpoint.json', {
        'partition': PARTITION, 'source': 'harness', 'revision': REVISION,
        'scope_sha256': SCOPE, 'manifest_sha256': sha256(manifest_raw),
        'partitions_sha256': sha256(partitions_raw),
        'path_ledger_sha256': sha256(path_ledger_raw),
        'path_ledger_scope_and_identity_verified': True,
        'live_state_accessed': False, 'credentials_accessed': False,
        'primary_file_count': len(files), 'primary_bytes': 187846,
        'primary_lines': sum(row['lines'] for row in files),
        'primary_full_body_read': True, 'standalone_test_scripts': 14, 'helper_shims': 0,
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
        'primary_count': len(files), 'primary_bytes': 187846,
        'support_count': len(support), 'review_sha256': sha256(review_raw),
        'method': 'Own stdlib metadata recorder only; no source import/execution.',
        'upstream_tests_executed': 0, 'upstream_pass_claimed': False,
    })
    print(json.dumps({'files': len(files), 'bytes': 187846, 'supports': len(support),
                      'missing_manifest_sha': [row['path'] for row in files + support
                                               if row['source'] == 'harness'
                                               and not row['manifest_snapshot_sha256_present']],
                      'review_sha256': sha256(review_raw)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
