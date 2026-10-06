"""Seam contracts as typed observations; transforms and directional comparison as data (INV-SEAM-001).

The upstream seam registry returned OK when a partial value map or a prefix strip collapsed two
distinct values, ignored unknown affix options so a no-op affix bypassed the identity guard,
gave HIGH fidelity to extractions that dropped members, compared enums by tag:name so a type
change was invisible, and dropped a second package's same short name. Here a contract's identity
carries stack, package and name; a transform is a closed schema whose effective mapping is
computed over the full input set (passthrough included); fidelity below the policy is BLOCKED,
never OK; and a comparison is advisory until a reviewer approves blocking under a policy revision.
"""
import re

from codex_harness.domain.model import ContractError, digest, require

FIDELITY = ('HIGH', 'LOW', 'UNKNOWN')
VERDICTS = ('OK', 'DRIFT', 'NEEDS_TRANSFORM', 'BLOCKED')
KINDS = ('enum', 'message')
DIRECTIONS = ('producer_to_consumer', 'consumer_to_producer', 'both')
TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_./-]{0,199}\Z')
TRANSFORM_KEYS = {'identity': {'version', 'kind'},
                  'value_map': {'version', 'kind', 'value_map'},
                  'affix': {'version', 'kind', 'strip_prefix', 'strip_suffix', 'add_prefix', 'add_suffix'}}
POLICY_VERSION = 1
# What a check can cover. An extractor declares which of these it actually observed; a policy says
# which an approved spec requires. Anything required but not covered is unverified, never OK.
CHECK_SCOPES = ('member_names', 'member_types', 'member_tags', 'envelope', 'rpc', 'response_types',
                'error_mapping', 'storage', 'execution', 'human_scenario')
COMPARE_SCOPES = {'name': 'member_names', 'type': 'member_types', 'tag': 'member_tags'}


def contract_identity(stack, package, name):
    """Qualified identity: the same short name in another package is another contract."""
    for label, value in (('stack', stack), ('package', package), ('name', name)):
        require(type(value) is str and TOKEN.fullmatch(value), f'Contract {label} must be an identifier token')
    return {'stack': stack, 'package': package, 'name': name, 'id': digest(['seam-contract', stack, package, name])}


def parse_transform(spec):
    """Closed transform schema; an unknown option is refused, never ignored."""
    require(isinstance(spec, dict) and spec.get('kind') in TRANSFORM_KEYS, 'Transform must declare kind identity, value_map or affix')
    allowed = TRANSFORM_KEYS[spec['kind']]
    unknown = sorted(set(spec) - allowed)
    require(not unknown, 'Unknown transform option(s): ' + ', '.join(unknown))
    require(type(spec.get('version')) is int and spec['version'] == 1, 'Unknown transform version')
    transform = {'version': 1, 'kind': spec['kind']}
    if spec['kind'] == 'value_map':
        mapping = spec.get('value_map')
        require(isinstance(mapping, dict) and mapping and all(
            type(k) is str and k and type(v) is str and v for k, v in mapping.items()), 'value_map must map non-empty names to non-empty names')
        transform['value_map'] = dict(mapping)
    elif spec['kind'] == 'affix':
        options = {k: spec.get(k) for k in ('strip_prefix', 'strip_suffix', 'add_prefix', 'add_suffix') if k in spec}
        require(options and all(type(v) is str and v for v in options.values()), 'affix requires at least one non-empty affix option')
        transform.update(options)
    return transform


def apply_transform(transform, value):
    if transform['kind'] == 'identity':
        return value
    if transform['kind'] == 'value_map':
        return transform['value_map'].get(value, value)
    result = value
    if 'strip_prefix' in transform and result.startswith(transform['strip_prefix']):
        result = result[len(transform['strip_prefix']):]
    if 'strip_suffix' in transform and result.endswith(transform['strip_suffix']):
        result = result[:len(result) - len(transform['strip_suffix'])]
    return transform.get('add_prefix', '') + result + transform.get('add_suffix', '')


def effective_transform(transform, values):
    """The mapping over the whole input set, passthrough included, with every collision named."""
    transform = parse_transform(transform)
    require(isinstance(values, list) and all(type(v) is str and v for v in values), 'Transform inputs must be names')
    mapping = {value: apply_transform(transform, value) for value in dict.fromkeys(values)}
    targets = {}
    for source, target in mapping.items():
        targets.setdefault(target, []).append(source)
    collisions = {target: sources for target, sources in targets.items() if len(sources) > 1}
    effective = 'identity' if all(k == v for k, v in mapping.items()) else 'mapping'
    return {'declared': transform['kind'], 'effective': effective,
            'declared_effective_mismatch': transform['kind'] != 'identity' and effective == 'identity',
            'mapping': mapping, 'collisions': collisions, 'empty_targets': sorted(t for t in targets if not t)}


