"""Append-only experience claims; a separate bucket that recurrence counting never reads."""
from codex_harness.domain.model import require, utcnow

BUCKET = 'experience_claims'
RECORD_ONLY = ('body_ref', 'recorded_at', 'sequence')


class ExperienceClaims:
    def __init__(self, store):
        self.store = store

    def record(self, claim, body_ref):
        require(isinstance(body_ref, str) and body_ref.startswith('sha256:'), 'Lesson bytes must be archived first')
        with self.store.transaction() as tx:
            existing = tx.get(BUCKET, claim['id'])
            if existing is not None:
                # INV-EXPERIENCE-001: the ID binds source, path, bytes and rule version, so a
                # different body under the same ID is corruption, not an update.
                require({k: v for k, v in existing.items() if k not in RECORD_ONLY} == claim,
                        'Experience claim ID reused with different content')
                return {'id': claim['id'], 'changed': False, 'body_ref': existing['body_ref']}
            # Import order is the only version order; timestamps can tie within one second.
            sequence = 1 + sum(row['source']['name'] == claim['source']['name']
                               and row['source']['path'] == claim['source']['path'] for row in tx.scan(BUCKET))
            tx.put(BUCKET, claim['id'], {**claim, 'body_ref': body_ref, 'recorded_at': utcnow(),
                                         'sequence': sequence})
        return {'id': claim['id'], 'changed': True, 'body_ref': body_ref}

    def versions(self, source, path):
        with self.store.transaction() as tx:
            rows = [row for row in tx.scan(BUCKET)
                    if row['source']['name'] == source and row['source']['path'] == path]
        return sorted(rows, key=lambda row: (row['sequence'], row['id']))

    def summary(self):
        with self.store.transaction() as tx:
            rows = tx.scan(BUCKET)
        return {'claims': len(rows),
                'upstream_occurrences_sum': sum(row['upstream_occurrences'] or 0 for row in rows),
                'independent_occurrences_sum': sum(row['independent_occurrences']['count'] for row in rows),
                'unverified': sum(row['status'] == 'upstream_occurrences_unverified' for row in rows),
                'recomputed': sum(row['status'] == 'independently_recomputed' for row in rows)}
