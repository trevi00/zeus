"""Breaker state machine as typed data: canonical keys, validated policy, fenced generations (INV-BREAKER-001).

The upstream composite breaker composed file paths from aliases, returned an admission bool
that no owner or generation was bound to, let an old holder's success close a slot another
holder had reclaimed, folded histories in input order and accepted booleans as thresholds.
Here every transition is a pure decision over validated state, every admission carries the
generation it was granted under, and failure history folds over unique events by time.
"""
import re
from datetime import datetime, timedelta

from codex_harness.domain.model import ContractError, digest, require

STATES = ('closed', 'open', 'half_open')
RESULTS = ('success', 'failure', 'unknown')
POLICY_KEYS = frozenset({'version', 'failure_threshold', 'window_seconds', 'cooldown_seconds',
                         'probe_ttl_seconds', 'max_history', 'revision'})
PART = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}\Z')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')


def _int(value, name, minimum):
    # `type is int` keeps bool out: True is not a threshold of one.
    require(type(value) is int and value >= minimum, f'{name} must be an integer >= {minimum}')
    return value


def parse_policy(document):
    """Closed policy schema with cross-field bounds, validated on read and on write alike."""
    require(isinstance(document, dict) and set(document) == POLICY_KEYS,
            f'Breaker policy must carry exactly {sorted(POLICY_KEYS)}')
    require(type(document['version']) is int and document['version'] == 1, 'Unknown breaker policy version')
    policy = {'version': 1,
              'failure_threshold': _int(document['failure_threshold'], 'failure_threshold', 1),
              'window_seconds': _int(document['window_seconds'], 'window_seconds', 1),
              'cooldown_seconds': _int(document['cooldown_seconds'], 'cooldown_seconds', 1),
              'probe_ttl_seconds': _int(document['probe_ttl_seconds'], 'probe_ttl_seconds', 1),
              'max_history': _int(document['max_history'], 'max_history', 1)}
    require(policy['failure_threshold'] <= policy['max_history'],
            'failure_threshold cannot exceed the retained history')
    require(policy['probe_ttl_seconds'] <= policy['window_seconds'],
            'probe_ttl_seconds cannot exceed the failure window')
    revision = document['revision']
    require(type(revision) is str and (HEX40.fullmatch(revision) or revision == 'unversioned'),
            'Policy revision must be a Git commit hash or "unversioned"')
    policy['revision'] = revision
    policy['policy_hash'] = digest({k: policy[k] for k in sorted(policy)})
    return policy


def breaker_key(provider, scope):
    """One identity per (provider, scope): typed parts hashed together, never a composed path.

    Parts are exact lowercase tokens; an alias is refused rather than folded, so two spellings
    can never share or split a breaker by accident, and delimiters cannot collide.
    """
    for name, value in (('provider', provider), ('scope', scope)):
        require(type(value) is str and PART.fullmatch(value), f'Breaker {name} must be a lowercase token')
    return 'breaker:' + digest([provider, scope])


def parse_time(value, name):
    require(type(value) is str, f'{name} must be ISO-8601 text')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ContractError(f'{name} is not ISO-8601') from None
    require(parsed.tzinfo is not None, f'{name} must carry a timezone')
    return parsed


def new_state(key, policy):
    return {'id': key, 'state': 'closed', 'generation': 0, 'failures': [], 'opened_at': None,
            'reservation': None, 'policy_hash': policy['policy_hash'], 'policy_revision': policy['revision']}


def parse_state(row):
    """Reject anything that is not a well-formed breaker record; the caller treats it as corrupt."""
    require(isinstance(row, dict) and set(row) >= {'id', 'state', 'generation', 'failures', 'opened_at', 'reservation'},
            'Breaker record lacks required fields')
    require(row['state'] in STATES, 'Unknown breaker state')
    _int(row['generation'], 'generation', 0)
    require(isinstance(row['failures'], list), 'Breaker failure history must be a list')
    for failure in row['failures']:
        require(isinstance(failure, dict) and type(failure.get('id')) is str and bool(failure['id']),
                'Breaker failure entry requires an id')
        parse_time(failure.get('at'), 'failure.at')
    if row['opened_at'] is not None:
        parse_time(row['opened_at'], 'opened_at')
    reservation = row['reservation']
    if reservation is not None:
        require(isinstance(reservation, dict) and set(reservation) == {'owner', 'task_id', 'generation', 'attempt',
                                                                       'breaker_generation', 'expires_at'},
                'Breaker reservation shape')
        _int(reservation['breaker_generation'], 'reservation.breaker_generation', 0)
        parse_time(reservation['expires_at'], 'reservation.expires_at')
    require(row['state'] == 'half_open' or reservation is None, 'Only a half-open breaker holds a reservation')
    return row


def fold_failures(failures, now, window_seconds):
    """Unique failure events inside the window, ordered by time then id: neither duplicates nor
    input order change the count."""
    unique = {}
    for failure in failures:
        unique.setdefault(failure['id'], failure)
    ordered = sorted(unique.values(), key=lambda f: (parse_time(f['at'], 'failure.at'), f['id']))
    start = now - timedelta(seconds=window_seconds)
    return [f for f in ordered if parse_time(f['at'], 'failure.at') > start]


def decide(state, now, policy):
    """Pure admission decision: admit, probe (assign the single slot), reclaim (expired slot) or refuse."""
    if state['state'] == 'closed':
        return 'admit', 'closed'
    if state['state'] == 'open':
        reopen_at = parse_time(state['opened_at'], 'opened_at') + timedelta(seconds=policy['cooldown_seconds'])
        if now < reopen_at:
            return 'refuse', 'open until ' + reopen_at.isoformat()
        return 'probe', 'cooldown elapsed'
    reservation = state['reservation']
    if reservation is None:
        # Half-open without a slot holder is a repaired/released slot, not a free-for-all: one probe.
        return 'probe', 'half-open slot free'
    if now >= parse_time(reservation['expires_at'], 'reservation.expires_at'):
        return 'reclaim', 'probe reservation expired'
    return 'refuse', 'probe in flight'
