"""Durable breaker admission: conditional transitions in one store transaction, fenced by generation.

Admission is granted only by a committed state transition, so a store that cannot write never
returns an admitted token. Every token names the generation it was granted under; a result
reported against another generation is recorded as stale and changes nothing. Corrupt,
missing and unreadable state are distinct from a new breaker, and none of them is quietly
`closed`. A closed breaker admits calls; it never authorizes acceptance, graduation or deployment.
"""
from datetime import datetime, timedelta, timezone

from codex_harness.domain.breaker import (
    RESULTS,
    breaker_key,
    decide,
    fold_failures,
    new_state,
    parse_policy,
    parse_state,
)
from codex_harness.domain.model import ContractError, digest, require, utcnow

BUCKET = 'breakers'
EVENTS = 'breaker_events'
NOTICES = 'breaker_notices'
POLICIES = 'breaker_policies'
DEFAULT_POLICY = {'version': 1, 'failure_threshold': 3, 'window_seconds': 600, 'cooldown_seconds': 120,
                  'probe_ttl_seconds': 300, 'max_history': 50, 'revision': 'unversioned'}


def _now(now):
    return now if now is not None else datetime.now(timezone.utc)


class _Corrupt(Exception):
    def __init__(self, key, raw, reason):
        super().__init__(reason)
        self.key, self.raw, self.reason = key, raw, reason


