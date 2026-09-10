"""Evidence claims, inspection states and replay authority as data (INV-EVIDENCE-001).

The upstream observer returned CLEAN for directories, empty evidence, unreplayed claims and
permission errors, confirmed fabrication for a file it looked up from the wrong cwd, and
executed the command the model wrote into its own envelope. Here a claim is typed, an
inspection result is one of eight named states with a cause, a model-written command is a
claim and never an authorization, and only a Git-defined policy prefix may be replayed.
"""
import math
import os
import re
import shlex

from codex_harness.domain.model import ContractError, digest, require

STATES = ('checked', 'not_checked', 'missing', 'unknown', 'error', 'replay_failed', 'flake_pattern',
          'verified_mismatch')
KINDS = ('file', 'command')
POLICY_KEYS = frozenset({'version', 'replay', 'files'})
REPLAY_KEYS = frozenset({'allowed_argv_prefixes', 'per_command_seconds', 'total_seconds', 'max_claims',
                         'max_output_bytes', 'replays_per_claim'})
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
MAX_ARGV = 64


def _bounded_int(value, name, low, high):
    require(type(value) is int and low <= value <= high, f'{name} must be an integer in [{low}, {high}]')
    return value


def parse_policy(document):
    """Closed replay/file policy; every bound is finite, positive and capped."""
    require(isinstance(document, dict) and set(document) == POLICY_KEYS, 'Evidence policy must carry version, replay, files')
    require(type(document['version']) is int and document['version'] == 1, 'Unknown evidence policy version')
    replay = document['replay']
    require(isinstance(replay, dict) and set(replay) == REPLAY_KEYS, 'Evidence replay policy fields')
    prefixes = replay['allowed_argv_prefixes']
    require(isinstance(prefixes, list) and prefixes and all(
        isinstance(p, list) and p and all(type(t) is str and t and '\x00' not in t for t in p) for p in prefixes),
        'allowed_argv_prefixes must be non-empty lists of argv tokens')
    policy = {'version': 1,
              'replay': {'allowed_argv_prefixes': [list(p) for p in prefixes],
                         'per_command_seconds': _bounded_int(replay['per_command_seconds'], 'per_command_seconds', 1, 3600),
                         'total_seconds': _bounded_int(replay['total_seconds'], 'total_seconds', 1, 7200),
                         'max_claims': _bounded_int(replay['max_claims'], 'max_claims', 1, 256),
                         'max_output_bytes': _bounded_int(replay['max_output_bytes'], 'max_output_bytes', 1024, 8 * 1024 * 1024),
                         'replays_per_claim': _bounded_int(replay['replays_per_claim'], 'replays_per_claim', 1, 3)},
              'files': {'max_bytes': _bounded_int(document['files'].get('max_bytes') if isinstance(document['files'], dict) else None,
                                                  'files.max_bytes', 1, 64 * 1024 * 1024)}}
    require(policy['replay']['per_command_seconds'] <= policy['replay']['total_seconds'],
            'per_command_seconds cannot exceed total_seconds')
    policy['policy_hash'] = digest({k: v for k, v in policy.items()})
    return policy


def parse_claim(raw):
    """A typed evidence claim. Free text is a command claim of expected exit 0, nothing more."""
    if isinstance(raw, str):
        # Free text is split the way the host shell would tokenize it; POSIX rules would eat the
        # backslashes of a Windows path and turn the claim into a different command.
        posix = os.name != 'nt'
        try:
            argv = shlex.split(raw, posix=posix)
        except ValueError as exc:
            raise ContractError('Unparseable command claim: ' + str(exc)) from exc
        if not posix:
            argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in ('"', "'") else a for a in argv]
        require(argv, 'Empty command claim')
        return parse_claim({'kind': 'command', 'argv': argv, 'expected_exit': 0, 'origin': 'free_text', 'text': raw})
    require(isinstance(raw, dict) and raw.get('kind') in KINDS, 'Evidence claim must name a kind')
    if raw['kind'] == 'command':
        require(set(raw) <= {'kind', 'argv', 'expected_exit', 'origin', 'text'}, 'Unknown command claim fields')
        argv = raw.get('argv')
        require(isinstance(argv, list) and 0 < len(argv) <= MAX_ARGV
                and all(type(a) is str and a and '\x00' not in a for a in argv), 'Command claim argv must be non-empty text tokens')
        expected = raw.get('expected_exit', 0)
        require(type(expected) is int and 0 <= expected <= 255, 'expected_exit must be an exit status')
        return {'kind': 'command', 'argv': list(argv), 'expected_exit': expected,
                'origin': raw.get('origin', 'structured'), 'id': digest(['command', argv, expected])}
    require(set(raw) <= {'kind', 'path', 'sha256', 'range', 'origin'}, 'Unknown file claim fields')
    path = raw.get('path')
    require(type(path) is str and path and '\x00' not in path and not path.startswith(('/', '\\'))
            and not re.match(r'[A-Za-z]:', path) and '..' not in path.replace('\\', '/').split('/'),
            'File claim path must be relative and inside the workspace')
    sha = raw.get('sha256')
    require(sha is None or (type(sha) is str and HEX64.fullmatch(sha)), 'File claim sha256 must be 64 hex')
    span = raw.get('range')
    if span is not None:
        require(isinstance(span, dict) and set(span) == {'start', 'end'} and type(span['start']) is int
                and type(span['end']) is int and 1 <= span['start'] <= span['end'], 'File claim range must be 1-based lines')
    return {'kind': 'file', 'path': path.replace('\\', '/'), 'sha256': sha, 'range': span,
            'origin': raw.get('origin', 'structured'), 'id': digest(['file', path, sha, span])}


def authorized(argv, policy):
    """A model-written command is a claim; only a policy prefix grants replay."""
    return any(len(argv) >= len(prefix) and argv[:len(prefix)] == prefix
               for prefix in policy['replay']['allowed_argv_prefixes'])


def classify_replays(runs, expected_exit):
    """Runs are replay attempts of one command in one context: failures first, then agreement."""
    require(isinstance(runs, list) and runs, 'At least one replay run is required to classify')
    failed = [run for run in runs if run.get('failure')]
    if failed:
        return 'replay_failed', 'attempt ' + str(runs.index(failed[0]) + 1) + ': ' + failed[0]['failure']
    exits = {run['returncode'] for run in runs}
    if len(exits) > 1:
        return 'flake_pattern', 'exit statuses differ between identical replays: ' + ', '.join(map(str, sorted(exits)))
    exit_status = exits.pop()
    if exit_status == expected_exit:
        return 'checked', f'exit {exit_status} as claimed on {len(runs)} identical replay(s)'
    return 'verified_mismatch', f'exit {exit_status}, claimed {expected_exit}'


def denominator(findings):
    counts = {state: 0 for state in STATES}
    for finding in findings:
        require(finding.get('state') in STATES, 'Unknown inspection state')
        counts[finding['state']] += 1
    counts['claims'] = len(findings)
    return counts


def verdict(findings):
    """Never CLEAN: either every claim was checked and agreed, or the inspection is incomplete."""
    counts = denominator(findings)
    if counts['claims'] == 0:
        return 'no_claims'
    return 'all_checked' if counts['checked'] == counts['claims'] else 'incomplete'


def finite_positive(value, name, ceiling):
    require(type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value)
            and 0 < value <= ceiling, f'{name} must be finite, positive and at most {ceiling}')
    return value
