"""Resolve packaged Git policy for native consumers; no runtime mutation authority."""
import json
from pathlib import Path

from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.skill_ranking import FULL_BODY_MIN_SCORE
from codex_harness.domain.threshold_proposals import REGISTRY, validate_registry
from codex_harness.domain.threshold_replay import finite_number

POLICY_FILE = Path(__file__).resolve().parents[1] / 'resources/threshold-policy.json'
NATIVE_DEFAULTS = {'skill_match.FULL_BODY_MIN_SCORE': FULL_BODY_MIN_SCORE}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate threshold policy key')
        result[key] = value
    return result


def resolve_policy(text):
    validate_registry()
    require(all(name in REGISTRY and REGISTRY[name].default == value
                for name, value in NATIVE_DEFAULTS.items()), 'Native threshold default differs from registry')
    try:
        policy = json.loads(text, object_pairs_hook=_unique)
    except (ValueError, TypeError) as exc:
        raise ContractError('Invalid threshold policy JSON') from exc
    require(isinstance(policy, dict) and set(policy) == {'version', 'overrides'}
            and type(policy['version']) is int and policy['version'] == 1
            and isinstance(policy['overrides'], dict), 'Invalid threshold policy schema')
    values = dict(NATIVE_DEFAULTS)
    for name, value in policy['overrides'].items():
        # INV-THRESHOLD-POLICY-001: no dormant registry entry or locked invariant is writable.
        require(name in NATIVE_DEFAULTS and name in REGISTRY, 'Unsupported native threshold')
        require(finite_number(value), 'Threshold value must be finite numeric')
        values[name] = value
    return {'values': values, 'definition_hash': digest(text), 'definition': policy}


def effective_policy():
    try:
        return resolve_policy(POLICY_FILE.read_text(encoding='utf-8'))
    except OSError as exc:
        raise ContractError('Native threshold definition unavailable') from exc
