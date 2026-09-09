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
PARTITION = 'harness:tests/integration:003'
SCOPE = '51d4cd6654e2e1495efc91c1345cf502016664656a0f5a6f2866017611672c25'
REVIEW = 'docs/full-analysis/harness-integration-tests-003/review.md'

PRIMARY = {'test_heart_guard_smoke': (675,
                            'i01',
                            'Dispatch and repair fixtures with inert attack strings; probe lacks '
                            'allowed-read oracle.',
                            ['scripts/handlers/dispatch.py',
                             'scripts/handlers/guard_boot.py',
                             'scripts/handlers/post_tool/heart_selfcheck.py',
                             'scripts/handlers/pre_tool/write_boundary.py']),
 'test_hook_journal_smoke': (257,
                             'i02',
                             'Fixture journal and approval inference, expiry not proven against concurrent '
                             'append.',
                             ['scripts/lib/hook_journal.py', 'scripts/handlers/stop/prompt_rollup.py']),
 'test_hud_smoke': (202,
                    'i03',
                    'Synthetic HUD and conditional actual Bash launcher after state env is removed.',
                    ['scripts/cli/hud.py', 'scripts/handlers/hud_launcher.sh']),
 'test_integrity_smoke': (147,
                          'i04',
                          'Ledger poison fixtures; optional adjacent Guardian subprocess not pinned by '
                          'harness.',
                          ['scripts/validators/ledger_semantics.py', 'scripts/lib/ledger.py']),
 'test_invariants_binding_smoke': (483,
                                   'i05',
                                   'Lexical bindings and debt budgets; missing design skips fixture '
                                   'branches.',
                                   ['scripts/cli/invariants_cmd.py']),
 'test_jury_quorum_smoke': (308,
                            'i06',
                            'Fake providers, caller gate claims and quorum denominator; actual model calls '
                            'absent.',
                            ['scripts/cli/judge_cmd.py',
                             'scripts/lib/evaluator.py',
                             'scripts/lib/codex_provider.py']),
 'test_khaness_remine2_smoke': (134,
                                'i07',
                                'Heuristic reproduction class and environment depth fixtures, no replayed '
                                'task.',
                                ['scripts/lib/repro_probe.py',
                                 'scripts/engine/curator.py',
                                 'scripts/lib/agent_depth.py',
                                 'scripts/handlers/pre_tool/agent_depth_guard.py']),
 'test_l2_driver_smoke': (403,
                          'i08',
                          'Stub generator but real maintenance entrypoints and actual child process if '
                          'executed.',
                          ['scripts/cron/l2_driver.py', 'scripts/cron/role_supervisor.py']),
 'test_ladder_probe_smoke': (97,
                             'i09',
                             'Conditional external watchdog with alert-text oracle and partial marker '
                             'validity.',
                             ['scripts/engine/ladder_probe.py']),
 'test_ladder_smoke': (201,
                       'i10',
                       'Boolean fake canary misses tuple contract of actual default golden gate.',
                       ['scripts/engine/pr4.py',
                        'scripts/engine/golden.py',
                        'scripts/cli/ladder_cmd.py',
                        'config/policy/validator-ladder.json']),
 'test_latency_budget_smoke': (198,
                               'i11',
                               'Cache-only budgets and early rc0 despite prior FAILS; current suite detects '
                               'bad text.',
                               ['scripts/cli/hook_latency_probe.py',
                                'scripts/lib/test_outcome.py',
                                'scripts/cli/suite_cmd.py']),
 'test_lease_smoke': (204,
                      'i12',
                      'Sequential lease and key dedup fixtures without concurrent external action.',
                      ['scripts/lib/lease.py', 'scripts/lib/idempotency.py']),
 'test_mirror_smoke': (124,
                       'i13',
                       'Static document and path claims; no actual endpoint behavior.',
                       ['scripts/engine/mirror.py', 'scripts/cli/mirror_cmd.py']),
 'test_monitor_readonly_smoke': (221,
                                 'i14',
                                 'Actual local HTTP server if executed, partial identity and real service '
                                 'read paths.',
                                 ['brain/spikes/harness_monitor_server.py', 'brain/spikes/harness_board.py'])}

