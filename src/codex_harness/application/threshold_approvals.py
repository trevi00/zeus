"""Exact-value threshold approvals: bound to what was assessed, consumed once, applied by generation.

An assessed review says two independent actors accepted one calculated proposal. This module
turns that into an approval record bound to the exact name, current value, proposed value,
policy revision, evidence hash, corpus hash, reviewers, issuing actor, target environment and
expiry (INV-THRESHOLD-APPROVAL-001). Applying it is a conditional transition: the applied Git
policy must move exactly that name from exactly that current value to exactly that proposed
value on top of exactly that previous revision, before expiry, in that environment, and only
once. Anything else is refused and recorded; nothing is ever applied by default or by
existence of a file. This module never writes the active definition; it certifies one change.
"""
import re
from datetime import datetime, timedelta, timezone

from codex_harness.domain.model import ContractError, digest, require, utcnow
from codex_harness.domain.threshold_proposals import REGISTRY
from codex_harness.domain.threshold_replay import finite_number

BUCKET = 'threshold_approvals'
EVENTS = 'threshold_approval_events'
STATES = ('issued', 'consumed', 'revoked', 'expired', 'missing', 'corrupt', 'unreadable')
ENVIRONMENT = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}\Z')
REVISION = re.compile(r'[0-9a-f]{40}\Z')
MAX_TTL_SECONDS = 30 * 24 * 3600


def _time(value, name):
    require(type(value) is str, f'{name} must be ISO-8601 text')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ContractError(f'{name} is not ISO-8601') from None
    require(parsed.tzinfo is not None, f'{name} must carry a timezone')
    return parsed


def parse_applied_policy(document):
    """The change a consumer claims to have made: previous and applied Git policy, both exact."""
    require(isinstance(document, dict) and set(document) == {'previous_revision', 'previous_values', 'revision',
                                                              'values', 'environment'},
            'Applied policy must carry previous_revision, previous_values, revision, values and environment')
    for name in ('previous_revision', 'revision'):
        require(type(document[name]) is str and REVISION.fullmatch(document[name]), f'{name} must be a Git commit hash')
    for name in ('previous_values', 'values'):
        values = document[name]
        require(isinstance(values, dict) and set(values) <= set(REGISTRY)
                and all(finite_number(v) for v in values.values()), f'{name} must map registered names to finite numbers')
    require(type(document['environment']) is str and ENVIRONMENT.fullmatch(document['environment']),
            'environment must be a lowercase token')
    return document


