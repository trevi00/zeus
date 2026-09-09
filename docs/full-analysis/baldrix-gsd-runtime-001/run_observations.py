"""Run original GSD Node tests in the immutable offline review runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import uuid

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / '.runtime/absorption/sources/baldrix/pinned'
RECORDER = ROOT / 'docs/full-analysis/baldrix-test-runners-001/run_observations_v2.py'
IMAGE = 'sha256:12ba66164e4c3074725e4e6972ca436f946dac480cd2e426530f3c1b8343ef6c'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint():
    return {p.relative_to(SOURCE).as_posix(): digest(p) for p in sorted(SOURCE.rglob('*')) if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['environment', 'original-tests'])
    args = parser.parse_args()
    recorder = runpy.run_path(str(RECORDER))
    attempt_id = uuid.uuid4().hex
    name = 'zeus-gsd-review-' + attempt_id
    base = OUT / 'attempts' / (args.mode + '-' + attempt_id)
    before = fingerprint()
    tree_hash = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    assert len(before) == 1648
    assert tree_hash == '91a64542bc52b4a3a1f3e41ec0318bddbb21329f15880d33ed58b0acefb8111d'
    argv = ['docker', 'run', '--name', name, '--pull', 'never', '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '64',
            '--memory', '256m', '--cpus', '1', '--user', '65534:65534',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m']
    for value in ('HOME=/tmp/home', 'GSD_HOME=/tmp/home', 'CLAUDE_HOME=/tmp/home/.claude',
                  'TMPDIR=/tmp', 'TZ=UTC0', 'GIT_CONFIG_NOSYSTEM=1',
                  'GIT_CONFIG_GLOBAL=/dev/null', 'GIT_TERMINAL_PROMPT=0'):
        argv += ['--env', value]
    argv += ['--mount', f'type=bind,source={SOURCE},target=/source,readonly',
             '--workdir', '/tmp', '--entrypoint', '/usr/bin/timeout']
    if args.mode == 'environment':
        argv += ['--mount', f'type=bind,source={OUT / "environment.cjs"},target=/review.cjs,readonly']
        command = ['node', '/review.cjs']
    else:
        command = ['node', '--test', '/source/get-shit-done/bin/lib/__tests__/merge-back.test.cjs']
    argv += [IMAGE, '60', *command]
    metadata = {'mode': args.mode, 'source_files': len(before), 'source_tree_hash_before': tree_hash,
                'revision': 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2', 'image': IMAGE,
                'wrapper_sha256': digest(Path(__file__)), 'recorder_sha256': digest(RECORDER),
                'environment_program_sha256': digest(OUT / 'environment.cjs'),
                'original_test_sha256': digest(SOURCE / 'get-shit-done/bin/lib/__tests__/merge-back.test.cjs')}
    result = recorder['capture'](base, argv, 80, container_name=name, metadata=metadata)
    unchanged = before == fingerprint()
    recorder['save'](base / 'source-check.json', {**metadata, 'source_bytes_unchanged': unchanged})
    print(json.dumps({'attempt': base.relative_to(ROOT).as_posix(), **result}))
    return 0 if result['status'] == 'completed' and result['returncode'] == 0 and result.get('container_cleanup_returncode') == 0 and unchanged else 1


if __name__ == '__main__':
    raise SystemExit(main())
