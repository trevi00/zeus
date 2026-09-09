"""Own metadata recorder; reads source bytes without importing reviewed code."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
REL = OUT.relative_to(ROOT).as_posix()
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
REV = 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2'
HEAD = '9471f52d2c25de5c52d6c0525dbf5851e83d9455'
PARTITION = 'baldrix:get-shit-done/workflows:004'
SCOPE = '0bfc544b913ef32112f3353ef9a105cdeca9893a5159724f21f54e10d10396f4'
STATUS = 'body_reviewed_call_test_trace_pending'
REMAINING = [
    'Full transitive caller/config/helper/test closure is pending.',
    'No original execution, import, collection, probe, network, or installation.',
    'Historical PASS and source approval strings are not current execution receipts.',
    'Actual Claude joint review and license/dependency closure are pending.',
    'Windows/Linux/WSL behavior, model qualification, and human acceptance are pending.',
    'Current Zeus implementation equivalence and adoption approval are not established.',
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=True, indent=2) + '\n',
        encoding='utf-8', newline='\n',
    )


def main():
    manifest_path = SOURCE / 'manifest.json'
    manifest = load(manifest_path)
    assert manifest['revision'] == REV
    entries = {row['path']: row for row in manifest['inventory']}
    partition_path = ROOT / 'docs/full-analysis/partitions.json'
    partition = next(row for row in load(partition_path) if row['partition'] == PARTITION)
    assert partition['scope_sha256'] == SCOPE
    assert partition == load(OUT / 'inventory.json')
    prior = load(OUT / 'prior-ledger.json')
    plan = load(OUT / 'read-plan.json')
    review = (OUT / 'review.md').read_text(encoding='utf-8')
    assert {x['row']['path'] for x in prior['rows']} == {x['path'] for x in partition['paths']}

    def meta(path, ranges=None):
        raw = (SOURCE / 'pinned' / path).read_bytes()
        lines = len(raw.decode('utf-8').splitlines())
        digest = sha(raw)
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        entry = entries[path]
        expected = entry.get('snapshot_sha256')
        assert len(raw) == entry['bytes'] and blob == entry['object'], path
        assert expected is None or digest == expected, path
        ranges = ranges or [[1, lines]]
        assert all(1 <= a <= b <= lines for a, b in ranges), (path, ranges, lines)
        assert all(ranges[i][1] < ranges[i + 1][0] for i in range(len(ranges) - 1)), path
        return {
            'source': 'baldrix', 'path': path, 'revision': REV,
            'bytes': len(raw), 'git_blob': blob, 'raw_git_blob_status': 'matched',
            'pinned_sha256': digest, 'observed_sha256': None,
            'manifest_sha256': expected,
            'manifest_sha256_status': 'matched' if expected else 'absent_computed_only',
            'read_ranges': ranges, 'total_lines': lines,
            'body_read_complete': ranges == [[1, lines]],
            'read_basis': 'fresh_pinned_body_read', 'prior_ref': None,
            'tests_executed': [], 'test_limits': REMAINING[1],
        }

    rows = []
    for i, item in enumerate(partition['paths'], 1):
        row = meta(item['path'])
        anchor = f'f{i:02}'
        assert f'## {anchor}\n' in review
        section = review.split(f'## {anchor}\n', 1)[1].split('\n## ', 1)[0]
        assert item['path'] in section
        old = next(x for x in prior['rows'] if x['row']['path'] == item['path'])
        for key in ('revision', 'pinned_sha256', 'git_blob', 'bytes'):
            assert old['row'][key] == row[key], (item['path'], key)
        assert old['row']['disposition'] == 'unreviewed'
        row.update({
            'partition': PARTITION, 'scope_sha256': SCOPE,
            'primary_status': STATUS, 'disposition': STATUS,
            'review_ref': f'{REL}/review.md#{anchor}',
            'semantic_rationale': section.strip(),
            'supporting_ids': [f's{n:02}' for n in plan['links'][str(i)]],
            'test_role': 'workflow_prose_not_an_executable_test',
            'denominator_basis': 'Full primary body reading only; all embedded commands unexecuted.',
            'source_executed': False, 'prior_full_body_reused': False,
            'prior_ledger_row_index': old['row_index'],
            'prior_ledger_sha256': prior['ledger_sha256'],
            'prior_primary_disposition': old['row']['disposition'],
            'prior_ledger_record_ref': f'{REL}/prior-ledger.json',
            'remaining': REMAINING, 'adoption_approved': False,
        })
        rows.append(row)
    assert len(rows) == 18 and sum(row['bytes'] for row in rows) == 190882

    supports = []
    for i, (path, ranges) in enumerate(plan['support'], 1):
        row = meta(path, ranges)
        row.update({
            'id': f's{i:02}', 'counted_as_primary': False,
            'review_ref': f'{REL}/review.md#supporting',
            'disposition': 'supporting_ranges_reviewed_execution_pending',
            'reuse_basis': None,
        })
        if path.endswith('/__tests__/merge-back.test.cjs'):
            row.update({
                'test_scenarios_declared': 13,
                'test_scenarios_collected': 0,
                'test_scenarios_executed': 0,
                'test_basis': 'Fresh full static read; temporary real Git fixture oracles, not executed observations.',
            })
        supports.append(row)
    assert len(supports) == 32
    assert len({row['path'] for row in supports}) == 32
    assert not {row['path'] for row in rows} & {row['path'] for row in supports}
    for row in rows:
        assert set(row['supporting_ids']) <= {s['id'] for s in supports}
    save('files.json', rows)
    save('supporting.json', supports)
    save('remaining.json', {
        'primary_body_unread': [], 'remaining': REMAINING,
        'test_discovery_limits': [
            'The directly cited merge-back.test.cjs was freshly read in full; its 13 scenarios were not collected or run.',
            'All other workflow-specific test discovery and execution remain pending.',
            'Bounded literal searches of new-milestone workflow and skill found no seed/trigger terms; no full consumer closure claimed.',
        ],
        'source_test_bodies_read': 1, 'source_test_scenarios_declared': 13, 'tests_collected': 0, 'tests_executed': 0,
        'subsystem_complete': False, 'adoption_approved': False,
    })
    save('checkpoint.json', {
        'partition': PARTITION, 'revision': REV, 'scope_sha256': SCOPE,
        'zeus_head_observed_at_recording': HEAD,
        'primary_paths': 18, 'primary_bytes': 190882, 'primary_full_body_read': 18,
        'primary_fresh_full_body_read': 18, 'primary_full_body_reused': 0,
        'prior_primary_unreviewed': 18, 'primary_body_unread': [],
        'supporting_records': len(supports),
        'supporting_distinct_paths': len({row['path'] for row in supports}),
        'supporting_full_body_read': sum(row['body_read_complete'] for row in supports),
        'supporting_partial_body_read': sum(not row['body_read_complete'] for row in supports),
        'supporting_reused': 0, 'source_execution_count': 0,
        'source_import_probe_network_install_count': 0,
        'tests_collected': 0, 'tests_executed': 0, 'source_test_bodies_read': 1, 'source_test_scenarios_declared': 13,
        'live_or_credential_access_count': 0,
        'source_runtime_shared_coverage_changes': 0, 'global_coverage_mutated': False,
        'subsystem_complete': False, 'adoption_approved': False,
        'actual_claude_review_complete': False, 'license_complete': False,
        'platform_validation_complete': False, 'human_acceptance_complete': False,
        'model_qualification_complete': False,
        'review_sha256': sha((OUT / 'review.md').read_bytes()),
        'files_sha256': sha((OUT / 'files.json').read_bytes()),
        'supporting_sha256': sha((OUT / 'supporting.json').read_bytes()),
        'manifest_sha256': sha(manifest_path.read_bytes()),
        'partition_inventory_sha256': sha(partition_path.read_bytes()),
        'prior_ledger_record_sha256': sha((OUT / 'prior-ledger.json').read_bytes()),
        'remaining': REMAINING,
    })
    for path in OUT.iterdir():
        if not path.is_file():
            continue
        raw = path.read_bytes()
        text = raw.decode('utf-8')
        assert raw.endswith(b'\n') and not raw.endswith(b'\n\n'), path
        assert b'\r' not in raw and not raw.startswith(b'\xef\xbb\xbf'), path
        assert all(line == line.rstrip() for line in text.splitlines()), path
        if path.name in {'review.md', 'README.md'}:
            assert raw.isascii() and '??' not in text, path
        if path.suffix == '.json':
            load(path)
    print(json.dumps({
        'metadata': 'PASS', 'primary': len(rows), 'primary_bytes': 190882,
        'supporting': len(supports), 'upstream_execution': 0,
    }))


if __name__ == '__main__':
    main()
