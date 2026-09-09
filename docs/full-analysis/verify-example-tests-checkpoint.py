"""Check bounded review identities and raw receipts; this does not certify adoption."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'docs/full-analysis'
BASE = ROOT / '.runtime/absorption/sources'
FOLDERS = ('baldrix-example-fleet-001', 'baldrix-tests-004', 'baldrix-tests-005', 'harness-unit-tests-001')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    partitions = {r['partition']: r for r in read(REPORT / 'partitions.json')}
    manifests = {}
    primary = supporting = 0
    distinct = set()
    for folder in FOLDERS:
        directory = REPORT / folder
        checkpoint = read(directory / 'checkpoint.json')
        keys = checkpoint.get('partitions') or [checkpoint['partition']]
        expected = {(r['source'], r['path']) for key in keys for r in partitions[key]['paths']}
        records = read(directory / 'files.json')
        assert {(r['source'], r['path']) for r in records} == expected
        assert len(records) == len(expected)
        assert not distinct.intersection(expected)
        distinct.update(expected)
        if len(keys) == 1:
            assert checkpoint['scope_sha256'] == partitions[keys[0]]['scope_sha256']
        if checkpoint.get('review_sha256'):
            assert digest((directory / 'review.md').read_bytes()) == checkpoint['review_sha256']
        for name, expected_hash in checkpoint.get('artifact_sha256', {}).items():
            assert digest((directory / name).read_bytes()) == expected_hash
        for name in ('files.json', 'supporting.json', 'supporting-evidence.json'):
            path = directory / name
            if not path.exists():
                continue
            rows = read(path)
            primary += len(rows) if name == 'files.json' else 0
            supporting += len(rows) if name != 'files.json' else 0
            for row in rows:
                source = row['source']
                if source not in manifests:
                    manifest = read(BASE / source / 'manifest.json')
                    manifests[source] = (manifest['revision'], {r['path']: r for r in manifest['inventory']})
                revision, inventory = manifests[source]
                entry = inventory[row['path']]
                raw = (BASE / source / 'pinned' / row['path']).read_bytes()
                assert row['revision'] == revision
                assert len(raw) == entry['bytes'] == row.get('bytes', row.get('pinned_bytes'))
                assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == entry['object'] == row['git_blob']
                assert digest(raw) == row.get('pinned_sha256', row.get('sha256'))
                lines = raw.splitlines(keepends=True)
                covered = set()
                for span in row.get('read_ranges', row.get('line_ranges', [])):
                    if isinstance(span, dict):
                        start, end = span.get('start_line', span.get('start')), span.get('end_line', span.get('end'))
                        if 'raw_range_sha256' in span:
                            assert digest(b''.join(lines[start - 1:end])) == span['raw_range_sha256']
                    else:
                        start, end = span
                    assert 1 <= start <= end <= len(lines)
                    covered.update(range(start, end + 1))
                if name == 'files.json':
                    assert covered == set(range(1, len(lines) + 1))
                if row.get('review_ref'):
                    assert (ROOT / row['review_ref'].split('#')[0]).is_file()
        artifacts = directory / 'artifact-hashes.json'
        if artifacts.exists():
            for name, expected_hash in read(artifacts).items():
                raw = (directory / name).read_bytes()
                if isinstance(expected_hash, dict):
                    assert len(raw) == expected_hash['bytes']
                    expected_hash = expected_hash['sha256']
                assert digest(raw) == expected_hash
    assert primary == len(distinct) == 82
    directory = REPORT / FOLDERS[0]
    scope = read(directory / 'scope.json')
    assert len(scope['paths']) == 20 and sum(r['bytes'] for r in scope['paths']) == 18417
    assert digest(json.dumps(scope['paths'], sort_keys=True).encode()) == scope['scope_sha256']
    for prefix in ('claude-initial', 'claude-discussion'):
        receipt = read(directory / f'{prefix}-receipt.json')
        raw = (directory / f'{prefix}.json').read_bytes()
        assert digest(raw) == receipt['stdout_sha256']
        assert digest((directory / f'{prefix}.stderr.txt').read_bytes()) == receipt['stderr_sha256']
        response = json.loads(raw)
        assert receipt['returncode'] == 0 and response['is_error'] is False
        assert (directory / f'{prefix}.md').read_bytes() == response['result'].encode('utf-8')
    source_hashes = {p.relative_to(BASE / 'baldrix/pinned').as_posix(): digest(p.read_bytes())
                     for p in sorted((BASE / 'baldrix/pinned').rglob('*')) if p.is_file()}
    tree_hash = digest(json.dumps(source_hashes, sort_keys=True).encode())
    receipts = list((directory / 'attempts').rglob('receipt.json'))
    assert len(receipts) == 1
    for path in receipts:
        receipt = read(path)
        metadata = read(path.parent / 'intent.json')['metadata']
        check = read(path.parent / 'source-check.json')
        assert receipt['status'] == 'completed' and receipt['returncode'] == receipt['container_cleanup_returncode'] == 0
        assert check['source_bytes_unchanged'] is True
        assert metadata['source_files'] == check['source_files'] == len(source_hashes) == 1648
        assert metadata['source_tree_hash_before'] == check['source_tree_hash_before'] == tree_hash
        for key, program in [('program_sha256', directory / 'component_observations.py'),
                             ('wrapper_sha256', directory / 'run_observations.py'),
                             ('recorder_sha256', REPORT / 'baldrix-test-runners-001/run_observations_v2.py')]:
            assert metadata[key] == check[key] == digest(program.read_bytes())
        for stream in ('stdout', 'stderr'):
            assert digest((path.parent / f'{stream}.txt').read_bytes()) == receipt[f'{stream}_sha256']
        observations = [json.loads(line) for line in (path.parent / 'stdout.txt').read_text().splitlines()]
        commands = [r for r in observations if 'argv' in r]
        assert len(commands) == 7
        manual = next(r for r in commands if r['observation'] == 'original_manual_test')
        assert manual['returncode'] == 0 and '[OK] 2/2 tests passed' in manual['stdout']
        for command in commands:
            assert digest(command['stdout'].encode('utf-8')) == command['stdout_sha256']
    all_artifacts = {p.relative_to(ROOT).as_posix(): digest(p.read_bytes())
                     for folder in FOLDERS for p in sorted((REPORT / folder).rglob('*')) if p.is_file()}
    result = {'kind': 'root_checkpoint_identity_verification', 'primary_records': primary,
              'supporting_records': supporting, 'raw_claude_receipts': 2,
              'original_observation_receipts': 1, 'original_cli_subprocesses': 7,
              'original_manual_tests_passed': 2, 'agent_original_tests_executed': 0,
              'artifact_hashes': all_artifacts, 'semantic_correctness_certified': False,
              'whole_analysis_complete': False, 'adoption_approved': False}
    (REPORT / 'example-tests-checkpoint-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'primary': primary, 'supporting': supporting, 'artifacts': len(all_artifacts)}))


if __name__ == '__main__':
    main()
