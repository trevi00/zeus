"""Run the validation suite on this host against a PostgreSQL/Redis stack this run owns, and write a bound receipt.

One run = one host at one Git head. The run creates its own compose project (a fresh unique name,
refused if anything already carries that name), publishes the services on ephemeral loopback ports
(so nothing that already listens on the fixed 55432/56379 ports is touched), pins the database, Redis
and namespace settings to that stack through the repository .env (the way CI does) while running the
tests in an environment stripped of every inherited ZEUS_*/HARNESS_*/POSTGRES_*/COMPOSE_* variable, so
nothing can point them elsewhere and the tests that manage their own .env or variables still can;
the previous .env is restored at teardown. It records the
identity of the services the tests will talk to (PostgreSQL system identifier and container id, Redis
run_id and container id) before and after the run together with their traffic counters, runs the same
commands CI runs, and tears down only the resources it created. Every phase is recorded as it ended:
a setup, stack, step, timeout, identity or teardown failure makes `passed` false and the process exit
non-zero, and a teardown failure never erases the step evidence gathered before it.

The receipt binds the execution bytes: git head, tracked and untracked changes, and the digests of the
runner itself, compose.yaml, the generated override, uv.lock and pyproject.toml. Secrets never enter
the receipt or the logs the runner writes: the database URL is recorded with its password redacted.

usage: uv run python scripts/environment_evidence.py --label windows-11 --out docs/zeus/evidence/environment-runs-002
"""
import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = 'compose.yaml'
INHERITED_PREFIXES = ('ZEUS_', 'HARNESS_', 'POSTGRES_', 'COMPOSE_')
STEP_TIMEOUT = 3600
OVERRIDE = ('services:\n'
            '  postgres:\n    ports: !override ["127.0.0.1::5432"]\n'
            '  redis:\n    ports: !override ["127.0.0.1::6379"]\n')


def now():
    return datetime.now(timezone.utc).isoformat()


def digest_text(text):
    return 'sha256:' + hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()


def digest_file(path):
    try:
        return 'sha256:' + hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        return 'unreadable: ' + type(exc).__name__


def redact(url):
    return re.sub(r'://([^:/@]+):[^@]*@', r'://\1:***@', url)


