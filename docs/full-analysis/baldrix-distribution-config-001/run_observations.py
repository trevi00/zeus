"""Execute the bounded original-source observation using the published v2 recorder."""
import hashlib
import json
from pathlib import Path
import runpy
import uuid

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / '.runtime/absorption/sources/baldrix/pinned'
RECORDER = ROOT / 'docs/full-analysis/baldrix-test-runners-001/run_observations_v2.py'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint():
    return {p.relative_to(SOURCE).as_posix(): digest(p) for p in sorted(SOURCE.rglob('*')) if p.is_file()}


def main():
    recorder = runpy.run_path(str(RECORDER))
    attempt_id = uuid.uuid4().hex
    name = 'zeus-review-' + attempt_id
    base = OUT / 'attempts' / attempt_id
    before = fingerprint()
    assert len(before) == 1648
    tree_hash = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    assert tree_hash == '91a64542bc52b4a3a1f3e41ec0318bddbb21329f15880d33ed58b0acefb8111d'
    argv = ['docker', 'run', '--name', name, '--pull', 'never', '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '64',
            '--memory', '256m', '--cpus', '1', '--user', '65534:65534',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m']
    for value in ('HOME=/tmp', 'CLAUDE_HOME=/tmp/state-home', 'CLAUDE_ASSETS_HOME=/source',
                  'PYTHONDONTWRITEBYTECODE=1', 'PYTHONNOUSERSITE=1', 'PYTHONUTF8=1', 'PYTHONPATH=/source/scripts', 'TZ=UTC0'):
        argv += ['--env', value]
    argv += ['--mount', f'type=bind,source={SOURCE},target=/source,readonly',
             '--mount', f'type=bind,source={OUT / "component_observations.py"},target=/review.py,readonly',
             '--workdir', '/source/scripts', '--entrypoint', '/usr/bin/timeout', recorder['IMAGE'],
             '60', '/app/.venv/bin/python', '-B', '/review.py']
    metadata = {'source_files': len(before), 'source_tree_hash_before': tree_hash,
                'revision': 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2',
                'program_sha256': digest(OUT / 'component_observations.py'),
                'wrapper_sha256': digest(Path(__file__)), 'recorder_sha256': digest(RECORDER)}
    result = recorder['capture'](base, argv, 80, container_name=name, metadata=metadata)
    unchanged = before == fingerprint()
    recorder['save'](base / 'source-check.json', {**metadata, 'source_bytes_unchanged': unchanged})
    print(json.dumps({'attempt': base.relative_to(ROOT).as_posix(), **result}))
    return 0 if result['status'] == 'completed' and result['returncode'] == 0 and result.get('container_cleanup_returncode') == 0 and unchanged else 1


if __name__ == '__main__':
    raise SystemExit(main())
