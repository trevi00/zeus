"""Own byte-only metadata recorder. Never imports or executes reviewed source."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
REL = OUT.relative_to(ROOT).as_posix()
SOURCE = ROOT / '.runtime/absorption/sources/harness'
REV = 'a3f8b3be9a0a389329de6e16a6c7db81782041a3'
PARTITION = 'harness:tests/contract:001'
STATUS = 'body_reviewed_call_test_trace_pending'
SUPPORT = [
    ('tests/_isolate.py', [[1, 125], [214, 243], [315, 386]]),
    ('scripts/lib/test_outcome.py', [[90, 105], [189, 253]]),
    ('scripts/cli/suite_cmd.py', [[75, 169], [341, 378]]),
    ('scripts/lib/derive_state.py', [[54, 181], [277, 426]]),
    ('scripts/cron/bus_tailer.py', [[1, 136]]),
    ('scripts/cron/l2_driver.py', [[64, 82], [512, 559], [716, 858],
                                 [1180, 1346], [1420, 1464], [1921, 1941]]),
    ('scripts/lib/arming.py', [[422, 848]]),
    ('scripts/cli/arming_cmd.py', [[64, 126]]),
    ('scripts/lib/approval_proof.py', [[64, 136]]),
    ('scripts/lib/evidence_freshness.py', [[141, 226]]),
    ('scripts/engine/pipeline_loader.py', [[78, 117], [292, 330]]),
    ('scripts/engine/ontology_index.py', [[129, 239]]),
    ('ontology/schema.json', [[43, 76]]),
    ('scripts/engine/sandbox.py', [[89, 161]]),
    ('scripts/cli/spiral_cmd.py', [[266, 308]]),
    ('scripts/lib/ledger.py', [[132, 151], [395, 413]]),
    ('brain/spikes/board_publisher.py', [[25, 280]]),
    ('scripts/cli/boundary_corpus_cmd.py', [[47, 137], [176, 269]]),
    ('brain/spikes/harness_board.py', [[148, 192]]),
    ('scripts/cron/research_queue.py', [[60, 73]]),
    ('scripts/cron/youtube_queue.py', [[50, 63]]),
    ('scripts/cron/source_queue.py', [[46, 59]]),
    ('brain/reports/bus-topics-vs-sa3.md', [[1, 156]]),
    ('config/profile.yaml', [[1, 7]]),
    ('config/policy/arming-rules.json', [[1, 110]]),
    ('scripts/handlers/pre_tool/write_boundary.py', [[981, 1045]]),
    ('scripts/engine/select_ready.py', [[42, 78]]),
    ('config/policy/write-boundary.json', [[25, 54], [134, 149]]),
    ('pipelines/harness-selfimprove.yaml', [[66, 103], [123, 175], [244, 274]]),
]
LINKS = {
    1: [1, 2, 3], 2: [1, 2, 3, 4, 16],
    3: [1, 4, 6, 7, 11, 27, 29],
    4: [1, 7, 8, 10, 15, 25], 5: [1, 7, 8, 9, 14, 25],
    6: [2, 3, 11, 12, 13], 7: [1, 17, 19],
    8: [1, 18, 26, 28], 9: [1, 5, 6],
    10: [5, 16, 20, 21, 22, 23, 24], 11: [1, 5, 6, 16, 24],
}
REMAINING = [
    'Only recorded direct ranges reviewed; transitive caller/config/test closure pending.',
    'Upstream execution/import/probe/network/install prohibited: none performed.',
    'Historical PASS, approval statements and synthetic fixtures are not current execution evidence.',
    'Actual Claude joint review, license/dependency closure and model qualification pending.',
    'Windows/Linux/WSL execution and real human experience acceptance pending.',
    'Zeus eight-stage SDD implementation equivalence and adoption approval not established.',
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8', newline='\n')


def main():
    manifest = load(SOURCE / 'manifest.json')
    assert manifest['revision'] == REV
    entries = {r['path']: r for r in manifest['inventory']}
    inventory = next(p for p in load(ROOT / 'docs/full-analysis/partitions.json')
                     if p['partition'] == PARTITION)
    assert inventory['scope_sha256'] == '66bda8a8cf43d1c4928d88d4f6f3cd0eb1eff332b06a501c67a88f087e6abfd4'
    save('inventory.json', inventory)
    review = (OUT / 'review.md').read_text(encoding='utf-8')

    def meta(path, ranges=None):
        raw = (SOURCE / 'pinned' / path).read_bytes()
        lines = len(raw.decode('utf-8').splitlines())
        entry = entries[path]
        digest = sha(raw)
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        expected = entry.get('snapshot_sha256')
        assert blob == entry['object'] and len(raw) == entry['bytes'], path
        assert expected is None or expected == digest, path
        ranges = ranges or [[1, lines]]
        assert all(1 <= a <= b <= lines for a, b in ranges), (path, lines)
        return {
            'source': 'harness', 'path': path, 'revision': REV,
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
    for i, item in enumerate(inventory['paths'], 1):
        row = meta(item['path'])
        anchor = f'f{i:02}'
        assert f'## {anchor}\n' in review
        assert Path(item['path']).name in review
        row.update({
            'partition': PARTITION, 'scope_sha256': inventory['scope_sha256'],
            'disposition': STATUS, 'primary_status': STATUS,
            'review_ref': f'{REL}/review.md#{anchor}',
            'supporting_ids': [f's{n:02}' for n in LINKS[i]],
            'remaining': REMAINING, 'adoption_approved': False,
            'prior_full_body_reused': False,
        })
        rows.append(row)
    assert len(rows) == 11 and sum(r['bytes'] for r in rows) == 195089
    supports = []
    for i, (path, ranges) in enumerate(SUPPORT, 1):
        row = meta(path, ranges)
        row.update({'id': f's{i:02}', 'counted_as_primary': False,
                    'review_ref': f'{REL}/review.md#supporting',
                    'disposition': 'supporting_ranges_reviewed_execution_pending'})
        supports.append(row)
    assert '## supporting\n' in review
    assert not {r['path'] for r in rows} & {s['path'] for s in supports}
    save('files.json', rows)
    save('supporting.json', supports)
    save('remaining.json', {'primary_body_unread': [], 'remaining': REMAINING,
                            'subsystem_complete': False, 'adoption_approved': False})
    save('checkpoint.json', {
        'partition': PARTITION, 'revision': REV,
        'scope_sha256': inventory['scope_sha256'],
        'primary_paths': 11, 'primary_bytes': 195089, 'primary_full_body_read': 11,
        'primary_full_body_reused': 0, 'global_coverage_mutated': False,
        'prior_primary_inventory_basis': 'Immediate child docs/full-analysis/*/files.json metadata scan before review found zero matching primary rows; no prior semantic report reused.',
        'supporting_paths': len(supports),
        'supporting_full_body_read': sum(s['body_read_complete'] for s in supports),
        'supporting_partial_body_read': sum(not s['body_read_complete'] for s in supports),
        'supporting_reused': 0, 'source_execution_count': 0,
        'source_import_probe_network_install_count': 0,
        'source_runtime_shared_coverage_changes': 0,
        'subsystem_complete': False, 'adoption_approved': False,
        'actual_claude_review_complete': False, 'license_complete': False,
        'platform_validation_complete': False, 'human_acceptance_complete': False,
        'model_qualification_complete': False,
        'review_sha256': sha((OUT / 'review.md').read_bytes()),
        'files_sha256': sha((OUT / 'files.json').read_bytes()),
        'supporting_sha256': sha((OUT / 'supporting.json').read_bytes()),
        'manifest_sha256': sha((SOURCE / 'manifest.json').read_bytes()),
        'remaining': REMAINING,
    })
    for path in OUT.iterdir():
        if path.is_file():
            raw = path.read_bytes()
            raw.decode('utf-8')
            assert b'\r' not in raw and not raw.startswith(b'\xef\xbb\xbf'), path
            if path.suffix == '.json':
                load(path)
    print(json.dumps({'metadata': 'PASS', 'primary': len(rows),
                      'supporting': len(supports), 'upstream_execution': 0}))


if __name__ == '__main__':
    main()