class Shell:
    """The only subprocess boundary; tests replace it."""

    def run(self, argv, env=None, timeout=STEP_TIMEOUT, cwd=ROOT):
        started = time.monotonic()
        try:
            completed = subprocess.run(argv, cwd=cwd, env=env if env is not None else {**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
            return {'returncode': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr,
                    'seconds': round(time.monotonic() - started, 1), 'timed_out': False, 'error': None}
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode('utf-8', 'replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
            err = exc.stderr.decode('utf-8', 'replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
            return {'returncode': None, 'stdout': out, 'stderr': err, 'seconds': round(time.monotonic() - started, 1),
                    'timed_out': True, 'error': f'timeout after {timeout}s'}
        except OSError as exc:
            return {'returncode': None, 'stdout': '', 'stderr': '', 'seconds': round(time.monotonic() - started, 1),
                    'timed_out': False, 'error': type(exc).__name__ + ': ' + str(exc)}


class EvidenceRun:
    def __init__(self, label, out, shell=None, root=ROOT, project=None):
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,40}', label):
            raise ValueError('label must be a lowercase token (letters, digits, dot, dash)')
        self.label, self.root, self.shell = label, Path(root), shell or Shell()
        self.out = self.root / out
        # compose project names allow only [a-z0-9_-]; a label like "wsl-ubuntu-26.04" is normalized.
        self.project = project or f"harness-evidence-{re.sub(r'[^a-z0-9-]', '-', label)}-{uuid4().hex[:8]}"
        self.password = secrets.token_hex(16)
        self.receipt = {'label': label, 'compose_project': self.project, 'started_at': now(), 'phases': {}, 'steps': [], 'passed': False,
                        'authority': 'what ran on this host at this head against the stack this run created; not a reboot, '
                                     'a human acceptance or a deployment'}
        self.services = {}
        self.env = None

    # ---- helpers
    def sh(self, argv, **kwargs):
        return self.shell.run(argv, **kwargs)

    def compose(self, *args, env=None, timeout=900):
        argv = ['docker', 'compose', '-p', self.project, '-f', str(self.root / COMPOSE_FILE), '-f', str(self.override_path), *args]
        return self.sh(argv, env={**os.environ, 'POSTGRES_PASSWORD': self.password, **(env or {})}, timeout=timeout)

    def phase(self, name, result, ok):
        self.receipt['phases'][name] = {**result, 'ok': bool(ok), 'at': now()}
        return ok

    @property
    def override_path(self):
        return self.out / f'{self.label}-compose.override.yaml'

    # ---- phases
    def preflight(self):
        head = self.sh(['git', 'rev-parse', 'HEAD'])
        status = self.sh(['git', 'status', '--porcelain', '--untracked-files=all'])
        diff = self.sh(['git', 'diff', 'HEAD'])
        changes = [line for line in status['stdout'].splitlines() if line.strip()]
        info = {'head': head['stdout'].strip(), 'tracked_changes': [c for c in changes if not c.startswith('??')],
                'untracked': [c[3:] for c in changes if c.startswith('??')], 'diff_sha256': digest_text(diff['stdout']),
                'inputs': {'runner': digest_file(Path(__file__)), 'compose': digest_file(self.root / COMPOSE_FILE),
                           'uv.lock': digest_file(self.root / 'uv.lock'), 'pyproject.toml': digest_file(self.root / 'pyproject.toml'),
                           'override': digest_text(OVERRIDE)},
                'platform': platform.platform(), 'machine': platform.machine(), 'python': platform.python_version(),
                'uv': self.version(['uv', '--version']), 'docker': self.version(['docker', 'version', '--format', '{{.Server.Version}}']),
                'compose': self.version(['docker', 'compose', 'version', '--short'])}
        self.receipt.update(info)
        ok = head['returncode'] == 0 and bool(info['head'])
        return self.phase('preflight', {'git_ok': ok}, ok)

    def version(self, argv):
        result = self.sh(argv, timeout=60)
        return result['stdout'].strip().splitlines()[0] if result['stdout'].strip() else 'unavailable: ' + str(result['error'] or result['stderr'][:80])

    def claim_project(self):
        """The project name must be new: nothing may already carry it, so teardown can only remove what this run made."""
        existing = self.sh(['docker', 'ps', '-a', '--filter', f'label=com.docker.compose.project={self.project}', '-q'], timeout=60)
        volumes = self.sh(['docker', 'volume', 'ls', '--filter', f'label=com.docker.compose.project={self.project}', '-q'], timeout=60)
        networks = self.sh(['docker', 'network', 'ls', '--filter', f'label=com.docker.compose.project={self.project}', '-q'], timeout=60)
        found = {'containers': existing['stdout'].split(), 'volumes': volumes['stdout'].split(), 'networks': networks['stdout'].split()}
        errors = [r['error'] for r in (existing, volumes, networks) if r['error'] or r['returncode']]
        ok = not errors and not any(found.values())
        return self.phase('claim_project', {'found': found, 'errors': errors,
                                            'refusal': None if ok else 'project name already owns resources or docker is unavailable'}, ok)

    def stack_up(self):
        self.out.mkdir(parents=True, exist_ok=True)
        self.override_path.write_text(OVERRIDE, encoding='utf-8')
        up = self.compose('up', '-d', '--wait', 'postgres', 'redis')
        if up['returncode'] != 0:
            return self.phase('stack_up', {'exit_code': up['returncode'], 'error': up['error'], 'stderr_tail': up['stderr'].strip().splitlines()[-6:]}, False)
        endpoints = {}
        for service, port in (('postgres', '5432'), ('redis', '6379')):
            ident = self.compose('ps', '-q', service, timeout=60)
            published = self.compose('port', service, port, timeout=60)
            match = re.fullmatch(r'127\.0\.0\.1:(\d+)', published['stdout'].strip())
            if not ident['stdout'].strip() or not match:
                return self.phase('stack_up', {'error': f'{service}: container or published port unavailable', 'stdout': published['stdout'][:200]}, False)
            endpoints[service] = {'container': ident['stdout'].strip(), 'host_port': int(match.group(1))}
        self.services = endpoints
        dsn = f"postgresql://harness:{self.password}@127.0.0.1:{endpoints['postgres']['host_port']}/harness"
        redis = f"redis://127.0.0.1:{endpoints['redis']['host_port']}/0"
        # The services are pinned the way CI pins them: through the repository's .env, which settings()
        # reads whenever the process environment carries no ZEUS_/HARNESS_ value. The tests therefore run
        # in an environment stripped of every inherited ZEUS_*/HARNESS_*/POSTGRES_*/COMPOSE_* variable
        # (nothing can point them elsewhere) while the tests that write their own .env or set their own
        # variables (configuration, supervisor) keep working. The previous .env is restored at teardown.
        base = {k: v for k, v in os.environ.items() if not k.startswith(INHERITED_PREFIXES)}
        self.env = {**base, 'PYTHONIOENCODING': 'utf-8'}
        dotenv = self.root / '.env'
        self.dotenv_before = dotenv.read_bytes() if dotenv.exists() else None
        content = (f'POSTGRES_PASSWORD={self.password}\nHARNESS_DATABASE_URL={dsn}\nHARNESS_REDIS_URL={redis}\n'
                   f'COMPOSE_PROJECT_NAME={self.project}\nZEUS_REDIS_NAMESPACE={self.project}\n')
        dotenv.write_text(content, encoding='utf-8', newline='\n')
        return self.phase('stack_up', {'seconds': up['seconds'], 'services': endpoints, 'database_url': redact(dsn), 'redis_url': redis,
                                       'dropped_inherited': sorted(k for k in os.environ if k.startswith(INHERITED_PREFIXES)),
                                       'pinning': {'mechanism': 'repository .env (settings() reads it when no ZEUS_/HARNESS_ variable is set)',
                                                   'dotenv_before_sha256': digest_text(self.dotenv_before.decode('utf-8', 'replace')) if self.dotenv_before is not None else None,
                                                   'dotenv_run_sha256': digest_text(content), 'dotenv_run': self.scrub(content).splitlines()}}, True)

    def scrub(self, text):
        """The per-run database password never reaches a log or the receipt."""
        return text.replace(self.password, '***')

    def identity(self, name):
        """Who the tests are talking to: identifiers that survive the run, and counters that must move during it."""
        pg = self.services['postgres']['container']
        rd = self.services['redis']['container']
        psql = ['docker', 'exec', pg, 'psql', '-U', 'harness', '-d', 'harness', '-tAc']
        system = self.sh(psql + ['select system_identifier from pg_control_system()'], timeout=60)
        commits = self.sh(psql + ["select xact_commit from pg_stat_database where datname='harness'"], timeout=60)
        info = self.sh(['docker', 'exec', rd, 'redis-cli', 'INFO'], timeout=60)
        run_id = re.search(r'run_id:(\w+)', info['stdout'])
        commands = re.search(r'total_commands_processed:(\d+)', info['stdout'])
        record = {'postgres': {'container': pg, 'system_identifier': system['stdout'].strip() or None,
                               'xact_commit': int(commits['stdout'].strip()) if commits['stdout'].strip().isdigit() else None},
                  'redis': {'container': rd, 'run_id': run_id.group(1) if run_id else None,
                            'total_commands_processed': int(commands.group(1)) if commands else None}}
        ok = all(v is not None for s in record.values() for v in s.values())
        return self.phase(name, record, ok)

    def steps(self):
        junit = self.out / f'{self.label}-full-suite.junit.xml'
        plan = [
            ('ruff', ['uv', 'run', 'ruff', 'check', '.'], {}),
            ('full-suite-integration', ['uv', 'run', 'python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', f'--junitxml={junit}'],
             {'HARNESS_INTEGRATION': '1'}),
            ('disposable-docker-checks', ['uv', 'run', 'python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                                          'tests/test_verification.py', 'tests/test_host_interruption.py'],
             {'HARNESS_INTEGRATION': '1', 'ZEUS_TEST_DOCKER': '1'}),
        ]
        all_ok = True
        for name, argv, extra in plan:
            result = self.sh(argv, env={**self.env, **extra})
            result['stdout'], result['stderr'] = self.scrub(result['stdout']), self.scrub(result['stderr'])
            log = self.out / f'{self.label}-{name}.log'
            log.write_text(result['stdout'] + ('\n--- stderr ---\n' + result['stderr'] if result['stderr'] else ''), encoding='utf-8', errors='replace')
            lines = [line for line in result['stdout'].splitlines() if line.strip()]
            summary = next((line for line in reversed(lines) if ' passed' in line or ' failed' in line or 'error' in line.lower()
                            or 'All checks passed' in line), lines[-1] if lines else '')
            ok = result['returncode'] == 0 and not result['timed_out'] and result['error'] is None
            all_ok = all_ok and ok
            self.receipt['steps'].append({'name': name, 'argv': argv, 'env_added': extra, 'exit_code': result['returncode'], 'ok': ok,
                                          'timed_out': result['timed_out'], 'error': result['error'], 'seconds': result['seconds'],
                                          'summary': summary, 'stdout_sha256': digest_text(result['stdout']),
                                          'stderr_sha256': digest_text(result['stderr']), 'log': log.name})
            if name == 'full-suite-integration' and junit.exists():
                junit.write_text(self.scrub(junit.read_text(encoding='utf-8')), encoding='utf-8', newline='\n')
                self.receipt['junit_sha256'] = digest_file(junit)
                self.receipt['per_file'] = per_file(junit)
        return self.phase('steps', {'count': len(self.receipt['steps']), 'expected': len(plan)}, all_ok and len(self.receipt['steps']) == len(plan))

    def identity_stable(self):
        before, after = self.receipt['phases'].get('identity_before'), self.receipt['phases'].get('identity_after')
        if not (before and after and before['ok'] and after['ok']):
            return self.phase('identity_stable', {'reason': 'identity was not observed on both sides'}, False)
        same = all(before[s][k] == after[s][k] for s in ('postgres', 'redis') for k in ('container', 'system_identifier', 'run_id') if k in before[s])
        moved = {'postgres_xact_commit': after['postgres']['xact_commit'] - before['postgres']['xact_commit'],
                 'redis_commands': after['redis']['total_commands_processed'] - before['redis']['total_commands_processed']}
        ok = same and moved['postgres_xact_commit'] > 0 and moved['redis_commands'] > 0
        return self.phase('identity_stable', {'same_services': same, 'traffic': moved,
                                              'note': 'the tests ran with both aliases pinned to this stack; the counters of this stack moved'}, ok)

    def teardown(self):
        dotenv = self.root / '.env'
        restored = None
        if hasattr(self, 'dotenv_before'):
            if self.dotenv_before is None:
                dotenv.unlink(missing_ok=True)
                restored = 'removed (there was no .env before the run)'
            else:
                dotenv.write_bytes(self.dotenv_before)
                restored = 'restored to its previous content'
        down = self.compose('down', '--volumes', '--remove-orphans', timeout=600)
        leftovers = self.sh(['docker', 'ps', '-a', '--filter', f'label=com.docker.compose.project={self.project}', '-q'], timeout=60)
        volumes = self.sh(['docker', 'volume', 'ls', '--filter', f'label=com.docker.compose.project={self.project}', '-q'], timeout=60)
        remaining = leftovers['stdout'].split() + volumes['stdout'].split()
        ok = down['returncode'] == 0 and not down['error'] and not remaining
        return self.phase('teardown', {'exit_code': down['returncode'], 'error': down['error'], 'stderr_tail': down['stderr'].strip().splitlines()[-4:],
                                       'remaining': remaining, 'scope': f'only compose project {self.project}', 'dotenv': restored}, ok)

    # ---- driver
    def execute(self):
        required = ['preflight', 'claim_project', 'stack_up', 'identity_before', 'steps', 'identity_after', 'identity_stable', 'teardown']
        created = False
        try:
            if not self.preflight() or not self.claim_project():
                return self.receipt
            created = True
            if not self.stack_up():
                return self.receipt
            if not self.identity('identity_before'):
                return self.receipt
            self.steps()
            self.identity('identity_after')
            self.identity_stable()
        except Exception as exc:  # any unexpected failure is recorded, never swallowed into a pass
            self.receipt['phases']['error'] = {'ok': False, 'type': type(exc).__name__, 'message': str(exc)[:500], 'at': now()}
        finally:
            if created:
                try:
                    self.teardown()
                except Exception as exc:
                    self.receipt['phases']['teardown'] = {'ok': False, 'type': type(exc).__name__, 'message': str(exc)[:500], 'at': now()}
            self.finish(required)
        return self.receipt

    def finish(self, required):
        phases = self.receipt['phases']
        self.receipt['required_phases'] = required
        self.receipt['passed'] = all(phases.get(name, {}).get('ok') is True for name in required) and 'error' not in phases
        self.receipt['finished_at'] = now()
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'{self.label}-receipt.json').write_text(self.scrub(json.dumps(self.receipt, ensure_ascii=False, indent=2)) + '\n', encoding='utf-8')
        return self.receipt


def per_file(junit_path):
    """Per test file outcome counts from the junit report, so a reader can map criteria to test nodes."""
    counts = {}
    for case in ET.parse(junit_path).getroot().iter('testcase'):
        # xunit2 gives classname "tests.test_module[.TestClass]" and no file attribute.
        module = next((part for part in case.get('classname', '').split('.') if part.startswith('test_')), None)
        name = case.get('file') or (module + '.py' if module else '')
        key = name.replace('\\', '/').split('/')[-1] if name else 'unknown'
        bucket = counts.setdefault(key, {'passed': 0, 'skipped': 0, 'failed': 0, 'error': 0})
        if case.find('skipped') is not None:
            bucket['skipped'] += 1
        elif case.find('failure') is not None:
            bucket['failed'] += 1
        elif case.find('error') is not None:
            bucket['error'] += 1
        else:
            bucket['passed'] += 1
    return dict(sorted(counts.items()))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True, help='host label, e.g. windows-11 or wsl-ubuntu-26.04')
    parser.add_argument('--out', required=True, help='directory (relative to the repository) for receipt, logs and override')
    args = parser.parse_args(argv)
    receipt = EvidenceRun(args.label, args.out, root=ROOT).execute()
    print(json.dumps({k: receipt.get(k) for k in ('label', 'compose_project', 'head', 'passed', 'finished_at')}), file=sys.stderr)
    for name, phase in receipt['phases'].items():
        if not phase.get('ok'):
            print(f'phase {name}: FAILED {json.dumps({k: v for k, v in phase.items() if k != "ok"}, ensure_ascii=False)[:300]}', file=sys.stderr)
    for step in receipt['steps']:
        print(f"{step['name']}: exit {step['exit_code']} in {step['seconds']}s: {step['summary']}", file=sys.stderr)
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
