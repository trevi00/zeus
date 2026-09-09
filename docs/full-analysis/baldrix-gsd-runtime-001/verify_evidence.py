"""Validate retained bytes and execution scope; never execute upstream sources."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    wrappers = {sha(p): p.name for p in OUT.glob('run_*.py')}
    programs = {sha(p): p.name for p in OUT.glob('*.cjs')}
    source = ROOT / '.runtime/absorption/sources/baldrix/pinned'
    manifest = json.loads((source.parent / 'manifest.json').read_text('utf-8'))
    fingerprint = {}
    for entry in manifest['inventory']:
        path = source / entry['path']
        raw = path.read_bytes()
        assert len(raw) == entry['bytes']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == entry['object']
        fingerprint[entry['path']] = sha(path)
    tree = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    assert len(fingerprint) == 1648
    assert tree == '91a64542bc52b4a3a1f3e41ec0318bddbb21329f15880d33ed58b0acefb8111d'
    rows = []
    for directory in sorted((OUT / 'attempts').iterdir()):
        intent = json.loads((directory / 'intent.json').read_text())
        receipt = json.loads((directory / 'receipt.json').read_text())
        checked = json.loads((directory / 'source-check.json').read_text())
        meta = intent['metadata']
        assert checked['source_bytes_unchanged']
        assert meta['source_tree_hash_before'] == tree
        assert meta['wrapper_sha256'] in wrappers
        assert meta['recorder_sha256'] == sha(ROOT / 'docs/full-analysis/baldrix-test-runners-001/run_observations_v2.py')
        for key in ['environment_program_sha256', 'component_program_sha256']:
            if key in meta:
                assert meta[key] in programs
        assert meta['original_test_sha256'] == fingerprint['get-shit-done/bin/lib/__tests__/merge-back.test.cjs']
        for stream in ['stdout', 'stderr']:
            assert sha(directory / (stream + '.txt')) == receipt[stream + '_sha256']
        assert receipt['container_cleanup_returncode'] == 0
        assert (directory / 'cleanup.stdout.txt').read_text().strip() == intent['container_name']
        argv = intent['argv']
        for option, value in [('--network', 'none'), ('--pids-limit', '64'), ('--user', '65534:65534'),
                              ('--memory', '256m'), ('--cpus', '1'), ('--cap-drop', 'ALL')]:
            assert argv[argv.index(option) + 1] == value
        assert '--read-only' in argv and 'no-new-privileges' in argv
        assert meta['image'] == 'sha256:12ba66164e4c3074725e4e6972ca436f946dac480cd2e426530f3c1b8343ef6c'
        rows.append({'attempt': directory.name, 'exit': receipt['returncode'],
                     'wrapper': wrappers[meta['wrapper_sha256']], 'docker_init': '--init' in argv})
    assert len(rows) == 5
    original = (OUT / 'run_observations.py').read_text()
    with_init = (OUT / 'run_observations_with_init.py').read_text()
    assert with_init == original.replace("'--name', name", "'--init', '--name', name")
    passed = (OUT / 'attempts/original-tests-b017f7cfa7f947a09c5b3f940c449391/stdout.txt').read_text('utf-8')
    assert 'tests 13' in passed and 'pass 13' in passed and 'fail 0' in passed and 'cancelled 0' in passed
    observations = [json.loads(line) for line in (OUT / 'attempts/components-367f9cbb19a94b90ae20392ca0ceb5c3/stdout.txt').read_text('utf-8').splitlines()]
    cases = {r['name']: r for r in observations if 'name' in r}
    assert len(cases) == 6
    assert all(r['result']['status'] == 0 and 'json' in r['result'] for r in cases.values())
    assert cases['merge-invalid-base']['result']['json']['merged']
    foreign = cases['merge-foreign-branch']['result']['json']['worktrees'][0]
    assert foreign['branch'] == 'unrelated-owner' and foreign['branch_deleted'] and foreign['removed']
    assert cases['phase-renumber']['after'].count('### Phase 5:') == 2
    assert not cases['profile-evidence']['sentinel_present']
    assert cases['profile-evidence_quotes']['sentinel_present']
    claude = json.loads((OUT / 'claude-discussion-receipt.json').read_text('utf-8'))
    assert claude['returncode'] == 0 and not claude['is_error']
    assert claude['stdout_sha256'] == sha(OUT / 'claude-discussion.json')
    assert claude['stderr_sha256'] == sha(OUT / 'claude-discussion.stderr.txt')
    raw_claude = json.loads((OUT / 'claude-discussion.json').read_text('utf-8'))
    assert raw_claude['session_id'] == claude['session_id']
    assert raw_claude['result'] == (OUT / 'claude-discussion.md').read_text('utf-8')
    assert claude['argv'][-1] == (OUT / 'claude-discussion-prompt.txt').read_text('utf-8')
    identity = json.loads((OUT / 'runtime-tool-identity-v2.json').read_text())
    assert identity['returncode'] == 0 and identity['stdout'].strip() == '/bin/busybox'
    result = {'source_files_verified': len(fingerprint), 'attempts': rows,
              'original_test_passes': 13, 'component_observations': 6,
              'new_primary_coverage': 0, 'acceptance': False, 'whole_analysis_complete': False,
              'actual_claude_receipt_bound': True,
              'verifier_sha256': sha(Path(__file__))}
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
