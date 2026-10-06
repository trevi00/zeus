"""Native decision dependencies that must remain current across recovery."""
from codex_harness.application.audit_gate import binding
from codex_harness.domain.model import digest, require
from codex_harness.domain.research import require_dispatch


def release_review_policy(candidate):
    checks = ['tests', 'cli_start', 'cli_file_task']
    if candidate.get('hook_id'):
        checks += ['hook_reproduction', 'hook_normal_case']
    return {'checks': checks, 'revision': candidate['base']}


def context(tx, row, org, artifacts):
    phase, data, actor = row['phase'], row['input'], row['actor']
    org.actor(actor)
    if phase in {'research_lead', 'proposal'}:
        # INV-RESEARCH-004: recovery cannot unlock the intentionally deferred legacy route.
        require_dispatch({'proposal': data})
    if phase == 'diagnose':
        evidence = artifacts.document(data['evidence_ref'])
        source = tx.get('tasks', data['source_task_id'])
        require(source is not None and evidence['task_id'] == source['id'] == data['source_task_id']
                and evidence['agent'] == data['source_actor'] == source['agent']
                and org.actor(source['agent']).parent == actor, 'Diagnosis source identity changed')
        require(type(evidence['attempt']) is int and evidence['attempt'] > 0
                and row['id'] == data['occurrence_id'] == digest({'task': source['id'], 'attempt': evidence['attempt']})
                and evidence['error'] == data['error'], 'Diagnosis occurrence binding changed')
        require(tx.get('incidents', data['occurrence_id']) is None, 'Diagnosis occurrence already recorded')
        # A later source retry or cancellation must not invalidate this historical failure.
        return {'kind': phase, 'source': {k: source[k] for k in ('id', 'agent', 'input_hash')},
                'evidence': evidence, 'evidence_ref': data['evidence_ref']}
    if phase == 'audit_review':
        bound = binding(tx, data['audit_id'], data['proposal'])
        require(bound == data['binding'] and row['id'] == digest({'binding': bound, 'actor': actor}),
                'Audit recovery binding changed')
        require(actor in {'lead:research', 'conductor'} and actor != data['proposal']['author'],
                'Invalid audit recovery reviewer')
        reviews = sorted((r for r in tx.scan('research_reviews') if r['review']['binding'] == bound), key=digest)
        require(not any(r['review']['actor'] == actor for r in reviews)
                and tx.get('research_approvals', bound) is None, 'Audit review already recorded')
        if actor == 'conductor':
            require(any(r['review']['actor'] == 'lead:research' and r['review']['accepted'] for r in reviews),
                    'Research lead approval required')
        return {'kind': phase, 'binding': bound, 'reviews': reviews}
    require(phase in {'review_lead', 'review_conductor'}, 'No recovery coupling handler for this decision phase')
    message = row['message']
    inbox = tx.get('workflow_inbox', row['id'])
    require(message['message_id'] == row['id'] and inbox is not None and inbox['hash'] == digest(message),
            'Originating decision report changed')
    details = message['what']['details']
    source_bucket = 'decisions_pending' if 'decision_id' in details else 'tasks'
    source_id = details.get('decision_id', details.get('task_id'))
    source = tx.get(source_bucket, source_id)
    require(source is not None and source['id'] == source_id and source['status'] == 'succeeded'
            and source['result'] == details['result'] == data
            and source.get('actor', source.get('agent')) == message['who']['sender'], 'Unproven originating result')
    candidate = data['candidate']
    author = org.actor(candidate['author'], 'worker')
    require(actor == (author.parent if phase == 'review_lead' else 'conductor'), 'Invalid candidate reviewer')
    if phase == 'review_conductor':
        release_id = data['release_id']
        release = tx.get('releases', release_id)
        require(release is not None, 'Candidate release missing')
        policy = release['policy']
    else:
        policy = release_review_policy(candidate)
        release_id = digest({'candidate': candidate, 'policy': policy})
        release = tx.get('releases', release_id)
    if release is not None:
        require(release['id'] == release_id and release['candidate'] == candidate and release['policy'] == policy
                and release_id == digest({'candidate': candidate, 'policy': policy})
                and release['policy_hash'] == digest(policy) and release['status'] in {'candidate', 'reviewed'}
                and not any(r['actor'] == actor for r in release['reviews']), 'Release no longer reviewable')
    if phase == 'review_conductor':
        require(release is not None and any(r['actor'] == author.parent and r['accepted']
                for r in release['reviews']), 'Lead release approval required')
    require(tx.get('release_queue', release_id) is None, 'Release already queued')
    hook = tx.get('hooks', candidate['hook_id']) if candidate.get('hook_id') else None
    if candidate.get('hook_id'):
        require(hook is not None and hook['id'] == candidate['hook_id'] and hook['status'] in {'candidate', 'reviewed'}
                and hook['revision'] == candidate['revision'] and hook['author'] == candidate['author']
                and not any(r['actor'] == actor for r in hook['reviews']), 'Hook no longer reviewable')
        if phase == 'review_conductor':
            require(any(r['role'] == 'lead' and r['passed'] for r in hook['reviews']), 'Lead hook review required')
    loop = tx.get('improvement_loops', message['correlation_id'])
    require(loop is None or loop.get('status') not in {'stagnated', 'budget_exhausted'}, 'Improvement loop terminal')
    return {'kind': phase, 'source': {'id': source_id, 'status': source['status'], 'result': source['result'],
                'actor': source.get('actor', source.get('agent'))}, 'inbox_hash': inbox['hash'],
            'release': ({k: release[k] for k in ('id', 'candidate', 'policy_hash', 'status', 'reviews')}
                        if release is not None else None),
            'hook': ({'id': hook['id'], 'status': hook['status'], 'revision': hook['revision'],
                      'author': hook['author'], 'spec_hash': digest(hook['spec']), 'reviews': hook['reviews']}
                     if hook is not None else None),
            # Rework counts and rejected trees control native branching; annotations do not.
            'loop': ({k: loop.get(k) for k in ('status', 'reworks', 'rejected_trees')} if loop else None)}
