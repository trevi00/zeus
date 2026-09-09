"""Own byte-only metadata recorder. Never imports or executes reviewed source."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
REL = OUT.relative_to(ROOT).as_posix()
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
REV = 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2'
PARTITION = 'baldrix:agents:002'
STATUS = 'body_reviewed_call_test_trace_pending'
PLAN = json.loads((OUT / 'read-plan.json').read_text(encoding='utf-8'))
SUPPORT = PLAN['support']
LINKS = {int(k): v for k, v in PLAN['links'].items()}
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
    assert inventory['scope_sha256'] == '7abe8bbacd9eb4ae685a85d2c71b55c3222038547781a6c695f71584d222a218'
    save('inventory.json', inventory)
    prior = load(OUT / 'prior-ledger.json')
    assert {r['row']['path'] for r in prior['rows']} == {r['path'] for r in inventory['paths']}

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
    for i, item in enumerate(inventory['paths'], 1):
        row = meta(item['path'])
        anchor = f'f{i:02}'
        row['test_role'] = 'agent_instruction_document_not_a_test'
        row['denominator_basis'] = 'Full document reading; embedded commands/examples/checklists were not executed.'
        row['source_executed'] = False
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
        old = next(r for r in prior['rows'] if r['row']['path'] == row['path'])
        assert old['row']['revision'] == REV and old['row']['pinned_sha256'] == row['pinned_sha256']
        assert old['row']['git_blob'] == row['git_blob'] and old['row']['bytes'] == row['bytes']
        row['prior_ledger_row_index'] = old['row_index']
        row['prior_ledger_sha256'] = prior['ledger_sha256']
        row['prior_primary_disposition'] = old['row']['disposition']
        rows.append(row)
    assert len(rows) == 10 and sum(r['bytes'] for r in rows) == 169185
    supports = []
    for i, (path, ranges) in enumerate(SUPPORT, 1):
        row = meta(path, ranges)
        row.update({'id': f's{i:02}', 'counted_as_primary': False,
                    'review_ref': f'{REL}/review.md#supporting',
                    'disposition': 'supporting_ranges_reviewed_execution_pending'})
        supports.append(row)
    assert '## supporting\n' in review
    assert not {r['path'] for r in rows} & {s['path'] for s in supports}
    for i, row in enumerate(rows, 1):
        section = review.split(f'## f{i:02}\n', 1)[1].split('\n## ', 1)[0]
        assert Path(row['path']).name in section
        assert set(row['supporting_ids']) <= {s['id'] for s in supports}
    save('files.json', rows)
    save('supporting.json', supports)
    save('remaining.json', {'primary_body_unread': [], 'remaining': REMAINING,
                            'subsystem_complete': False, 'adoption_approved': False})
    save('checkpoint.json', {
        'partition': PARTITION, 'revision': REV,
        'scope_sha256': inventory['scope_sha256'],
        'primary_paths': 10, 'primary_bytes': 169185, 'primary_full_body_read': 10,
        'agent_instruction_documents': 10, 'test_scripts': 0, 'self_check_wrappers': 0, 'tests_collected': 0, 'tests_executed': 0,
        'primary_full_body_reused': 0, 'global_coverage_mutated': False,
        'prior_primary_inventory_basis': 'Captured path-ledger.json rows show all 10 unreviewed; fresh body reading, no semantic report reuse. See prior-ledger.json for exact rows and source hash.',
        'supporting_paths': len(supports),
        'supporting_full_body_read': sum(s['body_read_complete'] for s in supports),
        'supporting_partial_body_read': sum(not s['body_read_complete'] for s in supports),
        'supporting_reused': 0, 'source_execution_count': 0,
        'source_import_probe_network_install_count': 0,
        'live_or_credential_access_count': 0,
        'source_runtime_shared_coverage_changes': 0,
        'subsystem_complete': False, 'adoption_approved': False,
        'actual_claude_review_complete': False, 'license_complete': False,
        'platform_validation_complete': False, 'human_acceptance_complete': False,
        'model_qualification_complete': False,
        'review_sha256': sha((OUT / 'review.md').read_bytes()),
        'files_sha256': sha((OUT / 'files.json').read_bytes()),
        'supporting_sha256': sha((OUT / 'supporting.json').read_bytes()),
        'manifest_sha256': sha((SOURCE / 'manifest.json').read_bytes()),
        'prior_ledger_record_sha256': sha((OUT / 'prior-ledger.json').read_bytes()),
        'remaining': REMAINING,
    })
    for path in OUT.iterdir():
        if path.is_file():
            raw = path.read_bytes()
            raw.decode('utf-8')
            if path.name in {'review.md', 'README.md'}:
                assert raw.isascii() and bytes([63, 63]) not in raw, path
            assert b'\r' not in raw and not raw.startswith(b'\xef\xbb\xbf'), path
            if path.suffix == '.json':
                load(path)
    print(json.dumps({'metadata': 'PASS', 'primary': len(rows),
                      'supporting': len(supports), 'upstream_execution': 0}))


if __name__ == '__main__':
    main()
