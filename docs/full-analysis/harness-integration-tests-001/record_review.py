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
PARTITION = 'harness:tests/integration:001'
SCOPE = '89b74e56c0d68e88149e1d4cb03ee1d8bbeb9d5ba27bf370ac0cc80c2d850a30'
REVIEW = 'docs/full-analysis/harness-integration-tests-001/review.md'

PRIMARY = {
    '_isolate': (20, 't01', 'Dynamic reexport shim, not an executable test suite.',
                 ['tests/_isolate.py', 'scripts/cli/suite_cmd.py']),
    'test_approval_proof_smoke': (149, 't02', 'Real HMAC and match functions over synthetic approvals and isolated key/ledger.',
                                  ['scripts/lib/approval_proof.py', 'scripts/lib/arming.py', 'scripts/lib/ledger.py']),
    'test_arm_silence_smoke': (308, 't03', 'Real arming failure branches and delta notification queue, fake guardian assets.',
                               ['scripts/cron/l2_driver.py', 'scripts/lib/approval_proof.py']),
    'test_arming_smoke': (169, 't04', 'Arm CLI binding precedence and hook stamp branches; lexical guard ordering.',
                          ['scripts/cli/run_cmd.py', 'scripts/handlers/prompt/seeding.py', 'scripts/handlers/stop/reenforce.py']),
    'test_arming_wiring_smoke': (779, 't05', 'Rule contract checks with stub grade/freshness and fixture subprocess arm flow.',
                                 ['scripts/lib/arming.py', 'scripts/cron/l2_driver.py', 'scripts/lib/approval_proof.py', 'scripts/cli/spiral_cmd.py']),
    'test_autodisarm_smoke': (301, 't06', 'Injected completion/failure ledger and real disarm; weak preservation oracle.',
                              ['scripts/cron/l2_driver.py', 'scripts/cli/run_cmd.py', 'scripts/lib/derive_state.py', 'scripts/lib/ledger.py']),
    'test_autoheart_smoke': (1121, 't07', 'Stubbed gate stack with selected real Git fixture operations and disposition oracles.',
                             ['scripts/cli/autoheart_cmd.py', 'scripts/engine/sandbox.py', 'scripts/cron/l2_driver.py', 'scripts/cli/suite_cmd.py']),
    'test_backlog_smoke': (371, 't08', 'Synthetic candidates plus real fixture CLI and pinned historical proposal corpus shape.',
                           ['scripts/lib/backlog.py', 'scripts/cli/spiral_cmd.py', 'scripts/lib/ledger.py']),
    'test_capture_smoke': (222, 't09', 'Synthetic event folding and isolated capture-to-ledger-to-candidate CLI flow.',
                           ['scripts/lib/backlog.py', 'scripts/cli/capture_cmd.py', 'scripts/cli/spiral_cmd.py', 'config/policy/backlog-weights.json']),
    'test_chat_smoke': (155, 't10', 'Three synthetic Markdown artifacts drive actual machine gates; ontology writes outside state.',
                        ['pipelines/chat.yaml', 'scripts/engine/gate_runner.py', 'scripts/engine/checks.py', 'scripts/engine/ontology_index.py', 'scripts/handlers/prompt/seeding.py']),
}

