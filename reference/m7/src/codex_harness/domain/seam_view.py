"""Derived seam view and gate: provenance per node, roles per edge, a closed policy vocabulary, and
nonzero obligations (INV-SEAM-VIEW-001).

The upstream graph flattened declared, extracted and observed facts into one LIVE label that meant
"matched, not BLOCKED" — never traffic — dropped producer/consumer roles, drift direction and
BLOCKED status, accepted `--fail-on TYPO` and an empty seam list as a 0/0 success. Here a node
carries its provenance, an edge keeps roles, direction, verdict and fidelity, `live` is reserved
for OK comparisons between two HIGH observations, the gate vocabulary is closed, and a gate can
pass only when every required seam is present and OK. The view is a deterministic projection of
its inputs with a generation receipt; it is never a ledger of its own.
"""
from codex_harness.domain.model import canonical, digest, require
from codex_harness.domain.seams import VERDICTS, covered_scopes_of

FAIL_ON_VOCABULARY = ('DRIFT', 'NEEDS_TRANSFORM', 'BLOCKED')
PROVENANCE = ('observed', 'extracted_partial', 'unavailable', 'declared_only')
VIEW_VERSION = 'zeus.seam-view.v1'


def parse_gate_policy(policy):
    """Closed policy: allowed fail-on names only, no typos, no empty obligations."""
    require(isinstance(policy, dict) and set(policy) == {'version', 'fail_on', 'required_seams'},
            'Gate policy requires version, fail_on, required_seams')
    require(type(policy['version']) is int and policy['version'] == 1, 'Unknown gate policy version')
    fail_on = policy['fail_on']
    require(isinstance(fail_on, list) and fail_on, 'fail_on must name at least one verdict')
    unknown = sorted(set(v for v in fail_on if v not in FAIL_ON_VOCABULARY))
    require(not unknown, 'fail_on names outside the vocabulary ' + str(list(FAIL_ON_VOCABULARY)) + ': ' + ', '.join(map(str, unknown)))
    require(len(set(fail_on)) == len(fail_on), 'fail_on repeats a verdict')
    seams = policy['required_seams']
    require(isinstance(seams, list) and seams and all(type(s) is str and s for s in seams), 'required_seams must name at least one seam')
    require(len(set(seams)) == len(seams), 'required_seams repeats a seam')
    return {'version': 1, 'fail_on': sorted(fail_on), 'required_seams': sorted(seams), 'policy_hash': digest(policy)}


def seam_id(producer_id, consumer_id):
    return digest(['seam', producer_id, consumer_id])


def node_provenance(observation):
    if observation is None:
        return 'declared_only'
    fidelity = observation.get('fidelity')
    if fidelity == 'HIGH':
        return 'observed'
    if fidelity == 'LOW':
        return 'extracted_partial'
    return 'unavailable'