class ThresholdApprovals:
    def __init__(self, store, artifacts):
        self.store, self.artifacts = store, artifacts

    def _event(self, tx, approval_id, kind, **details):
        sequence = 1 + sum(row['approval_id'] == approval_id for row in tx.scan(EVENTS))
        event = {'id': digest([approval_id, sequence]), 'approval_id': approval_id, 'sequence': sequence,
                 'kind': kind, 'at': utcnow(), **details}
        tx.put(EVENTS, event['id'], event)
        return event

    def issue(self, request_id, *, actor, environment, ttl_seconds, now=None):
        """Bind an assessed request to one exact change. Idempotent for the same binding."""
        require(actor == 'conductor', 'Only the conductor issues threshold approvals')
        require(type(environment) is str and ENVIRONMENT.fullmatch(environment), 'environment must be a lowercase token')
        require(type(ttl_seconds) is int and 0 < ttl_seconds <= MAX_TTL_SECONDS, 'ttl_seconds out of range')
        now = now or datetime.now(timezone.utc)
        with self.store.transaction() as tx:
            request = tx.get('threshold_review_requests', request_id)
            require(request is not None and request['status'] == 'assessed', 'Assessed threshold review required')
            reviews = request['reviews']
            actors = [review['actor'] for review in reviews]
            require(actors == ['lead:improvement', 'conductor'] and all(review['result']['accepted'] is True
                    and not review['result'].get('blocked') and not review['result'].get('inspection_blocked')
                    for review in reviews), 'Both independent assessments must have accepted')
            row = tx.get('threshold_proposals', request['row_id'])
            require(row is not None and digest(row) == request['binding'], 'Assessed record changed since review')
            proposal = row['proposal']
            require(proposal['suggested'] is not None and proposal['reference_accepted'],
                    'Only a reference-accepted suggestion can be approved')
            require(finite_number(proposal['current']) and finite_number(proposal['suggested'])
                    and proposal['suggested'] != proposal['current'], 'Approval requires a finite, different value')
            evidence = self.artifacts.document(row['evidence_ref'])
            require(proposal in evidence['proposals'], 'Evaluation evidence no longer contains this proposal')
            binding = {'kind': 'threshold-approval-v1', 'request_id': request_id, 'request_binding': request['binding'],
                       'name': proposal['name'], 'current': proposal['current'], 'proposed': proposal['suggested'],
                       'policy_revision': proposal['policy_revision'], 'evidence_ref': row['evidence_ref'],
                       'corpus_hash': proposal['corpus_hash'], 'registry_hash': proposal['registry_hash'],
                       'reviews': [{'actor': r['actor'], 'decision_id': r['decision_id'], 'generation': r['generation']}
                                   for r in reviews],
                       'issued_by': actor, 'environment': environment}
            approval_id = digest(binding)
            existing = tx.get(BUCKET, approval_id)
            if existing is not None:
                return existing
            approval = {**binding, 'id': approval_id, 'status': 'issued', 'issued_at': now.isoformat(),
                        'expires_at': (now + timedelta(seconds=ttl_seconds)).isoformat(),
                        'application': None, 'authority': 'certifies one exact policy change; never writes the definition'}
            tx.put(BUCKET, approval_id, approval)
            self._event(tx, approval_id, 'issued', environment=environment, expires_at=approval['expires_at'])
            return approval

    def _check(self, approval, applied, now):
        if approval['status'] != 'issued':
            return 'approval is ' + approval['status']
        if now >= _time(approval['expires_at'], 'expires_at'):
            return 'approval expired'
        if applied['environment'] != approval['environment']:
            return 'environment differs from the approved target'
        if applied['previous_revision'] != approval['policy_revision']:
            return 'previous policy revision differs from the assessed one'
        name = approval['name']
        if applied['previous_values'].get(name) != approval['current']:
            return 'previous value differs from the approved current value'
        if applied['values'].get(name) != approval['proposed']:
            return 'applied value differs from the approved proposed value'
        if type(applied['values'][name]) is not type(approval['proposed']):
            return 'applied value type differs from the approved one'
        unrelated = {k for k in set(applied['values']) | set(applied['previous_values'])
                     if k != name and applied['values'].get(k) != applied['previous_values'].get(k)}
        if unrelated:
            return 'the change touches other thresholds: ' + ', '.join(sorted(unrelated))
        if applied['revision'] == applied['previous_revision']:
            return 'applied revision equals the previous revision'
        return None

    def consume(self, approval_id, applied_policy, now=None):
        """Certify one application: the conditional transition issued -> consumed, exactly once."""
        applied = parse_applied_policy(applied_policy)
        now = now or datetime.now(timezone.utc)
        with self.store.transaction() as tx:
            approval = tx.get(BUCKET, approval_id)
            require(approval is not None, 'Unknown threshold approval')
            reason = self._check(approval, applied, now)
            if reason is not None:
                break_out = reason
            else:
                break_out = None
                generation = 1 + sum(row['status'] == 'consumed' and row['name'] == approval['name']
                                     for row in tx.scan(BUCKET))
                approval.update(status='consumed', application={'revision': applied['revision'], 'generation': generation,
                                                                'environment': applied['environment'],
                                                                'at': now.isoformat()})
                tx.put(BUCKET, approval_id, approval)
                self._event(tx, approval_id, 'consumed', applied_revision=applied['revision'], generation=generation)
        if break_out is not None:
            # The refusal is its own committed record; the refused transaction changed nothing.
            with self.store.transaction() as tx:
                self._event(tx, approval_id, 'refused', reason=break_out, applied_revision=applied['revision'])
            raise ContractError('Threshold approval cannot certify this change: ' + break_out)
        return approval

    def revoke(self, approval_id, *, actor, reason):
        require(actor in {'conductor', 'lead:improvement'}, 'Only a reviewer revokes an approval')
        require(type(reason) is str and bool(reason.strip()), 'Revocation reason required')
        with self.store.transaction() as tx:
            approval = tx.get(BUCKET, approval_id)
            require(approval is not None, 'Unknown threshold approval')
            if approval['status'] == 'revoked':
                return approval
            require(approval['status'] == 'issued', 'Only an issued approval can be revoked; a consumed one is history')
            approval.update(status='revoked', revocation={'actor': actor, 'reason': reason, 'at': utcnow()})
            tx.put(BUCKET, approval_id, approval)
            self._event(tx, approval_id, 'revoked', actor=actor, reason=reason)
            return approval

    def inspect(self, approval_id, now=None):
        now = now or datetime.now(timezone.utc)
        try:
            with self.store.transaction() as tx:
                approval = tx.get(BUCKET, approval_id)
        except Exception as exc:
            return {'id': approval_id, 'state': 'unreadable', 'reason': type(exc).__name__}
        if approval is None:
            return {'id': approval_id, 'state': 'missing'}
        try:
            require(approval.get('status') in {'issued', 'consumed', 'revoked'} and finite_number(approval.get('current'))
                    and finite_number(approval.get('proposed')) and approval.get('name') in REGISTRY,
                    'approval record is malformed')
            expires = _time(approval['expires_at'], 'expires_at')
        except ContractError as exc:
            return {'id': approval_id, 'state': 'corrupt', 'reason': str(exc)}
        state = approval['status']
        if state == 'issued' and now >= expires:
            state = 'expired'
        return {'id': approval_id, 'state': state, 'name': approval['name'], 'current': approval['current'],
                'proposed': approval['proposed'], 'policy_revision': approval['policy_revision'],
                'environment': approval['environment'], 'expires_at': approval['expires_at'],
                'application': approval.get('application'), 'authority': approval['authority']}