class Breaker:
    def __init__(self, store, policy_document=DEFAULT_POLICY):
        self.store = store
        self.policy = parse_policy(policy_document)

    def _event(self, tx, key, generation, kind, **details):
        sequence = 1 + sum(row['key'] == key for row in tx.scan(EVENTS))
        event = {'id': digest([key, sequence]), 'key': key, 'sequence': sequence, 'generation': generation,
                 'kind': kind, 'at': utcnow(), **details}
        tx.put(EVENTS, event['id'], event)
        return event

    def _load(self, tx, key):
        raw = tx.get(BUCKET, key)
        if raw is None:
            return new_state(key, self.policy), 'new'
        try:
            return parse_state(raw), 'stored'
        except ContractError as exc:
            raise _Corrupt(key, raw, str(exc)) from exc

    def _repair_required(self, corrupt):
        # The notice is committed on its own: the refused transaction rolled back with nothing else in it.
        notice = {'id': digest([corrupt.key, 'corrupt', corrupt.reason]), 'key': corrupt.key,
                  'reason': corrupt.reason, 'excerpt': repr(corrupt.raw)[:2000], 'at': utcnow()}
        with self.store.transaction() as tx:
            if tx.get(NOTICES, notice['id']) is None:
                tx.put(NOTICES, notice['id'], notice)
        raise ContractError('Breaker state requires repair: ' + corrupt.reason)

    def admit(self, key, lease, now=None):
        """Return an admission token or raise; the token exists only if the transition committed."""
        require(type(key) is str and key.startswith('breaker:'), 'Breaker key required')
        require(isinstance(lease, dict) and type(lease.get('id')) is str and type(lease.get('generation')) is int
                and type(lease.get('attempt')) is int, 'Admission requires a typed execution lease')
        now = _now(now)
        try:
            return self._admit(key, lease, now)
        except _Corrupt as corrupt:
            self._repair_required(corrupt)

    def _admit(self, key, lease, now):
        with self.store.transaction() as tx:
            state, origin = self._load(tx, key)
            decision, reason = decide(state, now, self.policy)
            require(decision != 'refuse', f'Breaker refuses admission for {key}: {reason}')
            probe = decision in {'probe', 'reclaim'}
            if probe:
                previous = state['reservation']
                generation = state['generation'] + 1
                state.update(state='half_open', generation=generation,
                             reservation={'owner': lease.get('lease_owner'), 'task_id': lease['id'],
                                          'generation': lease['generation'], 'attempt': lease['attempt'],
                                          'breaker_generation': generation,
                                          'expires_at': (now + timedelta(
                                              seconds=self.policy['probe_ttl_seconds'])).isoformat()})
                state['policy_hash'], state['policy_revision'] = self.policy['policy_hash'], self.policy['revision']
                tx.put(BUCKET, key, state)
                self._event(tx, key, state['generation'], 'probe_reserved', reason=reason, origin=origin,
                            reclaimed_from=previous)
            elif origin == 'new':
                tx.put(BUCKET, key, state)
            token = {'key': key, 'generation': state['generation'], 'probe': probe,
                     'policy_hash': self.policy['policy_hash'], 'policy_revision': self.policy['revision'],
                     'task_id': lease['id'], 'task_generation': lease['generation'], 'attempt': lease['attempt'],
                     'admitted_at': now.isoformat()}
            self._event(tx, key, state['generation'], 'admitted', probe=probe, reason=reason, origin=origin,
                        task_id=lease['id'], attempt=lease['attempt'])
            return token

    def report(self, token, result, now=None):
        """Apply one result to the generation it was admitted under; anything else is stale."""
        require(isinstance(token, dict) and type(token.get('generation')) is int and type(token.get('key')) is str,
                'Breaker report requires an admission token')
        require(result in RESULTS, 'Unknown breaker result')
        now = _now(now)
        try:
            return self._report(token, result, now)
        except _Corrupt as corrupt:
            self._repair_required(corrupt)

    def _report(self, token, result, now):
        with self.store.transaction() as tx:
            state, _ = self._load(tx, key := token['key'])
            if state['generation'] != token['generation']:
                self._event(tx, key, state['generation'], 'stale_result', result=result,
                            token_generation=token['generation'], task_id=token.get('task_id'))
                return {'applied': False, 'reason': 'stale_generation', 'state': state['state'],
                        'generation': state['generation']}
            if token['probe']:
                # Only the slot holder's result settles the probe; unknown releases the slot without a verdict.
                if result == 'success':
                    state.update(state='closed', failures=[], opened_at=None, reservation=None,
                                 generation=state['generation'] + 1)
                elif result == 'failure':
                    state.update(state='open', opened_at=now.isoformat(), reservation=None,
                                 generation=state['generation'] + 1)
                else:
                    state.update(reservation=None)
            elif result == 'failure':
                failure = {'id': digest([key, token['task_id'], token['attempt'], token['admitted_at']]),
                           'at': now.isoformat()}
                failures = fold_failures(state['failures'] + [failure], now, self.policy['window_seconds'])
                state['failures'] = failures[-self.policy['max_history']:]
                if len(state['failures']) >= self.policy['failure_threshold']:
                    state.update(state='open', opened_at=now.isoformat(), generation=state['generation'] + 1)
            tx.put(BUCKET, key, state)
            self._event(tx, key, state['generation'], 'result', result=result, probe=token['probe'],
                        state=state['state'], task_id=token.get('task_id'))
            return {'applied': True, 'state': state['state'], 'generation': state['generation']}

    def inspect(self, key, now=None):
        now = _now(now)
        try:
            with self.store.transaction() as tx:
                raw = tx.get(BUCKET, key)
        except Exception as exc:  # store failure is its own state, never availability
            return {'key': key, 'state': 'unreadable', 'admits': False, 'reason': type(exc).__name__}
        if raw is None:
            return {'key': key, 'state': 'missing', 'admits': True,
                    'note': 'a breaker with no record is new; it admits but proves nothing'}
        try:
            state = parse_state(raw)
        except ContractError as exc:
            return {'key': key, 'state': 'corrupt', 'admits': False, 'reason': str(exc)}
        decision, reason = decide(state, now, self.policy)
        return {'key': key, 'state': state['state'], 'generation': state['generation'], 'admits': decision != 'refuse',
                'decision': decision, 'reason': reason, 'failures_in_window': len(
                    fold_failures(state['failures'], now, self.policy['window_seconds'])),
                'reservation': state['reservation'], 'policy_revision': state.get('policy_revision'),
                'authority': 'admission only; never acceptance, graduation or deployment'}

    def update_policy(self, document, *, revision):
        """Validate on write, store, then read back and compare: applied means the effective value changed."""
        policy = parse_policy({**document, 'revision': revision})
        with self.store.transaction() as tx:
            tx.put(POLICIES, revision, {'id': revision, 'policy': policy, 'at': utcnow()})
        with self.store.transaction() as tx:
            stored = tx.get(POLICIES, revision)
        applied = stored is not None and parse_policy({k: stored['policy'][k] for k in policy if k != 'policy_hash'}) == policy
        require(applied, 'Breaker policy was not applied as written')
        self.policy = policy
        return {'applied': True, 'revision': revision, 'policy_hash': policy['policy_hash']}


def result_of(result):
    """Map a runner result to a breaker verdict: provider failures count, everything unproven is unknown."""
    if not isinstance(result, dict):
        return 'unknown'
    failure = result.get('failure')
    if failure:
        return 'failure' if str(failure.get('cause', '')).startswith('codex-provider-') else 'unknown'
    if result.get('inspection_blocked') or result.get('interrupted') or result.get('answer') is None:
        return 'unknown'
    return 'success'


def result_of_exception(error):
    """A transport that died or timed out is a provider failure; anything else proves nothing."""
    return 'failure' if isinstance(error, ContractError) and str(error).startswith('Codex') else 'unknown'


__all__ = ['Breaker', 'DEFAULT_POLICY', 'breaker_key', 'result_of', 'result_of_exception']
