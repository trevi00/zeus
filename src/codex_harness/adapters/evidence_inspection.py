"""Deterministic evidence inspection: explicit cwd, bounded replay, raw bytes kept, states named.

File checks and command replays share one explicit context (workspace cwd, source revision,
policy hash). Replays run only for policy-authorized argv prefixes, with a minimal environment,
a finite per-command deadline, an output byte cap and an aggregate budget; the process tree is
terminated on timeout and that termination is recorded. Raw stdout/stderr bytes are archived
losslessly (latin-1 byte-preserving text) beside their SHA-256, and decoding problems are a
recorded property of the output, never a replacement of it.

Replay context (review-contract-001): a Python replay runs the trusted host interpreter, never
the first token the model wrote. Authorization is decided on the original claim argv; only an
authorized `python -m ...` claim has its first token replaced by the verified absolute
`sys.executable`, and the finding keeps the original argv, the effective argv and the reason.
The snapshot is taken per workspace: it binds that interpreter, the normalized cwd and a
PYTHONPATH that is the candidate's `src` only when it exists (the parent's PYTHONPATH and the
harness's own secrets are never inherited), and every replay runs under exactly those values.
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

from codex_harness.adapters.process_tree import ProcessTree, TreeOwnershipError
from codex_harness.domain.evidence import (
    authorized,
    classify_replays,
    finite_positive,
    parse_claim,
    parse_policy,
)
from codex_harness.domain.model import ContractError, canonical, digest

# Capture teardown bounds: each tree-termination phase, then the readers' one shared join window.
CLEANUP_SECONDS = 10.0
READER_JOIN_SECONDS = 5.0
POLICY_FILE = Path(__file__).resolve().parents[1] / 'resources/evidence-policy.json'
# PROGRAMDATA (Windows OpenSSH reads its host configuration under it; goal-progress-001 isolated an
# ssh-keygen exit 255 to its absence) joins the allowlist under both spellings the host may carry,
# like SYSTEMROOT/SystemRoot. Its value takes part in the snapshot digest (INV-OPERATION-001).
KEEP_ENV = ('PATH', 'SYSTEMROOT', 'SystemRoot', 'COMSPEC', 'TEMP', 'TMP', 'HOME', 'USERPROFILE', 'LANG', 'LC_ALL',
            'PROGRAMDATA', 'ProgramData')


def packaged_policy():
    try:
        return parse_policy(json.loads(POLICY_FILE.read_text(encoding='utf-8')))
    except (OSError, ValueError) as exc:
        raise ContractError('Evidence policy definition unavailable or invalid') from exc


def replay_environment(base=None, cwd=None):
    """The minimal replay environment. With `cwd`, PYTHONPATH is bound to `<cwd>/src` when that
    directory exists and is otherwise absent; the parent's PYTHONPATH is never in KEEP_ENV."""
    env = {key: value for key, value in (base if base is not None else os.environ).items() if key in KEEP_ENV}
    env['PYTHONIOENCODING'] = 'utf-8'
    if cwd is not None:
        source_root = Path(cwd).resolve() / 'src'
        if source_root.is_dir():
            env['PYTHONPATH'] = str(source_root)
    return env


def trusted_interpreter(candidate=None):
    """The host interpreter every Python replay runs: an existing absolute file, verified before any
    child starts. Windows `shell=False` does not resolve `python` through the child's PATH, and a
    model-written executable is never trusted, so the replay names this file explicitly."""
    path = Path(candidate if candidate is not None else sys.executable)
    if not (path.is_absolute() and path.is_file()):
        raise ContractError('Trusted replay interpreter is not a file: ' + str(path))
    return path.resolve()


def replay_argv(argv, interpreter):
    """The effective argv for an already authorized claim, with the reason it differs, if it does.

    Only a claim whose first two tokens are `python -m` is rewritten, and only its first token; every
    other authorized command runs exactly as claimed. The caller authorizes the original argv first,
    so this never widens a policy prefix.
    """
    if len(argv) >= 2 and argv[0] == 'python' and argv[1] == '-m':
        return [str(interpreter), *argv[1:]], ('first token "python" replaced by the trusted host interpreter; '
                                              'authorization was decided on the original argv')
    return list(argv), None


