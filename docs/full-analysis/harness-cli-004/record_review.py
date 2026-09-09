"""Generate review metadata only; never import or execute upstream sources."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = ROOT / '.runtime/absorption/sources/harness'
PINNED = SOURCE / 'pinned'
REVISION = 'a3f8b3be9a0a389329de6e16a6c7db81782041a3'
PARTITION = 'harness:scripts/cli:004'
SCOPE = '692447cf6d9292349ec60a99ce69a42f452db063a58e5b16d51c8afb7fe1696b'
REVIEW = 'docs/full-analysis/harness-cli-004/review.md'

PRIMARY = {
    'spiral': ('S04', 679, 'Candidate ranking, proposal, signed approval and freshness surfaces.',
               ['scripts/lib/arming.py', 'scripts/lib/backlog.py',
                'scripts/lib/approval_proof.py', 'scripts/lib/evidence_freshness.py',
                'scripts/cron/l2_driver.py', 'config/policy/arming-rules.json',
                'config/policy/backlog-weights.json'],
               ['tests/integration/test_backlog_smoke.py']),
    'status': ('S06', 163, 'Ledger state and unbound global operational status projection.',
               ['scripts/engine/select_ready.py', 'scripts/engine/tick.py',
                'scripts/lib/decomposition.py'], []),
    'step': ('S03', 511, 'Dispatch/delegation records, wave guidance and gate command contract.',
             ['scripts/lib/decomposition.py', 'scripts/engine/select_ready.py',
              'scripts/engine/tick.py', 'scripts/engine/gate_runner.py',
              'scripts/handlers/stop/subagent_harvest.py', 'scripts/handlers/registry.py'],
             ['tests/integration/test_decomposition_smoke.py',
              'tests/contract/test_domain_lead_delivery_contract.py']),
    'suite': ('S05', 624, 'Script execution and textual verdict denominator/baseline/recheck.',
              ['scripts/lib/test_outcome.py', 'scripts/cli/autoheart_cmd.py',
               'pipelines/harness-selfimprove.yaml'],
              ['tests/contract/test_suite_runner_smoke.py',
               'tests/integration/test_small_batch_smoke.py']),
    'testgen': ('S01', 49, 'GWT extraction issues non-strict xfail skeletons, not acceptance.',
                ['scripts/engine/testgen.py', 'scripts/cli/suite_cmd.py'], []),
    'workup': ('S02', 54, 'Scaffold issuance and machine-block/document consistency check.',
               ['scripts/engine/workup.py'], ['tests/unit/test_workup_smoke.py']),
}

SUPPORT = {
    'scripts/engine/testgen.py': [(1, 70)],
    'scripts/engine/workup.py': [(15, 225)],
    'scripts/lib/test_outcome.py': [(45, 85), (90, 111), (179, 253), (303, 345)],
    'scripts/lib/approval_proof.py': [(64, 136)],
    'scripts/lib/backlog.py': [(46, 105), (206, 238)],
    'scripts/lib/arming.py': [(348, 442), (577, 730)],
    'scripts/cron/l2_driver.py': [(1216, 1252)],
    'scripts/engine/select_ready.py': [(23, 99)],
    'scripts/lib/decomposition.py': [(45, 188)],
    'scripts/engine/gate_runner.py': [(28, 51), (100, 123)],
    'scripts/cli/autoheart_cmd.py': [(129, 151), (438, 480), (645, 665), (678, 725)],
    'pipelines/harness-selfimprove.yaml': [(91, 106), (183, 265)],
    'tests/unit/test_workup_smoke.py': [(29, 70)],
    'tests/contract/test_suite_runner_smoke.py': [(50, 107), (213, 242), (255, 282)],
    'tests/integration/test_small_batch_smoke.py': [(738, 754)],
    'tests/integration/test_backlog_smoke.py': [(148, 179)],
    'tests/integration/test_decomposition_smoke.py': [(39, 110)],
    'scripts/engine/tick.py': [(112, 133), (327, 350)],
    'scripts/lib/evidence_freshness.py': [(141, 226)],
    'tests/contract/test_domain_lead_delivery_contract.py': [(65, 113)],
    'scripts/handlers/stop/subagent_harvest.py': [(58, 154)],
    'config/policy/arming-rules.json': [(37, 70)],
    'config/policy/backlog-weights.json': [(1, 9)],
    'scripts/handlers/registry.py': [(1, 35), (74, 85)],
}
ZEUS = {
    'src/codex_harness/domain/sdd.py': [(8, 22), (169, 202)],
    'src/codex_harness/domain/model_routing.py': [(24, 39)],
    'src/codex_harness/application/sdd.py': [(159, 184)],
}


def digest(raw: bytes) -> str:
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
    assert partition['scope_sha256'] == SCOPE
    assert partition['bytes'] == 114624
    expected = [f'scripts/cli/{name}_cmd.py' for name in PRIMARY]
    assert partition['paths'] == [{'source': 'harness', 'path': p} for p in expected]

    def source_row(path: str, ranges: list[tuple[int, int]]) -> dict:
        raw = (PINNED / path).read_bytes()
        item = inventory[path]
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        sha = digest(raw)
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
            'line_ranges': ranges, 'review_ref': REVIEW, 'tests_executed': [],
        }

    files = []
    for name, (section, lines, summary, trace, tests) in PRIMARY.items():
        row = source_row(f'scripts/cli/{name}_cmd.py', [(1, lines)])
        assert row['lines'] == lines
        row.update({
            'partition': PARTITION, 'disposition': 'semantically_reviewed',
            'read_extent': 'full_body', 'semantic_summary': summary,
            'finding_sections': [section, 'Z01'], 'caller_or_dependency_trace': trace,
            'tests_read_in_part': tests,
            'test_limits': 'Selected test bodies read only; no upstream execution.',
            'remaining': ['Full transitive closure', 'Runtime reproduction',
                          'Independent Claude review', 'Adoption decision'],
            'adoption_status': 'not_approved_not_incorporated',
        })
        files.append(row)
    assert len(files) == 6 and sum(row['bytes'] for row in files) == 114624
    support = []
    for path, ranges in SUPPORT.items():
        row = source_row(path, ranges)
        row.update({'read_extent': 'listed_line_ranges_only',
                    'counted_in_partition_coverage': False})
        support.append(row)
    for path, ranges in ZEUS.items():
        raw = (ROOT / path).read_bytes()
        lines = len(raw.decode('utf-8').splitlines())
        assert all(1 <= a <= b <= lines for a, b in ranges)
        support.append({
            'source': 'zeus', 'path': path,
            'revision': 'working_tree_not_source_manifest', 'sha256': digest(raw),
            'bytes': len(raw), 'lines': lines, 'line_ranges': ranges,
            'read_extent': 'listed_line_ranges_only', 'review_ref': REVIEW,
            'counted_in_partition_coverage': False, 'tests_executed': [],
        })
    write('files.json', files)
    write('supporting-evidence.json', support)
    write('checkpoint.json', {
        'partition': PARTITION, 'source': 'harness', 'revision': REVISION,
        'scope_sha256': SCOPE, 'manifest_sha256': digest(manifest_raw),
        'partitions_sha256': digest(partitions_raw), 'primary_file_count': len(files),
        'primary_bytes': sum(row['bytes'] for row in files),
        'primary_full_body_read': True, 'support_harness_count': len(SUPPORT),
        'support_zeus_count': len(ZEUS), 'support_is_partial_not_primary_coverage': True,
        'manifest_snapshot_sha256_missing': [row['path'] for row in files + support
                                            if row['source'] == 'harness'
                                            and not row['manifest_snapshot_sha256_present']],
        'status': 'static_review_complete_execution_and_independent_review_pending',
        'upstream_execution_count': 0, 'tests_executed': [], 'model_invocation_count': 0,
        'source_instructions_inherited': False, 'blocked_probe_retried_or_bypassed': False,
        'source_modified': False, 'runtime_modified': False, 'shared_coverage_modified': False,
        'commit_or_push_performed': False, 'full_analysis_complete': False,
        'subsystem_complete': False, 'adoption_approved': False, 'acceptance_complete': False,
        'claude_cross_review': 'root_managed_pending',
        'device_farm_and_samsung_execution': 'deferred_not_implemented_or_verified',
        'missing_path_observations': ['config/policy/evidence-freshness.json'],
        'remaining': ['Full caller/config/test closure', 'Actual environment verification',
                      'Concurrent state and authorization reproduction',
                      'Human scenario and production evidence', 'Independent review/adoption'],
    })
    print(json.dumps({'primary_files': len(files), 'primary_bytes': 114624,
                      'support_files': len(support), 'upstream_executions': 0}))


if __name__ == '__main__':
    main()
