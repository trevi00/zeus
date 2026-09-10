"""Append-only experience claims; a separate bucket that recurrence counting never reads."""
from codex_harness.domain.model import require, utcnow

BUCKET = 'experience_claims'
RECORD_ONLY = ('body_ref', 'recorded_at', 'sequence', 'acquisitions')
ACQUISITION_KEYS = ('kind', 'revision')


def content_identity(claim):
    """The immutable content claim: everything except where/when the same bytes were acquired."""
    return {**claim, 'source': {k: v for k, v in claim['source'].items() if k not in ACQUISITION_KEYS}}


class ExperienceClaims:
    def __init__(self, store):
        self.store = store

    def record(self, claim, body_ref):
        require(isinstance(body_ref, str) and body_ref.startswith('sha256:'), 'Lesson bytes must be archived first')
        acquisition = {k: claim['source'][k] for k in ACQUISITION_KEYS}
        with self.store.transaction() as tx:
            existing = tx.get(BUCKET, claim['id'])
            if existing is not None:
                # INV-EXPERIENCE-001: the ID binds source, path, bytes and rule version, so a
                # different body under the same ID is corruption, not an update. The acquisition
                # basis (observed bytes, pinned commit A, pinned commit B) is separate evidence of
                # where the same bytes were seen; it accumulates and never counts as a new occurrence
                # (review counterexample, PR #36).
                require(content_identity({k: v for k, v in existing.items() if k not in RECORD_ONLY})
                        == content_identity(claim), 'Experience claim ID reused with different content')
                acquisitions = existing.get('acquisitions', [{k: existing['source'][k] for k in ACQUISITION_KEYS}])
                added = acquisition not in acquisitions
                if added:
                    tx.put(BUCKET, claim['id'], {**existing, 'acquisitions': acquisitions + [acquisition]})
                return {'id': claim['id'], 'changed': False, 'acquisition_added': added,
                        'body_ref': existing['body_ref']}
            # Import order is the only version order; timestamps can tie within one second.
            sequence = 1 + sum(row['source']['name'] == claim['source']['name']
                               and row['source']['path'] == claim['source']['path'] for row in tx.scan(BUCKET))
            tx.put(BUCKET, claim['id'], {**claim, 'body_ref': body_ref, 'recorded_at': utcnow(),
                                         'sequence': sequence, 'acquisitions': [acquisition]})
        return {'id': claim['id'], 'changed': True, 'acquisition_added': True, 'body_ref': body_ref}

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