def _reclaim(tree, readers, reason):
    """Bounded teardown of one capture, in the only safe order: end the owned process TREE, then a
    bounded join of the readers, then close only the streams whose reader has finished. A blocking
    close is never attempted while a live reader owns the stream; what cannot be reclaimed is
    reported as debt, never discarded. Returns the cleanup record; `confirmed` means nothing is left."""
    record = {'reason': reason, 'tree': None, 'readers_alive': [], 'streams_closed': [], 'error': None}
    try:
        record['tree'] = tree.terminate(reason, timeout=CLEANUP_SECONDS, settle=CLEANUP_SECONDS)
    except Exception as exc:  # the readers and the caller's own cleanup still get their turn
        record['error'] = type(exc).__name__ + ': ' + str(exc)
    deadline = time.monotonic() + READER_JOIN_SECONDS
    for name, thread, stream in readers:
        if thread.ident is not None:  # a reader that never started owns nothing
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            record['readers_alive'].append(name)
            continue
        try:
            stream.close()
            record['streams_closed'].append(name)
        except OSError as exc:
            record['error'] = record['error'] or type(exc).__name__ + ': ' + str(exc)
    try:
        tree.close()
    except Exception as exc:
        record['error'] = record['error'] or type(exc).__name__ + ': ' + str(exc)
    record['confirmed'] = bool(record['tree'] and record['tree']['confirmed'] and not record['readers_alive']
                               and record['error'] is None)
    return record


def _capture(argv, cwd, timeout, max_bytes, env):
    """Run one bounded replay and return everything observed, including how it ended.

    The client process is an owned `ProcessTree` from spawn. However the wait ends (exit, deadline,
    KeyboardInterrupt, any exception) `_reclaim` runs once, bounded, before anything propagates; an
    interruption is re-raised unchanged with the cleanup record on its `capture_cleanup` attribute,
    so the outer owner (`hold`) still stops its container and knows what this capture left behind."""
    started = time.monotonic()
    try:
        tree = ProcessTree.spawn(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        return {'failure': 'executable_missing: ' + str(exc), 'returncode': None, 'duration_seconds': 0.0}
    except PermissionError as exc:
        return {'failure': 'permission_denied: ' + str(exc), 'returncode': None, 'duration_seconds': 0.0}
    except OSError as exc:
        return {'failure': 'spawn_error: ' + type(exc).__name__ + ': ' + str(exc), 'returncode': None,
                'duration_seconds': 0.0}
    except TreeOwnershipError as exc:  # no owned boundary, no replay; a leak carries its own detail
        return {'failure': 'spawn_error: ' + type(exc).__name__ + ': ' + str(exc), 'returncode': None,
                'duration_seconds': 0.0, **({'cleanup': exc.detail} if hasattr(exc, 'detail') else {})}
    process = tree.process
    captured = [b'', b'']
    truncated = [False, False]

    def drain(stream, index):
        while block := stream.read(4096):
            room = max_bytes - len(captured[index])
            if room > 0:
                captured[index] += block[:room]
            if len(block) > room:
                truncated[index] = True
    readers = [(name, threading.Thread(target=drain, args=(stream, i), daemon=True), stream)
               for i, (name, stream) in enumerate((('stdout', process.stdout), ('stderr', process.stderr)))]
    terminated, failure, reason = False, None, 'exited'
    try:
        for _, thread, _ in readers:
            thread.start()
        process.wait(timeout=timeout)
        deadline = time.monotonic() + READER_JOIN_SECONDS  # an exited child's output, as before
        for _, thread, _ in readers:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        terminated, failure, reason = True, f'timeout after {timeout}s; process tree terminated', 'timeout'
    except BaseException as exc:
        # Cancellation or an unexpected failure: bounded cleanup first, then the ORIGINAL exception.
        exc.capture_cleanup = _reclaim(tree, readers, type(exc).__name__)
        raise
    cleanup = _reclaim(tree, readers, reason)
    if not cleanup['confirmed']:
        # Partial capture is never a success: the debt is named and travels with the run.
        failure = (failure + '; ' if failure else '') + 'capture_cleanup_unconfirmed: ' + (
            'readers still own ' + ','.join(cleanup['readers_alive']) if cleanup['readers_alive']
            else cleanup['error'] or 'process tree not proven gone')
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
            'duration_seconds': round(time.monotonic() - started, 3), **streams,
            **({'cleanup': cleanup} if terminated or not cleanup['confirmed'] else {})}


