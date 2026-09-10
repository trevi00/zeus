"""Deterministic evidence inspection: explicit cwd, bounded replay, raw bytes kept, states named.

File checks and command replays share one explicit context (workspace cwd, source revision,
policy hash). Replays run only for policy-authorized argv prefixes, with a minimal environment,
a finite per-command deadline, an output byte cap and an aggregate budget; the process tree is
terminated on timeout and that termination is recorded. Raw stdout/stderr bytes are archived
losslessly (latin-1 byte-preserving text) beside their SHA-256, and decoding problems are a
recorded property of the output, never a replacement of it.
"""
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

from codex_harness.domain.evidence import (
    authorized,
    classify_replays,
    finite_positive,
    parse_claim,
    parse_policy,
)
from codex_harness.domain.model import ContractError, canonical, digest

POLICY_FILE = Path(__file__).resolve().parents[1] / 'resources/evidence-policy.json'
KEEP_ENV = ('PATH', 'SYSTEMROOT', 'SystemRoot', 'COMSPEC', 'TEMP', 'TMP', 'HOME', 'USERPROFILE', 'LANG', 'LC_ALL')


def packaged_policy():
    try:
        return parse_policy(json.loads(POLICY_FILE.read_text(encoding='utf-8')))
    except (OSError, ValueError) as exc:
        raise ContractError('Evidence policy definition unavailable or invalid') from exc


def replay_environment(base=None):
    env = {key: value for key, value in (base if base is not None else os.environ).items() if key in KEEP_ENV}
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def _capture(argv, cwd, timeout, max_bytes, env):
    """Run one bounded replay and return everything observed, including how it ended."""
    started = time.monotonic()
    try:
        process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=env,
                                   **({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt'
                                      else {'start_new_session': True}))
    except FileNotFoundError as exc:
        return {'failure': 'executable_missing: ' + str(exc), 'returncode': None, 'duration_seconds': 0.0}
    except PermissionError as exc:
        return {'failure': 'permission_denied: ' + str(exc), 'returncode': None, 'duration_seconds': 0.0}
    except OSError as exc:
        return {'failure': 'spawn_error: ' + type(exc).__name__ + ': ' + str(exc), 'returncode': None,
                'duration_seconds': 0.0}
    captured = [b'', b'']
    truncated = [False, False]

    def drain(stream, index):
        while block := stream.read(4096):
            room = max_bytes - len(captured[index])
            if room > 0:
                captured[index] += block[:room]
            if len(block) > room:
                truncated[index] = True
    readers = [threading.Thread(target=drain, args=(stream, i), daemon=True)
               for i, stream in enumerate((process.stdout, process.stderr))]
    for thread in readers:
        thread.start()
    terminated, failure = False, None
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminated, failure = True, f'timeout after {timeout}s; process tree terminated'
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=20)
        else:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=20)
    finally:
        for thread in readers:
            thread.join(timeout=5)
        for stream in (process.stdout, process.stderr):
            stream.close()
    streams = {}
    for name, raw, cut in (('stdout', captured[0], truncated[0]), ('stderr', captured[1], truncated[1])):
        try:
            raw.decode('utf-8')
            decoding = 'utf-8'
        except UnicodeDecodeError as exc:
            decoding = 'invalid_utf8: ' + str(exc)[:120]
        streams[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'truncated': cut,
                         'decoding': decoding, 'raw': raw.decode('latin-1')}
    return {'failure': failure, 'terminated': terminated, 'returncode': process.returncode,
            'duration_seconds': round(time.monotonic() - started, 3), **streams}