SUPPORT = {'scripts/handlers/dispatch.py': [(160, 234)],
 'scripts/handlers/guard_boot.py': [(43, 81), (138, 188)],
 'scripts/handlers/post_tool/heart_selfcheck.py': [(88, 149)],
 'scripts/lib/hook_journal.py': [(62, 258)],
 'scripts/handlers/stop/prompt_rollup.py': [(94, 187)],
 'scripts/lib/repro_probe.py': [(54, 105)],
 'scripts/engine/curator.py': [(189, 240)],
 'scripts/lib/lease.py': [(43, 144)],
 'scripts/lib/idempotency.py': [(1, 39)],
 'scripts/engine/pr4.py': [(1, 208)],
 'scripts/engine/golden.py': [(1, 76)],
 'scripts/engine/mirror.py': [(40, 147)],
 'scripts/validators/ledger_semantics.py': [(35, 139)],
 'scripts/engine/ladder_probe.py': [(39, 182)],
 'scripts/cli/judge_cmd.py': [(149, 185), (202, 380)],
 'scripts/lib/evaluator.py': [(354, 366), (384, 430), (454, 530)],
 'scripts/lib/codex_provider.py': [(217, 220), (380, 421)],
 'scripts/cli/invariants_cmd.py': [(150, 230), (265, 355)],
 'scripts/cron/l2_driver.py': [(137, 184),
                               (893, 952),
                               (1135, 1228),
                               (1230, 1268),
                               (1300, 1347),
                               (1420, 1464),
                               (1790, 1835),
                               (1920, 1983)],
 'brain/spikes/harness_monitor_server.py': [(45, 88),
                                            (237, 295),
                                            (317, 362),
                                            (375, 463),
                                            (757, 795)],
 'scripts/cli/hud.py': [(153, 285), (316, 334), (372, 416)],
 'scripts/lib/agent_depth.py': [(24, 49)],
 'scripts/handlers/pre_tool/agent_depth_guard.py': [(21, 33)],
 'scripts/cron/role_supervisor.py': [(182, 248)],
 'scripts/cli/ladder_cmd.py': [(25, 123)],
 'scripts/cli/mirror_cmd.py': [(22, 63)],
 'brain/spikes/harness_board.py': [(58, 85), (148, 176), (242, 295), (346, 366)],
 'scripts/handlers/pre_tool/write_boundary.py': [(570, 637), (981, 1098)],
 'scripts/cli/hook_latency_probe.py': [(87, 129)],
 'scripts/handlers/hud_launcher.sh': [(1, 12)],
 'config/policy/validator-ladder.json': [(1, 66)]}
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
    assert partition['scope_sha256'] == SCOPE and partition['bytes'] == 194529
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
    assert len(files) == 14 and sum(row['bytes'] for row in files) == 194529
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
            'All dispatcher handlers, restore correctness, real notification delivery and allowed-read canary.',
            'Journal concurrent append versus expiry and authenticated human approval receipts.',
            'Adjacent Guardian watchdog/seal source identity and all service/network effects.',
            'L2 arming prerequisites, maintenance dependencies, process cleanup and OS branches.',
            'Actual default golden case commands, fail-tuple rejection and transactional policy transitions.',
            'Cache source binding, partial SKIP axes, lease concurrency and external action completion.',
            'Monitor GET effects, startup identity, SSE/browser coverage and all collector calls.',
            'Spec claims to real product acceptance, model qualification and GitHub issue synchronization.',
        ],
        'review_ref': f'{REVIEW}#unknowns',
    })
    write('checkpoint.json', {
        'partition': PARTITION, 'source': 'harness', 'revision': REVISION,
        'scope_sha256': SCOPE, 'manifest_sha256': sha256(manifest_raw),
        'partitions_sha256': sha256(partitions_raw),
        'primary_file_count': len(files), 'primary_bytes': 194529,
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
        'primary_count': len(files), 'primary_bytes': 194529,
        'support_count': len(support), 'review_sha256': sha256(review_raw),
        'method': 'Own stdlib metadata recorder only; no source import/execution.',
        'upstream_tests_executed': 0, 'upstream_pass_claimed': False,
    })
    print(json.dumps({'files': len(files), 'bytes': 194529, 'supports': len(support),
                      'missing_manifest_sha': [row['path'] for row in files + support
                                               if row['source'] == 'harness'
                                               and not row['manifest_snapshot_sha256_present']],
                      'review_sha256': sha256(review_raw)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
