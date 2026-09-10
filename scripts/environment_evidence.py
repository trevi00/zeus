"""Run the validation suite against disposable Docker PostgreSQL/Redis on this host and write a bound receipt.

One run = one host (Windows, WSL Ubuntu, ...) at one Git head: the stack is brought up under its own
compose project name, the same commands CI runs are executed with the integration and disposable-Docker
flags on, every command's exit code, duration, summary line and full-output digests are recorded, and the
stack is torn down with its volumes whatever happened. The receipt names the platform, Python, uv, Docker
and compose versions, the containers that served the run and the head that was checked out; it is
evidence of what ran here, not of a reboot, a person's acceptance or a production deployment.

usage: uv run python scripts/environment_evidence.py --label windows-11 --project harness-evidence-win --out docs/zeus/evidence/environment-runs-001
"""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat()


def capture(argv, env=None, timeout=3600):
    started = time.monotonic()
    completed = subprocess.run(argv, cwd=ROOT, env={**os.environ, 'PYTHONIOENCODING': 'utf-8', **(env or {})},
                               capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    return completed, time.monotonic() - started


def digest(text):
    return 'sha256:' + hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()


def version_of(argv):
    try:
        return capture(argv, timeout=60)[0].stdout.strip().splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired) as exc:
        return 'unavailable: ' + type(exc).__name__


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True, help='host label, e.g. windows-11 or wsl-ubuntu-26.04')
    parser.add_argument('--project', required=True, help='compose project name for the disposable stack')
    parser.add_argument('--out', required=True, help='directory for the receipt and logs')
    args = parser.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    head = capture(['git', 'rev-parse', 'HEAD'])[0].stdout.strip()
    dirty = capture(['git', 'status', '--porcelain', '--untracked-files=no'])[0].stdout.strip()
    receipt = {'label': args.label, 'head': head, 'tree_dirty': bool(dirty), 'started_at': now(),
               'platform': platform.platform(), 'machine': platform.machine(), 'python': platform.python_version(),
               'uv': version_of(['uv', '--version']), 'docker': version_of(['docker', 'version', '--format', '{{.Server.Version}}']),
               'compose': version_of(['docker', 'compose', 'version', '--short']), 'compose_project': args.project,
               'steps': [], 'authority': 'what ran on this host at this head; not a reboot, a human acceptance or a deployment'}
    setup, _ = capture(['uv', 'run', 'harness', 'setup'])
    receipt['setup'] = {'exit_code': setup.returncode, 'stdout_tail': setup.stdout.strip().splitlines()[-3:]}
    compose = ['docker', 'compose', '-p', args.project]
    try:
        up, seconds = capture(compose + ['up', '-d', '--wait', 'postgres', 'redis'], timeout=900)
        receipt['stack'] = {'exit_code': up.returncode, 'seconds': round(seconds, 1), 'stderr_tail': up.stderr.strip().splitlines()[-5:]}
        ps, _ = capture(compose + ['ps', '--format', 'json'])
        receipt['containers'] = [json.loads(line) for line in ps.stdout.splitlines() if line.strip().startswith('{')]
        if up.returncode:
            raise SystemExit('stack did not come up')
        steps = [
            ('ruff', ['uv', 'run', 'ruff', 'check', '.'], {}),
            ('full-suite-integration', ['uv', 'run', 'python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider'], {'HARNESS_INTEGRATION': '1'}),
            ('disposable-docker-checks', ['uv', 'run', 'python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                                          'tests/test_verification.py', 'tests/test_host_interruption.py'],
             {'HARNESS_INTEGRATION': '1', 'ZEUS_TEST_DOCKER': '1'}),
        ]
        for name, argv, env in steps:
            completed, seconds = capture(argv, env)
            (out / f'{args.label}-{name}.log').write_text(completed.stdout + ('\n--- stderr ---\n' + completed.stderr if completed.stderr else ''),
                                                          encoding='utf-8', errors='replace')
            lines = [line for line in completed.stdout.splitlines() if line.strip()]
            summary = next((line for line in reversed(lines) if ' passed' in line or ' failed' in line or 'error' in line.lower()
                            or 'All checks passed' in line), lines[-1] if lines else '')
            receipt['steps'].append({'name': name, 'argv': argv, 'env': env, 'exit_code': completed.returncode, 'seconds': round(seconds, 1),
                                     'summary': summary, 'stdout_sha256': digest(completed.stdout), 'stderr_sha256': digest(completed.stderr),
                                     'log': f'{args.label}-{name}.log'})
    finally:
        down, _ = capture(compose + ['down', '--volumes', '--remove-orphans'], timeout=600)
        receipt['teardown'] = {'exit_code': down.returncode, 'stderr_tail': down.stderr.strip().splitlines()[-4:]}
        receipt['finished_at'] = now()
        receipt['passed'] = bool(receipt['steps']) and all(step['exit_code'] == 0 for step in receipt['steps'])
        (out / f'{args.label}-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({k: receipt[k] for k in ('label', 'head', 'passed', 'finished_at')}), file=sys.stderr)
        for step in receipt['steps']:
            print(f"{step['name']}: exit {step['exit_code']} in {step['seconds']}s: {step['summary']}", file=sys.stderr)


if __name__ == '__main__':
    main()