def build_view(observations, comparisons, policy):
    """One deterministic view from the recorded facts; equal inputs give byte-equal output."""
    policy = parse_gate_policy(policy)
    require(isinstance(observations, list) and isinstance(comparisons, list), 'View inputs must be lists')
    by_contract = {}
    for observation in observations:
        identity = observation['identity']['id']
        require(identity not in by_contract or by_contract[identity]['source'] == observation['source'],
                'Two observations of one contract with different sources cannot share a view')
        by_contract[identity] = observation
    nodes, edges = {}, {}
    for identity, observation in by_contract.items():
        nodes[identity] = {'id': identity, 'provenance': node_provenance(observation), 'identity': observation['identity'],
                           'fidelity': observation['fidelity'], 'source': observation['source'],
                           'members': len(observation['members']), 'covered_scopes': covered_scopes_of(observation),
                           'undeclared': True}  # cleared below when a comparison names it
    for comparison in comparisons:
        result = comparison['result']
        producer, consumer = result['producer'], result['consumer']
        for contract in (producer, consumer):
            observation = by_contract.get(contract)
            nodes.setdefault(contract, {'id': contract, 'provenance': node_provenance(observation), 'identity': None,
                                        'fidelity': None, 'source': None, 'members': None, 'covered_scopes': [],
                                        'undeclared': False})
            nodes[contract]['undeclared'] = False
        both_high = all(nodes[c]['provenance'] == 'observed' for c in (producer, consumer))
        complete = bool((result.get('scope_coverage') or {}).get('complete', False))
        sid = seam_id(producer, consumer)
        edge = {'seam_id': sid, 'producer': producer, 'consumer': consumer, 'roles': {'producer': producer, 'consumer': consumer},
                'direction': result['direction'], 'verdict': result['verdict'],
                'live': result['verdict'] == 'OK' and both_high and complete,
                'fidelity': {'producer': nodes[producer]['fidelity'], 'consumer': nodes[consumer]['fidelity']},
                'transform': (result.get('transform') or {}).get('effective'), 'collisions': (result.get('transform') or {}).get('collisions'),
                'producer_only': result.get('producer_only'), 'consumer_only': result.get('consumer_only'), 'changed': result.get('changed'),
                'reason': result.get('reason'), 'authority': result.get('authority'), 'blocking_eligible': result.get('blocking_eligible'),
                'comparison': comparison['id'], 'policy_hash': result.get('policy_hash'),
                'scope_coverage': result.get('scope_coverage'), 'copy': result.get('copy')}
        require(sid not in edges or edges[sid] == edge, 'Two different comparisons for one seam cannot share a view')
        edges[sid] = edge
    for required in policy['required_seams']:
        if required not in edges:
            edges[required] = {'seam_id': required, 'verdict': None, 'live': False, 'provenance': 'declared_only',
                               'reason': 'required by policy but no comparison is recorded'}
    shared = {}
    for identity, observation in by_contract.items():
        for member in observation['members']:
            key = f"{member.get('type')}:{member.get('tag')}"
            shared.setdefault(key, []).append(identity)
    shared_values = [{'value': key, 'contracts': sorted(ids), 'identity': 'type+tag',
                      'note': 'a shared literal value is a coincidence of declarations, never causal message delivery'}
                     for key, ids in sorted(shared.items()) if len(set(ids)) > 1]
    view = {'version': VIEW_VERSION, 'policy': policy,
            'nodes': [nodes[k] for k in sorted(nodes)], 'edges': [edges[k] for k in sorted(edges)],
            'shared_values': shared_values,
            'legend': {'live': 'an OK comparison between two HIGH observations on every required scope; never observed traffic or acceptance',
                       'provenance': list(PROVENANCE), 'undeclared': 'observed contract that no recorded comparison names'}}
    view['gate'] = gate(view)
    inputs_hash = digest({'observations': sorted(canonical(o) for o in observations),
                          'comparisons': sorted(canonical(c) for c in comparisons), 'policy': policy['policy_hash']})
    view['receipt'] = {'generator': VIEW_VERSION, 'inputs_hash': inputs_hash, 'view_hash': digest({k: v for k, v in view.items()}),
                       'derived': True, 'authority': 'derived view of recorded rows; not a ledger, not acceptance'}
    return view


def gate(view):
    """Pass only when every required seam is present and OK; fail on a listed verdict; otherwise undecided."""
    policy = view['policy']
    edges = {edge['seam_id']: edge for edge in view['edges']}
    required = policy['required_seams']
    statuses = {}
    for sid in required:
        edge = edges.get(sid)
        if edge is None or edge.get('verdict') is None:
            statuses[sid] = 'missing'
        elif edge['verdict'] == 'OK' and not (edge.get('scope_coverage') or {}).get('complete', False):
            statuses[sid] = 'OK_unverified_scopes'  # agreement on a subset of what the spec requires is not OK
        else:
            statuses[sid] = edge['verdict']
    failing = sorted(sid for sid, status in statuses.items() if status in policy['fail_on'])
    missing = sorted(sid for sid, status in statuses.items() if status == 'missing')
    not_ok = sorted(sid for sid, status in statuses.items() if status not in {'OK', 'missing'} and status not in policy['fail_on'])
    if failing:
        decision = 'fail'
    elif missing or not_ok:
        decision = 'undecided'
    else:
        decision = 'pass'
    return {'decision': decision, 'required': len(required), 'checked': sum(s != 'missing' for s in statuses.values()),
            'ok': sum(s == 'OK' for s in statuses.values()), 'failing': failing, 'missing': missing,
            'undecided': not_ok, 'statuses': statuses,
            'note': 'pass requires every required seam present and OK on every required scope; BLOCKED, NEEDS_TRANSFORM, '
                    'missing or scope-incomplete seams never pass',
            'authority': 'advisory; blocking use requires a reviewer approval on the comparison row'}


def verdict_vocabulary():
    return list(VERDICTS)