def parse_observation(document):
    """A typed extraction result. Fidelity is a claim about the extractor, denominators say what it saw."""
    require(isinstance(document, dict) and set(document) >= {'identity', 'kind', 'members', 'fidelity', 'denominator', 'source'},
            'Seam observation requires identity, kind, members, fidelity, denominator, source')
    covered = document.get('covered_scopes', [])
    require(isinstance(covered, list) and all(s in CHECK_SCOPES for s in covered) and len(set(covered)) == len(covered),
            'covered_scopes must list distinct check scopes')
    identity = document['identity']
    require(isinstance(identity, dict) and contract_identity(identity.get('stack'), identity.get('package'),
                                                             identity.get('name'))['id'] == identity.get('id'),
            'Seam identity does not match its parts')
    require(document['kind'] in KINDS, 'Unknown seam kind')
    require(document['fidelity'] in FIDELITY, 'Unknown seam fidelity')
    members = document['members']
    require(isinstance(members, list), 'Seam members must be a list')
    names = []
    for member in members:
        require(isinstance(member, dict) and type(member.get('name')) is str and member['name'], 'Seam member requires a name')
        require(set(member) <= {'name', 'type', 'tag', 'span'}, 'Unknown seam member fields')
        names.append(member['name'])
    require(len(set(names)) == len(names), 'Duplicate seam member names')
    denominator = document['denominator']
    require(isinstance(denominator, dict) and all(type(denominator.get(k)) is int and denominator[k] >= 0
            for k in ('symbols_found', 'unresolved')), 'Seam denominator requires symbols_found and unresolved counts')
    require(document['fidelity'] != 'HIGH' or denominator['unresolved'] == 0,
            'HIGH fidelity cannot coexist with unresolved members')
    source = document['source']
    require(isinstance(source, dict) and set(source) >= {'path', 'blob_sha', 'revision', 'parser'}
            and type(source['blob_sha']) is str and source['blob_sha'].startswith('sha256:'), 'Seam source identity incomplete')
    return document


def parse_policy(policy):
    require(isinstance(policy, dict) and {'version', 'direction', 'require_fidelity', 'compare'} <= set(policy)
            <= {'version', 'direction', 'require_fidelity', 'compare', 'required_scopes'},
            'Comparison policy requires version, direction, require_fidelity, compare (and optional required_scopes)')
    required_scopes = policy.get('required_scopes', ['member_names'])
    require(isinstance(required_scopes, list) and required_scopes and all(s in CHECK_SCOPES for s in required_scopes)
            and len(set(required_scopes)) == len(required_scopes), 'required_scopes must list distinct check scopes')
    require(policy['version'] == POLICY_VERSION and type(policy['version']) is int, 'Unknown comparison policy version')
    require(policy['direction'] in DIRECTIONS, 'Unknown comparison direction')
    require(policy['require_fidelity'] == 'HIGH', 'Only HIGH fidelity may be compared; lower fidelity is BLOCKED')
    require(isinstance(policy['compare'], list) and 'name' in policy['compare']
            and set(policy['compare']) <= {'name', 'type', 'tag'}, 'compare keys must include name and only name/type/tag')
    return {**policy, 'required_scopes': sorted(required_scopes), 'policy_hash': digest(policy)}


def covered_scopes_of(observation):
    """Declared coverage, or what the members themselves carry when the extractor did not declare it."""
    declared = observation.get('covered_scopes')
    if declared:
        return list(declared)
    members = observation.get('members') or []
    if not members:
        return []
    scopes = ['member_names']
    if all('type' in m for m in members):
        scopes.append('member_types')
    if all('tag' in m for m in members):
        scopes.append('member_tags')
    return scopes


def scope_coverage(producer, consumer, policy):
    """Which required scopes this comparison really checked: both sides must have covered them and
    the policy must compare them; everything else is unverified, never OK."""
    compared = {COMPARE_SCOPES[key] for key in policy['compare']}
    both = set(covered_scopes_of(producer)) & set(covered_scopes_of(consumer))
    checked = sorted(scope for scope in policy['required_scopes'] if scope in both and scope in compared)
    unverified = sorted(scope for scope in policy['required_scopes'] if scope not in checked)
    return {'required': list(policy['required_scopes']), 'checked': checked, 'unverified': unverified,
            'complete': not unverified,
            'note': 'OK speaks only for checked scopes; an unverified scope is not agreement'}


