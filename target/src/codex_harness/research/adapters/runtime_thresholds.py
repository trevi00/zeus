"""Resolve packaged Git policy for native consumers; no runtime mutation authority.

Layer: adapters
Context: research
Owns: resolve_policy and effective_policy, the packaged native threshold definition (`resources/threshold-policy.json`) checked against the closed registry; it has no runtime mutation authority
Does not own: the registry and its rules (research.domain.threshold_proposals), the Git-bound policy adapter that selects a revision (a later layer), the skill ranking whose default `FULL_BODY_MIN_SCORE` is mirrored here (context)
Entry points: resolve_policy, effective_policy, NATIVE_DEFAULTS, POLICY_FILE, FULL_BODY_MIN_SCORE
Contracts: INV-THRESHOLD-POLICY-001

Moved from M7 `adapters/runtime_thresholds.py` (SOURCE e38aa722) through named rules (DESIGN-s8 §13 V18, A/evidence/rebuild/s8/thresholds-a-move/transcribe.py): R-t0 (`FULL_BODY_MIN_SCORE` is a V9 local constant, equal to context's), R-t2 (`POLICY_FILE` climbs one directory more: `parents[2]`), R-t3 (each name from the target home of the module that defines it); every other statement is M7's. The first paragraph is M7's module docstring.
"""
import json
from pathlib import Path

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest
from codex_harness.kernel.numbers import finite_number
from codex_harness.research.domain.threshold_proposals import REGISTRY, validate_registry

# V18 R-t0: a V9 local published-language constant (context.domain.skills.ranking); a move test pins equality with the owner.
FULL_BODY_MIN_SCORE = 3
POLICY_FILE = Path(__file__).resolve().parents[2] / 'resources/threshold-policy.json'
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
