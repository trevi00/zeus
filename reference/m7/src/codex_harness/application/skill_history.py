"""Bounded hot history, permanent small deduplication ledger, transactional writes."""
from codex_harness.domain.model import digest, require, utcnow
from codex_harness.domain.skill_audit import DELIVERY_TIERS, audit_history
from codex_harness.domain.skill_history import MAX_EVENTS, TOP_MATCHES, assess_history


class SkillHistory:
    def __init__(self, store):
        self.store = store

    def snapshot(self, project, current, exclude):
        with self.store.transaction() as tx:
            state = tx.get('skill_history', project) or {'events': []}
        return assess_history(state['events'], current, exclude)

    def audit(self, project, **options):
        with self.store.transaction() as tx:
            state = tx.get('skill_history', project) or {'events': []}
        return {'project_key': project, **audit_history(state['events'], **options)}

    def record(self, project, event, guard=None):
        require(all(isinstance(event.get(key), str) and event[key]
                    for key in ('manifest_ref', 'context_ref')), 'Missing skill evidence reference')
        require(isinstance(event.get('id'), str) and bool(event['id']), 'Missing skill observation id')
        require(isinstance(event.get('top'), list) and len(event['top']) <= TOP_MATCHES,
                'Invalid skill observation size')
        for item in event['top']:
            require(isinstance(item, dict), 'Invalid skill observation item')
            require(isinstance(item.get('score'), int) and not isinstance(item['score'], bool)
                    and item['score'] >= 0, 'Invalid skill score')
            require(all(isinstance(item.get(key), str) and item[key]
                        for key in ('path', 'content_ref')), 'Invalid skill identity')
            if 'base_score' in item:
                require(isinstance(item['base_score'], int) and not isinstance(item['base_score'], bool)
                        and 0 <= item['base_score'] <= item['score'], 'Invalid base score')
            if 'body_chars' in item:
                require(isinstance(item['body_chars'], int) and not isinstance(item['body_chars'], bool)
                        and 0 <= item['body_chars'] <= 1024 * 1024, 'Invalid skill body size')
            require(isinstance(item.get('dimensions', []), list)
                    and all(isinstance(dim, str) for dim in item.get('dimensions', [])),
                    'Invalid skill dimensions')
            if 'tier' in item:
                require(item['tier'] in DELIVERY_TIERS, 'Invalid skill delivery tier')
            if 'rendered_hash' in item:
                require(isinstance(item['rendered_hash'], str) and bool(item['rendered_hash']),
                        'Invalid rendered body hash')
        require(len({(r['path'], r['content_ref']) for r in event['top']}) == len(event['top']),
                'Duplicate skill identity in observation')
        if 'delivery' in event:
            delivery = event['delivery']
            require(isinstance(delivery, dict) and set(delivery) == {'stage', 'admitted', 'omitted'}
                    and isinstance(delivery['stage'], str) and bool(delivery['stage'])
                    and all(isinstance(delivery[k], list) and all(isinstance(v, str) for v in delivery[k])
                            for k in ('admitted', 'omitted'))
                    and not set(delivery['admitted']) & set(delivery['omitted']),
                    'Invalid skill delivery record')
            require(all(item['path'] in delivery['admitted'] for item in event['top']
                        if item.get('tier') == 'full'), 'A full tier must be in the admitted set')
        # INV-SKILL-HISTORY-001: richer passive diagnostics do not create a new
        # observation or conflict with pre-audit retries of the same selection.
        scoring = [{key: item[key] for key in ('path', 'content_ref', 'score', 'base_score')
                    if key in item} for item in event['top']]
        fingerprint = digest({'id': event['id'], 'top': scoring, 'manifest_ref': event['manifest_ref']})
        key = digest([project, event['id']])
        with self.store.transaction() as tx:
            if guard:
                guard(tx)
            prior = tx.get('skill_observations', key)
            if prior:
                require(prior['fingerprint'] == fingerprint, 'Conflicting skill observation replay')
                return False
            state = tx.get('skill_history', project) or {'events': []}
            state['events'] = (state['events'] + [{**event, 'at': utcnow()}])[-MAX_EVENTS:]
            tx.put('skill_history', project, state)
            tx.put('skill_observations', key, {'fingerprint': fingerprint,
                   'context_ref': event['context_ref'], 'at': utcnow()})
        return True
