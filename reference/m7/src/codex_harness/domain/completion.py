"""Completion verdicts as bound evidence, never caller self-report (INV-COMPLETION-001).

A verdict proves something only when it names the execution it judged (task, generation,
attempt), the spec revision, the evaluation artifact, the runner invocation receipt and the
reviewer, and when its scenario denominator is explicit. The upstream selector accepted any
event with a verdict string and a timestamp; this schema is closed and every field is typed.
"""
import re
from datetime import datetime, timedelta, timezone

from codex_harness.domain.model import ContractError, canonical, digest

SCHEMA_VERSION = 1
EVENT = 'completion.verdict'
VERDICTS = ('approved', 'iterate', 'escalate')
REVIEWER_KINDS = ('model', 'human')
KEYS = frozenset({'schema_version', 'event', 'verdict', 'target', 'spec_revision', 'evaluation_artifact',
                  'runner_receipt', 'reviewer', 'scenarios', 'observed_at'})
TARGET_KEYS = frozenset({'task_id', 'generation', 'attempt'})
RECEIPT_KEYS = frozenset({'id', 'task_id', 'generation', 'attempt', 'digest'})
REVIEWER_KEYS = frozenset({'actor', 'kind'})
SCENARIO_KEYS = frozenset({'expected', 'passed', 'excluded'})
EXCLUSION_KEYS = frozenset({'id', 'approved_by', 'revision', 'reason'})
IDENTITY_KEYS = ('schema_version', 'event', 'verdict', 'target', 'spec_revision', 'evaluation_artifact',
                 'runner_receipt', 'reviewer', 'scenarios')
MAX_BYTES = 64 * 1024
FUTURE_SKEW = timedelta(seconds=60)
HEX40 = re.compile(r'^[0-9a-f]{40}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')


def _fail(reason):
    raise ContractError('Completion verdict rejected: ' + reason)


def _keys(value, expected, name):
    if not isinstance(value, dict) or set(value) != expected:
        _fail(f'{name} must carry exactly {sorted(expected)}')
    return value


def _text(value, name):
    if type(value) is not str or not value.strip():
        _fail(f'{name} must be a non-empty string')
    return value


def _count(value, name):
    if type(value) is not int or value < 1:
        _fail(f'{name} must be a positive integer')
    return value


def _hex(value, pattern, name):
    if type(value) is not str or not pattern.match(value):
        _fail(f'{name} must be lowercase hex of the declared length')
    return value


def _names(value, name):
    if not isinstance(value, list) or any(type(v) is not str or not v.strip() for v in value):
        _fail(f'{name} must be a list of non-empty strings')
    if len(set(value)) != len(value):
        _fail(f'{name} must not repeat a scenario')
    return value


def parse_timestamp(value, name='observed_at'):
    """Aware ISO-8601 text only; numbers (NaN included) and naive values are rejected."""
    if type(value) is not str:
        _fail(f'{name} must be ISO-8601 text')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        _fail(f'{name} is not ISO-8601')
    if parsed.tzinfo is None:
        _fail(f'{name} must carry a timezone')
    return parsed


def parse_verdict(record, now=None):
    """Validate one completion verdict record and return its normalized, identified form.

    `now` bounds the observed time (a verdict from the future is rejected); pass None to skip
    that check when re-reading stored rows.
    """
    _keys(record, KEYS, 'Completion verdict')
    if type(record['schema_version']) is not int or record['schema_version'] != SCHEMA_VERSION:
        _fail(f'schema_version must be {SCHEMA_VERSION}')
    if record['event'] != EVENT:
        _fail(f'event must be {EVENT}')
    if type(record['verdict']) is not str or record['verdict'] not in VERDICTS:
        _fail(f'verdict must be one of {VERDICTS}')
    target = _keys(record['target'], TARGET_KEYS, 'target')
    _text(target['task_id'], 'target.task_id')
    _count(target['generation'], 'target.generation')
    _count(target['attempt'], 'target.attempt')
    _hex(record['spec_revision'], HEX40, 'spec_revision')
    artifact = record['evaluation_artifact']
    if type(artifact) is not str or not artifact.startswith('sha256:') or not HEX64.match(artifact[7:]):
        _fail('evaluation_artifact must be a sha256: reference')
    receipt = _keys(record['runner_receipt'], RECEIPT_KEYS, 'runner_receipt')
    _text(receipt['id'], 'runner_receipt.id')
    _hex(receipt['digest'], HEX64, 'runner_receipt.digest')
    # Cross-target is derived from the receipt, never taken from a caller flag.
    if any(receipt[key] != target[key] or type(receipt[key]) is not type(target[key]) for key in TARGET_KEYS):
        _fail('runner_receipt targets a different execution than the verdict')
    reviewer = _keys(record['reviewer'], REVIEWER_KEYS, 'reviewer')
    _text(reviewer['actor'], 'reviewer.actor')
    if reviewer['kind'] not in REVIEWER_KINDS:
        _fail(f'reviewer.kind must be one of {REVIEWER_KINDS}')
    scenarios = _keys(record['scenarios'], SCENARIO_KEYS, 'scenarios')
    expected = _names(scenarios['expected'], 'scenarios.expected')
    passed = _names(scenarios['passed'], 'scenarios.passed')
    if not set(passed) <= set(expected):
        _fail('scenarios.passed must be a subset of scenarios.expected')
    if not isinstance(scenarios['excluded'], list):
        _fail('scenarios.excluded must be a list')
    excluded = []
    for item in scenarios['excluded']:
        _keys(item, EXCLUSION_KEYS, 'scenarios.excluded[]')
        _text(item['id'], 'scenarios.excluded[].id')
        if item['id'] not in expected or item['id'] in passed:
            _fail('an exclusion must name an expected scenario that did not pass')
        _text(item['approved_by'], 'scenarios.excluded[].approved_by')
        _hex(item['revision'], HEX40, 'scenarios.excluded[].revision')
        _text(item['reason'], 'scenarios.excluded[].reason')
        excluded.append(item['id'])
    if len(set(excluded)) != len(excluded):
        _fail('scenarios.excluded must not repeat a scenario')
    observed = parse_timestamp(record['observed_at'])
    if now is not None and observed > now + FUTURE_SKEW:
        _fail('observed_at is in the future')
    if len(canonical(record).encode('utf-8')) > MAX_BYTES:
        _fail(f'record exceeds {MAX_BYTES} bytes')
    # An empty denominator is not a full pass: nothing was checked.
    complete = bool(expected) and set(expected) == set(passed) | set(excluded)
    identity = digest([record[key] for key in IDENTITY_KEYS])
    return {**{key: record[key] for key in KEYS}, 'id': identity, 'complete': complete,
            'observed_at': observed.astimezone(timezone.utc).isoformat()}


def latest(verdicts):
    """The current verdict is the last recorded one; observed_at never orders records."""
    return max(verdicts, key=lambda row: row['sequence']) if verdicts else None
