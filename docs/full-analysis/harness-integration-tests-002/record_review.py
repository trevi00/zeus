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
PARTITION = 'harness:tests/integration:002'
SCOPE = '31cb8f035753cb90eb859a127d72fc32c3a0a8cd725a58ba6ccbb484535b2e8b'
REVIEW = 'docs/full-analysis/harness-integration-tests-002/review.md'

PRIMARY = {
    'test_cli_smoke': (169, 'i01', 'Real fixture CLI-hook-tick chain with synthetic operator approval.', ['scripts/cli/run_cmd.py', 'scripts/cli/residual_cmd.py', 'scripts/engine/gate_runner.py']),
    'test_cli_wrappers_smoke': (120, 'i02', 'Mixed fake and actual HOME CLI wrappers; ontology writes and potential real PG endpoint.', ['scripts/cli/ontology_cmd.py', 'scripts/engine/ontology_index.py', 'scripts/cli/fleet_status_cmd.py', 'scripts/engine/projection_pg.py']),
    'test_closedloop_smoke': (154, 'i03', 'Synthetic resolved ledger, real digest landing, stubbed background spawn.', ['scripts/handlers/stop/reflector_fork.py', 'scripts/engine/curator.py']),
    'test_context_programming_smoke': (182, 'i04', 'Lexical instruction checks and synthetic plus live Git cohesion signals.', ['scripts/engine/cohesion.py']),
    'test_curator_smoke': (350, 'i05', 'Fixture lesson lifecycle and same-evidence promotion; generic PASS repair harvest.', ['scripts/engine/curator.py']),
    'test_cycle_approval_smoke': (112, 'i06', 'Synthetic single-statement human approval across stage restart events.', ['scripts/engine/gate_runner.py', 'scripts/lib/derive_state.py']),
    'test_debate_smoke': (242, 'i07', 'Synthetic actor convergence, decision card and tick cap contracts.', ['scripts/engine/debate.py']),
    'test_decomposition_smoke': (202, 'i08', 'Plan and transcript fixtures; shard-only harvest attribution.', ['scripts/lib/decomposition.py', 'scripts/handlers/stop/subagent_harvest.py']),
    'test_dispatch_smoke': (335, 'i09', 'Actual fixture dispatch over inert command strings, conditional Bash launcher.', ['scripts/cli/suite_cmd.py', 'scripts/lib/test_outcome.py']),
    'test_endpoint_graph_smoke': (179, 'i10', 'Static JSON/table contract fixtures and real CLI atlas queries.', ['scripts/engine/endpoint_graph.py']),
    'test_engine_smoke': (500, 'i11', 'Loader contracts and actual file-gate/tick fixtures; synthetic human/render and budget events.', ['scripts/engine/gate_runner.py', 'scripts/engine/tick.py']),
    'test_evolve_smoke': (167, 'i12', 'Signature stability and caller executed boolean, no real executor receipt.', ['scripts/engine/evolve.py']),
    'test_fleet_smoke': (212, 'i13', 'Conditional real Kafka and PG integration with partial external cleanup.', ['scripts/cron/bus_tailer.py', 'scripts/engine/projection_pg.py', 'scripts/lib/profile.py']),
    'test_gate_active_smoke': (135, 'i14', 'Real gate spy and synthetic activity/status marker, not lock proof.', ['scripts/engine/gate_runner.py']),
    'test_gate_ratchet_smoke': (153, 'i15', 'Statement removal and waiver fixture; weaker not-same-blocker oracle.', ['scripts/engine/gate_ratchet.py', 'scripts/engine/tick.py']),
    'test_governance_mining_smoke': (145, 'i16', 'Completion path existence, scope heuristics, lexical routing assertions.', ['scripts/lib/completion_line.py', 'scripts/lib/decomposition.py']),
    'test_health_smoke': (312, 'i17', 'Live tree, fixture mutations, conditional spawn and Git backlog canaries.', ['scripts/validators/settings_wiring.py', 'scripts/cli/hook_latency_probe.py', 'scripts/cli/health_cmd.py']),
}

