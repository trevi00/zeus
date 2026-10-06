"""Seam observations, comparisons and imported ledgers as runtime records; blocking is an approval.

PostgreSQL owns what was observed, compared, approved and what could not be read. A comparison
is advisory; `blocking_eligible` is set only by a named reviewer under a policy revision, for a
DRIFT that still binds the same observations. An imported JSONL ledger keeps every prior valid
record and reports each corrupt line; a partial audit never presents itself as complete.
"""
import json

from codex_harness.domain.model import digest, require, utcnow
from codex_harness.domain.seam_view import build_view
from codex_harness.domain.seams import VERDICTS, audit_records, compare, parse_observation

OBSERVATIONS = 'seam_observations'
COMPARISONS = 'seam_comparisons'
IMPORTS = 'seam_ledger_imports'
VIEWS = 'seam_views'
REVIEWERS = ('lead:improvement', 'conductor')
RECORD_KEYS = {'seam_id', 'verdict', 'producer', 'consumer', 'at'}


class SeamLedger:
    def __init__(self, store):
        self.store = store

    def record_observation(self, observation, *, binding):
        observation = parse_observation(observation)
        require(isinstance(binding, dict) and type(binding.get('revision')) is str and binding['revision']
                and binding['revision'] == observation['source']['revision'], 'Observation binding must name the source revision it was read at')
        key = digest(['seam-observation', observation['identity']['id'], observation['source']['blob_sha'],
                      observation['source']['parser'], observation['source']['revision']])
        with self.store.transaction() as tx:
            existing = tx.get(OBSERVATIONS, key)
            if existing is not None:
                return existing
            # Recording order is assigned in the transaction, so "newest revision" never depends on a
            # clock tie or on set iteration order (review, PR #59).
            sequence = 1 + max((row.get('sequence', 0) for row in tx.scan(OBSERVATIONS)), default=0)
            row = {'id': key, 'observation': observation, 'binding': binding, 'recorded_at': utcnow(), 'sequence': sequence}
            tx.put(OBSERVATIONS, key, row)
            return row

    def compare(self, producer_id, consumer_id, transform, policy):
        with self.store.transaction() as tx:
            producer, consumer = tx.get(OBSERVATIONS, producer_id), tx.get(OBSERVATIONS, consumer_id)
            require(producer is not None and consumer is not None, 'Both observations must be recorded before comparison')
            result = compare(producer['observation'], consumer['observation'], transform, policy)
            key = digest(['seam-comparison', producer_id, consumer_id, transform, result['policy_hash']])
            existing = tx.get(COMPARISONS, key)
            if existing is not None:
                return existing
            row = {'id': key, 'producer_row': producer_id, 'consumer_row': consumer_id, 'transform': transform,
                   'result': result, 'approval': None, 'recorded_at': utcnow()}
            tx.put(COMPARISONS, key, row)
            return row

    def approve_blocking(self, comparison_id, *, actor, policy_revision, reason):
        """Only a reviewer turns an advisory DRIFT into a blocking-eligible finding, under a policy revision."""
        require(actor in REVIEWERS, 'Only a reviewer approves blocking use of a seam comparison')
        require(type(policy_revision) is str and len(policy_revision) == 40 and all(c in '0123456789abcdef' for c in policy_revision),
                'Blocking approval requires the Git revision of the deployment policy')
        require(type(reason) is str and bool(reason.strip()), 'Blocking approval requires a reason')
        with self.store.transaction() as tx:
            row = tx.get(COMPARISONS, comparison_id)
            require(row is not None, 'Unknown seam comparison')
            require(row['result']['verdict'] == 'DRIFT', 'Only a DRIFT comparison can be approved for blocking; '
                    + row['result']['verdict'] + ' is not a finding')
            if row['approval'] is not None:
                return row
            row['approval'] = {'actor': actor, 'policy_revision': policy_revision, 'reason': reason, 'at': utcnow()}
            row['result'] = {**row['result'], 'blocking_eligible': True, 'authority': 'reviewer-approved under policy ' + policy_revision}
            tx.put(COMPARISONS, comparison_id, row)
            return row

    def import_jsonl(self, text, *, source_label):
        """Import an upstream-style events ledger line by line; corrupt lines are kept as corrupt records."""
        require(type(text) is str and type(source_label) is str and source_label, 'Import requires text and a source label')
        records = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                require(isinstance(record, dict) and RECORD_KEYS <= set(record) and record['verdict'] in VERDICTS, 'record shape')
                records.append({'line': number, 'state': 'valid', 'record': record})
            except Exception as exc:  # malformed JSON, wrong shape: the line is evidence of corruption, not skipped
                records.append({'line': number, 'state': 'corrupt', 'reason': type(exc).__name__ + ': ' + str(exc)[:120],
                                'excerpt': line[:200]})
        audit = audit_records(records)
        key = digest(['seam-import', source_label, text])
        with self.store.transaction() as tx:
            existing = tx.get(IMPORTS, key)
            if existing is not None:
                return existing
            row = {'id': key, 'source_label': source_label, 'records': records, 'audit': audit, 'imported_at': utcnow(),
                   'authority': 'imported claims; not runtime observations, not acceptance'}
            tx.put(IMPORTS, key, row)
            return row

    def view(self, policy, *, revision=None, comparison_ids=None):
        """Project one revision's rows into a deterministic view; the row is derived and regenerable.

        The ledger is append-only, so it holds every revision ever observed. A view is about one
        source revision (review, PR #59): its observations are the rows recorded at that revision, and
        its comparisons are exactly those whose producer and consumer rows belong to it (or the
        explicit `comparison_ids`). With no revision named, the newest recorded revision is used and
        the receipt says which.
        """
        require(revision is None or (type(revision) is str and revision), 'View revision must be text')
        require(comparison_ids is None or (isinstance(comparison_ids, list) and all(type(c) is str for c in comparison_ids)),
                'comparison_ids must be a list of comparison ids')
        with self.store.transaction() as tx:
            observation_rows = tx.scan(OBSERVATIONS)
            comparison_rows = tx.scan(COMPARISONS)
        def recorded(row):
            return (row.get('sequence', 0), row['recorded_at'], row['id'])
        revisions = sorted({row['binding']['revision'] for row in observation_rows}, key=lambda r: max(
            recorded(row) for row in observation_rows if row['binding']['revision'] == r))
        if revision is None:
            require(revisions, 'No observations recorded; nothing to view')
            revision = revisions[-1]
        by_id = {row['id']: row for row in observation_rows if row['binding']['revision'] == revision}
        if comparison_ids is None:
            selected = [row for row in comparison_rows if row['producer_row'] in by_id and row['consumer_row'] in by_id]
        else:
            selected = [row for row in comparison_rows if row['id'] in comparison_ids]
            missing = sorted(set(comparison_ids) - {row['id'] for row in selected})
            require(not missing, 'Unknown seam comparison ids: ' + ', '.join(missing))
            outside = [row['id'] for row in selected if row['producer_row'] not in by_id or row['consumer_row'] not in by_id]
            require(not outside, 'Comparisons outside revision ' + revision + ': ' + ', '.join(outside))
        observations = [row['observation'] for row in by_id.values()]
        comparisons = [{'id': row['id'], 'result': row['result']} for row in selected]
        view = build_view(observations, comparisons, policy)
        view['receipt'] = {**view['receipt'], 'revision': revision, 'revisions_recorded': revisions,
                           'observation_rows': sorted(by_id), 'comparison_rows': sorted(row['id'] for row in selected)}
        key = view['receipt']['inputs_hash']
        with self.store.transaction() as tx:
            existing = tx.get(VIEWS, key)
            if existing is not None:
                require(existing['view']['receipt']['view_hash'] == view['receipt']['view_hash'],
                        'A regenerated view differs from the stored one for identical inputs')
                return existing
            row = {'id': key, 'view': view, 'generated_at': utcnow(), 'derived': True}
            tx.put(VIEWS, key, row)
            return row