class EvidenceInspector:
    def __init__(self, artifacts, policy=None, interpreter=None):
        self.artifacts = artifacts
        self.policy = parse_policy(policy) if policy is not None else packaged_policy()
        # Verified at snapshot time (before any child), so a missing interpreter is a clear refusal.
        self._interpreter = interpreter

    # Injection seams (INV-ISOLATED-WORKER-001): a backend may name another trusted interpreter,
    # replay context and capture. Authorization, classification, binding and archival stay here.
    def _trusted(self, candidate):
        return trusted_interpreter(candidate)

    def _python(self):
        return sys.version.split()[0]

    def _replay(self, argv, cwd, timeout, max_bytes, env):
        return _capture(argv, cwd, timeout, max_bytes, env)

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

    def inspect_command(self, claim, cwd, remaining_seconds, environment=None, interpreter=None):
        # Authorization is decided on the claim exactly as written; the interpreter substitution
        # below never takes part in it (review-contract-001).
        if not authorized(claim['argv'], self.policy):
            return {'state': 'not_checked', 'cause': 'command is not an authorized replay prefix; a claim is not authority'}
        per_command = min(self.policy['replay']['per_command_seconds'], remaining_seconds)
        if per_command <= 0:
            return {'state': 'not_checked', 'cause': 'aggregate replay budget exhausted'}
        finite_positive(per_command, 'replay deadline', self.policy['replay']['total_seconds'])
        interpreter = self._trusted(interpreter if interpreter is not None else self._interpreter)
        effective, transformation = replay_argv(claim['argv'], interpreter)
        runs = []
        for _ in range(self.policy['replay']['replays_per_claim']):
            run = self._replay(effective, str(Path(cwd).resolve()), per_command, self.policy['replay']['max_output_bytes'],
                               dict(environment) if environment is not None else replay_environment(cwd=cwd))
            runs.append(self._archive(run))
            if run.get('failure'):
                break
        state, cause = classify_replays(runs, claim['expected_exit'])
        return {'state': state, 'cause': cause, 'runs': runs, 'original_argv': list(claim['argv']),
                'replay_argv': effective, 'argv_identical': effective == list(claim['argv']),
                'argv_transformation': transformation, 'interpreter': str(interpreter)}

    def snapshot(self, cwd=None):
        """One verification context per workspace: its digest is part of the inspection identity and
        the same values are what every replay runs under (review, PR #54: names alone let a changed
        value reuse a pass). The interpreter is verified here, before any child exists."""
        interpreter = trusted_interpreter(self._interpreter)
        environment = replay_environment(cwd=cwd)
        identity = {'policy_hash': self.policy['policy_hash'], 'environment_names': sorted(environment),
                    'environment_digest': digest(sorted(environment.items())),
                    'interpreter': str(interpreter), 'cwd': str(Path(cwd).resolve()) if cwd is not None else None,
                    'tool': {'python': platform.python_version(), 'executable_digest': digest(str(interpreter)),
                             'implementation': platform.python_implementation()},
                    'platform': platform.platform()}
        return {'identity': identity, 'environment': environment, 'interpreter': str(interpreter)}

    def identity(self, cwd=None):
        return self.snapshot(cwd)['identity']

    def inspect(self, claims, cwd, binding, environment=None, interpreter=None):
        """Inspect every claim in one explicit context; the budget is enforced, never assumed.

        `environment` and `interpreter` are the snapshot the caller keyed the inspection by; every
        replay runs under exactly them, whatever the parent process's environment has become since.
        """
        root = Path(cwd)
        if not root.is_dir():
            return {'context': {**binding, 'cwd': str(root)}, 'policy_hash': self.policy['policy_hash'], 'findings': [
                {'claim': None, 'state': 'error', 'cause': 'workspace directory does not exist'}]}
        environment = dict(environment) if environment is not None else replay_environment(cwd=root)
        interpreter = self._trusted(interpreter if interpreter is not None else self._interpreter)
        context = {**binding, 'cwd': str(root.resolve()), 'environment': sorted(environment),
                   'environment_digest': digest(sorted(environment.items())), 'python': self._python(),
                   'interpreter': str(interpreter), 'pythonpath': environment.get('PYTHONPATH')}
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
                result = self.inspect_command(claim, root, deadline - time.monotonic(), environment, interpreter)
            findings.append({'claim': claim, **result})
        return {'context': context, 'policy_hash': self.policy['policy_hash'], 'findings': findings,
                'inspection_id': digest([context, self.policy['policy_hash'], [f['claim'] for f in findings]])}