class EvidenceInspector:
    def __init__(self, artifacts, policy=None):
        self.artifacts = artifacts
        self.policy = parse_policy(policy) if policy is not None else packaged_policy()

    def _archive(self, run):
        """Raw bytes go to the artifact store byte-for-byte; the finding keeps hashes and refs."""
        archived = {}
        for name in ('stdout', 'stderr'):
            if name in run:
                stream = run.pop(name)
                receipt = self.artifacts.put(canonical({'encoding': 'latin-1 byte-preserving', 'sha256': stream['sha256'],
                                                        'bytes': stream['bytes'], 'truncated': stream['truncated'],
                                                        'decoding': stream['decoding'], 'raw': stream['raw']}),
                                             'evidence-replay-' + name)
                archived[name] = {k: v for k, v in stream.items() if k != 'raw'} | {'ref': receipt['ref']}
        return {**run, **archived}

    def inspect_file(self, claim, cwd):
        root = Path(cwd).resolve()
        target = (root / claim['path'])
        try:
            resolved = target.resolve()
        except (OSError, ValueError) as exc:
            return {'state': 'error', 'cause': 'path cannot be resolved: ' + type(exc).__name__}
        if root not in resolved.parents and resolved != root:
            return {'state': 'error', 'cause': 'path resolves outside the workspace'}
        try:
            if not target.exists():
                return {'state': 'missing', 'cause': 'no such file under the workspace'}
            if target.is_dir():
                return {'state': 'missing', 'cause': 'a directory is not evidence'}
            size = target.stat().st_size
        except PermissionError as exc:
            return {'state': 'unknown', 'cause': 'permission denied: ' + str(exc)}
        except OSError as exc:
            return {'state': 'unknown', 'cause': 'stat failed: ' + type(exc).__name__}
        if size > self.policy['files']['max_bytes']:
            return {'state': 'not_checked', 'cause': f'file of {size} bytes exceeds the inspection budget', 'bytes': size}
        try:
            data = target.read_bytes()
        except PermissionError as exc:
            return {'state': 'unknown', 'cause': 'permission denied: ' + str(exc)}
        except OSError as exc:
            return {'state': 'unknown', 'cause': 'read failed: ' + type(exc).__name__}
        observed = hashlib.sha256(data).hexdigest()
        detail = {'bytes': len(data), 'sha256': observed}
        if claim['range'] is not None:
            lines = data.count(b'\n') + (0 if data.endswith(b'\n') or not data else 1)
            if claim['range']['end'] > lines:
                return {'state': 'verified_mismatch', 'cause': f'range ends at line {claim["range"]["end"]} but the file has {lines}',
                        **detail, 'lines': lines}
            detail['lines'] = lines
        if claim['sha256'] is not None and claim['sha256'] != observed:
            return {'state': 'verified_mismatch', 'cause': 'content hash differs from the claim', **detail}
        return {'state': 'checked', 'cause': 'file present' + (' with the claimed hash' if claim['sha256'] else
                                                              '; no hash was claimed, so only presence is checked'), **detail}

    def inspect_command(self, claim, cwd, remaining_seconds, environment=None):
        if not authorized(claim['argv'], self.policy):
            return {'state': 'not_checked', 'cause': 'command is not an authorized replay prefix; a claim is not authority'}
        per_command = min(self.policy['replay']['per_command_seconds'], remaining_seconds)
        if per_command <= 0:
            return {'state': 'not_checked', 'cause': 'aggregate replay budget exhausted'}
        finite_positive(per_command, 'replay deadline', self.policy['replay']['total_seconds'])
        runs = []
        for _ in range(self.policy['replay']['replays_per_claim']):
            run = _capture(claim['argv'], str(Path(cwd).resolve()), per_command, self.policy['replay']['max_output_bytes'],
                           dict(environment) if environment is not None else replay_environment())
            runs.append(self._archive(run))
            if run.get('failure'):
                break
        state, cause = classify_replays(runs, claim['expected_exit'])
        return {'state': state, 'cause': cause, 'runs': runs, 'replay_argv': list(claim['argv']),
                'argv_identical': True}

    def snapshot(self):
        """One environment snapshot: its digest is part of the inspection identity and the same values
        are what every replay runs under (review, PR #54: names alone let a changed value reuse a pass)."""
        environment = replay_environment()
        identity = {'policy_hash': self.policy['policy_hash'], 'environment_names': sorted(environment),
                    'environment_digest': digest(sorted(environment.items())),
                    'tool': {'python': platform.python_version(), 'executable_digest': digest(sys.executable),
                             'implementation': platform.python_implementation()},
                    'platform': platform.platform()}
        return {'identity': identity, 'environment': environment}

    def identity(self):
        return self.snapshot()['identity']

    def inspect(self, claims, cwd, binding, environment=None):
        """Inspect every claim in one explicit context; the budget is enforced, never assumed.

        `environment` is the snapshot the caller keyed the inspection by; every replay runs under exactly it.
        """
        environment = dict(environment) if environment is not None else replay_environment()
        root = Path(cwd)
        if not root.is_dir():
            return {'context': {**binding, 'cwd': str(root)}, 'policy_hash': self.policy['policy_hash'], 'findings': [
                {'claim': None, 'state': 'error', 'cause': 'workspace directory does not exist'}]}
        context = {**binding, 'cwd': str(root.resolve()), 'environment': sorted(environment),
                   'environment_digest': digest(sorted(environment.items())), 'python': sys.version.split()[0]}
        findings = []
        deadline = time.monotonic() + self.policy['replay']['total_seconds']
        for index, raw in enumerate(claims):
            try:
                claim = parse_claim(raw)
            except ContractError as exc:
                findings.append({'claim': {'raw': repr(raw)[:500]}, 'state': 'error', 'cause': str(exc)})
                continue
            if index >= self.policy['replay']['max_claims']:
                findings.append({'claim': claim, 'state': 'not_checked', 'cause': 'claim budget exhausted'})
                continue
            if claim['kind'] == 'file':
                result = self.inspect_file(claim, root)
            else:
                result = self.inspect_command(claim, root, deadline - time.monotonic(), environment)
            findings.append({'claim': claim, **result})
        return {'context': context, 'policy_hash': self.policy['policy_hash'], 'findings': findings,
                'inspection_id': digest([context, self.policy['policy_hash'], [f['claim'] for f in findings]])}