def copy_identity(producer, consumer):
    """A byte-identical copy and equality on the checked scopes are different facts."""
    same_blob = producer['source']['blob_sha'] == consumer['source']['blob_sha']
    return {'same_blob': same_blob, 'producer_blob': producer['source']['blob_sha'], 'consumer_blob': consumer['source']['blob_sha'],
            'note': 'same_blob is file byte identity; verdict OK is equality on the checked scopes only'}


def compare(producer, consumer, transform, policy):
    """Directional, advisory comparison of two observations under one effective transform."""
    producer, consumer, policy = parse_observation(producer), parse_observation(consumer), parse_policy(policy)
    base = {'policy_version': policy['version'], 'policy_hash': policy['policy_hash'], 'direction': policy['direction'],
            'compared_keys': list(policy['compare']), 'producer': producer['identity']['id'], 'consumer': consumer['identity']['id'],
            'authority': 'advisory', 'blocking_eligible': False,
            'scope_coverage': scope_coverage(producer, consumer, policy), 'copy': copy_identity(producer, consumer)}
    for side, observation in (('producer', producer), ('consumer', consumer)):
        if observation['fidelity'] != policy['require_fidelity']:
            return {**base, 'verdict': 'BLOCKED', 'reason': f'{side} fidelity is {observation["fidelity"]}, policy requires HIGH',
                    'denominators': {'producer': producer['denominator'], 'consumer': consumer['denominator']}}
    effective = effective_transform(transform, [m['name'] for m in producer['members']])
    if effective['collisions'] or effective['empty_targets']:
        return {**base, 'verdict': 'NEEDS_TRANSFORM', 'transform': effective,
                'reason': 'transform maps distinct producer values onto one target' if effective['collisions']
                else 'transform produces an empty target'}
    keys = [k for k in policy['compare'] if k != 'name']
    mapped = {effective['mapping'][m['name']]: m for m in producer['members']}
    consumers = {m['name']: m for m in consumer['members']}
    producer_only = sorted(set(mapped) - set(consumers))
    consumer_only = sorted(set(consumers) - set(mapped))
    changed = sorted(name for name in set(mapped) & set(consumers)
                     if any(mapped[name].get(k) != consumers[name].get(k) for k in keys))
    if policy['direction'] == 'producer_to_consumer':
        drift = bool(producer_only or changed)
    elif policy['direction'] == 'consumer_to_producer':
        drift = bool(consumer_only or changed)
    else:
        drift = bool(producer_only or consumer_only or changed)
    return {**base, 'verdict': 'DRIFT' if drift else 'OK', 'transform': effective, 'producer_only': producer_only,
            'consumer_only': consumer_only, 'changed': changed,
            'equivalent_on_checked_scopes': not drift and not producer_only and not consumer_only and not changed,
            'denominators': {'producer': producer['denominator'], 'consumer': consumer['denominator']},
            'note': 'name/type/tag agreement is textual; it is not compiler, serialization or product compatibility'}


def audit_records(records):
    """Fold imported ledger records: prior valid records are retained, corruption is reported, never repaired."""
    valid = [r for r in records if r.get('state') == 'valid']
    corrupt = [r for r in records if r.get('state') == 'corrupt']
    counts = {verdict: sum(r['record'].get('verdict') == verdict for r in valid) for verdict in VERDICTS}
    return {'valid': len(valid), 'corrupt': len(corrupt), 'status': 'complete' if not corrupt else 'partial',
            'verdicts': counts, 'corrupt_lines': [r['line'] for r in corrupt],
            'note': 'a partial audit proves nothing about the records it could not read'}


def unknown_observation(identity, kind, source, state, reason):
    """What an extractor returns when it could not extract: never HIGH, never empty-and-OK."""
    require(state in {'read_error', 'decoding_error', 'unsupported_syntax', 'unsupported_stack', 'truncated', 'missing_source'},
            'Unknown observation state')
    return {'identity': identity, 'kind': kind, 'members': [], 'fidelity': 'UNKNOWN', 'state': state, 'reason': reason,
            'denominator': {'symbols_found': 0, 'unresolved': 0}, 'source': source, 'covered_scopes': []}


class SeamError(ContractError):
    pass
