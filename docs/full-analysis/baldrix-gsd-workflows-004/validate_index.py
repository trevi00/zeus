"""Validate owned review metadata only; never import source code."""

import hashlib
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]


def load(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    primary = load('files.json')
    support = load('supporting.json')
    checkpoint = load('checkpoint.json')
    assert len(primary) == 18
    assert sum(row['bytes'] for row in primary) == 190882
    assert all(row['body_read_complete'] for row in primary)
    assert len(support) == 32
    assert len({row['path'] for row in support}) == 32
    assert not {r['path'] for r in primary} & {r['path'] for r in support}
    assert all(not row['counted_as_primary'] for row in support)
    assert checkpoint['source_execution_count'] == 0
    assert checkpoint['tests_executed'] == 0
    assert checkpoint['source_test_bodies_read'] == 1
    assert checkpoint['source_test_scenarios_declared'] == 13
    assert not checkpoint['adoption_approved']
    assert not checkpoint['subsystem_complete']
    for row in primary + support:
        filename, anchor = row['review_ref'].split('#')
        body = (ROOT / filename).read_text(encoding='utf-8')
        assert re.search(r'^## ' + re.escape(anchor) + r'$', body, re.M)
        assert row['tests_executed'] == []
        assert row['raw_git_blob_status'] == 'matched'
        assert row['read_basis'] == 'fresh_pinned_body_read'
    names = []
    for path in sorted(OUT.iterdir()):
        if not path.is_file() or path.name == 'validation.json':
            continue
        raw = path.read_bytes()
        body = raw.decode('utf-8')
        assert raw.endswith(b'\n') and not raw.endswith(b'\n\n'), path
        assert b'\r' not in raw and not raw.startswith(b'\xef\xbb\xbf'), path
        assert all(line == line.rstrip() for line in body.splitlines()), path
        if path.suffix in {'.md', '.json'}:
            assert '??' not in body, path
        if path.suffix == '.json':
            json.loads(body)
        names.append({'path': path.name, 'sha256': digest(path)})
    result = {
        'status': 'PASS',
        'scope': 'Own metadata, references, raw source identity and text integrity only.',
        'primary': 18,
        'primary_bytes': 190882,
        'supporting_records': 32,
        'supporting_distinct_paths': 32,
        'upstream_executions': 0,
        'source_tests_collected': 0,
        'source_tests_executed': 0,
        'source_test_bodies_read': 1,
        'source_test_scenarios_declared': 13,
        'ruff': 'Own recorder and validator passed check --no-cache.',
        'files': names,
    }
    (OUT / 'validation.json').write_text(
        json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n',
    )
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}))


if __name__ == '__main__':
    main()