# Exact inclusive ranges displayed and read in this review, including rereads
# of portions truncated by tool output. No prior review coverage is reused.
SUPPORT = {
    'tests/_isolate.py': [(1, 107), (164, 229), (388, 402)],
    'scripts/lib/approval_proof.py': [(50, 136)],
    'scripts/lib/paths.py': [(20, 105)],
    'scripts/cli/suite_cmd.py': [(65, 169), (254, 277), (341, 465), (605, 624)],
    'scripts/lib/test_outcome.py': [(65, 105), (189, 252)],
    'scripts/cli/autoheart_cmd.py': [(129, 151), (575, 670), (1076, 1133), (1198, 1304)],
    'scripts/engine/sandbox.py': [(172, 252), (459, 535)],
    'scripts/cron/l2_driver.py': [(114, 136), (598, 715), (1135, 1347), (1605, 1755)],
    'scripts/lib/arming.py': [(348, 421), (641, 765)],
    'scripts/cli/run_cmd.py': [(27, 253)],
    'scripts/handlers/stop/reenforce.py': [(29, 80)],
    'scripts/handlers/prompt/seeding.py': [(40, 99)],
    'scripts/cli/spiral_cmd.py': [(37, 177), (503, 679)],
    'scripts/cli/capture_cmd.py': [(50, 158)],
    'scripts/lib/backlog.py': [(81, 238)],
    'scripts/engine/ontology_index.py': [(95, 113), (253, 288)],
    'scripts/engine/gate_runner.py': [(28, 179)],
    'pipelines/chat.yaml': [(1, 54)],
    'scripts/engine/checks.py': [(91, 146)],
    'config/paths.yaml': [(1, 32)],
    'config/policy/backlog-weights.json': [(1, 9)],
    'scripts/lib/ledger.py': [(132, 169), (243, 320), (350, 387)],
    'scripts/lib/derive_state.py': [(182, 225)],
}
ZEUS = {
    'AGENTS.md': [(1, 17)],
    'src/codex_harness/domain/sdd.py': [(8, 22), (169, 202)],
    'src/codex_harness/application/sdd.py': [(159, 184)],
    'src/codex_harness/domain/model_routing.py': [(24, 39)],
}
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
    assert partition['scope_sha256'] == SCOPE and partition['bytes'] == 193748
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
            'declared_entrypoint': None if name == '_isolate' else '__main__ calls main; nonzero when FAILS nonempty',
            'denominator_basis': 'Full source body; emitted checks are conditional/dynamic and not executed.',
            'tests_read_in_part': [f'tests/integration/{name}.py'] if name != '_isolate' else [],
            'test_limits': 'Static oracle/fixture/caller analysis only; asserts are not PASS or human acceptance.',
            'remaining': REMAINING,
            'adoption_status': 'not_approved_not_incorporated',
        })
        files.append(row)
    assert len(files) == 10 and sum(row['bytes'] for row in files) == 193748
    support = []
    for path, ranges in SUPPORT.items():
        row = source_row(path, ranges, 'trace')
        row.update({'read_extent': 'listed_line_ranges_only', 'counted_in_partition_coverage': False})
        support.append(row)
    for path, ranges in ZEUS.items():
        raw = (ROOT / path).read_bytes()
        lines = len(raw.decode('utf-8').splitlines())
        assert all(1 <= a <= b <= lines for a, b in ranges)
        support.append({
            'source': 'zeus', 'path': path, 'revision': 'working_tree_not_source_manifest',
            'sha256': sha256(raw), 'bytes': len(raw), 'lines': lines, 'line_ranges': ranges,
            'read_extent': 'listed_line_ranges_only', 'review_ref': f'{REVIEW}#zeus',
            'read_basis': 'displayed_and_read_current_review', 'previous_review_reuse': None,
            'counted_in_partition_coverage': False, 'tests_executed': [],
        })
    write('files.json', files)
    write('supporting-evidence.json', support)
    write('remaining.json', {
        'partition': PARTITION, 'primary_body_remaining': [],
        'remaining': REMAINING,
        'specific_partial_traces': [
            'Lease internals; all hung-session/circuit/spawn/token runtime branches.',
            'Full write_boundary/sandbox classification and shipped arming policy closure.',
            'Ontology schema validators, tick/select_ready and step dispatch transitive closure.',
            'Incident CLI, completion assessment, actual proposal corpus bodies and historical snapshot equality.',
            'Compaction/snapshot/sidecar equivalence and GitHub issue synchronization.',
        ],
        'review_ref': f'{REVIEW}#unknowns',
    })
    write('checkpoint.json', {
        'partition': PARTITION, 'source': 'harness', 'revision': REVISION,
        'scope_sha256': SCOPE, 'manifest_sha256': sha256(manifest_raw),
        'partitions_sha256': sha256(partitions_raw),
        'primary_file_count': len(files), 'primary_bytes': 193748,
        'primary_lines': sum(row['lines'] for row in files),
        'primary_full_body_read': True, 'standalone_test_scripts': 9, 'helper_shims': 1,
        'support_harness_count': len(SUPPORT), 'support_zeus_count': len(ZEUS),
        'support_is_partial_not_primary_coverage': True, 'prior_support_reuse_count': 0,
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
        'primary_count': len(files), 'primary_bytes': 193748,
        'support_count': len(support), 'review_sha256': sha256(review_raw),
        'method': 'Own stdlib metadata recorder only; no source import/execution.',
        'upstream_tests_executed': 0, 'upstream_pass_claimed': False,
    })
    print(json.dumps({'files': len(files), 'bytes': 193748, 'supports': len(support),
                      'missing_manifest_sha': [row['path'] for row in files + support
                                               if row['source'] == 'harness'
                                               and not row['manifest_snapshot_sha256_present']],
                      'review_sha256': sha256(review_raw)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
