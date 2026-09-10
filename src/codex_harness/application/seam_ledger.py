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
            row = {'id': key, 'observation': observation, 'binding': binding, 'recorded_at': utcnow()}
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

    def view(self, policy):
        """Project the recorded rows into one deterministic view; the row is derived and regenerable."""
        with self.store.transaction() as tx:
            observations = [row['observation'] for row in tx.scan(OBSERVATIONS)]
            comparisons = [{'id': row['id'], 'result': row['result']} for row in tx.scan(COMPARISONS)]
        view = build_view(observations, comparisons, policy)
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