SUPPORT = {
    'scripts/engine/curator.py': [(86, 174), (241, 289)],
    'scripts/engine/evolve.py': [(185, 263)],
    'scripts/engine/gate_ratchet.py': [(24, 62)],
    'scripts/lib/decomposition.py': [(89, 138), (161, 188)],
    'scripts/cron/bus_tailer.py': [(1, 136)],
    'scripts/engine/projection_pg.py': [(1, 67)],
    'scripts/handlers/stop/reflector_fork.py': [(32, 98)],
    'scripts/handlers/stop/subagent_harvest.py': [(1, 150)],
    'scripts/engine/debate.py': [(64, 175)],
    'scripts/engine/endpoint_graph.py': [(24, 94), (112, 168)],
    'scripts/lib/completion_line.py': [(29, 87)],
    'scripts/engine/cohesion.py': [(63, 125)],
    'scripts/cli/fleet_status_cmd.py': [(1, 100), (152, 192)],
    'scripts/lib/profile.py': [(1, 24)],
    'scripts/cli/residual_cmd.py': [(43, 132)],
    'scripts/validators/settings_wiring.py': [(132, 161), (232, 280)],
    'scripts/cli/hook_latency_probe.py': [(43, 86)],
    'scripts/cli/health_cmd.py': [(411, 536), (739, 787)],
    'scripts/cli/ontology_cmd.py': [(30, 78)],
    'scripts/engine/tick.py': [(60, 100)],
}
PRIOR_DIR = ROOT / 'docs/full-analysis/harness-integration-tests-001'
REUSE_PATHS = {
    'tests/_isolate.py', 'scripts/lib/paths.py', 'scripts/cli/suite_cmd.py',
    'scripts/lib/test_outcome.py', 'scripts/engine/gate_runner.py',
    'scripts/cli/run_cmd.py', 'scripts/handlers/stop/reenforce.py',
    'scripts/handlers/prompt/seeding.py', 'scripts/engine/ontology_index.py',
    'config/paths.yaml', 'scripts/lib/ledger.py', 'scripts/lib/derive_state.py',
}
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
    assert partition['scope_sha256'] == SCOPE and partition['bytes'] == 190937
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
            'declared_entrypoint': '__main__ UTF-8 wrapper; FAILS-based result; fleet also has conditional whole-suite SKIP',
            'denominator_basis': 'Full source body; emitted checks are conditional/dynamic and not executed.',
            'tests_read_in_part': [f'tests/integration/{name}.py'] if name != '_isolate' else [],
            'test_limits': 'Static oracle/fixture/caller analysis only; asserts are not PASS or human acceptance.',
            'remaining': REMAINING,
            'adoption_status': 'not_approved_not_incorporated',
        })
        files.append(row)
    assert len(files) == 17 and sum(row['bytes'] for row in files) == 190937
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
            'Dispatch write_boundary and complete handler registry, actual shell commands and OS matrix.',
            'Curator provenance, reflection and asset gate full closure; independent repair receipts.',
            'Lease concurrency, debate actor authentication, compaction byte equivalence.',
            'Fleet endpoint identity, external cleanup, no network execution in this review.',
            'Loader/lex/catalog/seams, ontology validator, health safety sections and all fixture configuration bodies.',
            'Authenticated multi-statement approval binding, model qualification and GitHub issue synchronization.',
        ],
        'review_ref': f'{REVIEW}#unknowns',
    })
    write('checkpoint.json', {
        'partition': PARTITION, 'source': 'harness', 'revision': REVISION,
        'scope_sha256': SCOPE, 'manifest_sha256': sha256(manifest_raw),
        'partitions_sha256': sha256(partitions_raw),
        'primary_file_count': len(files), 'primary_bytes': 190937,
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
        'primary_count': len(files), 'primary_bytes': 190937,
        'support_count': len(support), 'review_sha256': sha256(review_raw),
        'method': 'Own stdlib metadata recorder only; no source import/execution.',
        'upstream_tests_executed': 0, 'upstream_pass_claimed': False,
    })
    print(json.dumps({'files': len(files), 'bytes': 190937, 'supports': len(support),
                      'missing_manifest_sha': [row['path'] for row in files + support
                                               if row['source'] == 'harness'
                                               and not row['manifest_snapshot_sha256_present']],
                      'review_sha256': sha256(review_raw)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
