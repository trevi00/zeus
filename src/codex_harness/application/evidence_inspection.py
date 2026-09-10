"""Evidence inspections as ledger rows bound to the execution that produced the claims.

Each row names the task, generation, attempt and owner, the candidate source revision and
base, the workspace, the policy hash and every finding with its state, cause and raw output
references. The verdict is `all_checked` only when every claim was checked and agreed;
otherwise `incomplete`, and a failed recording is a named state, never a silent success.
Consumers that need proof call `require_all_checked`.
"""
from codex_harness.domain.evidence import denominator, verdict
from codex_harness.domain.model import ContractError, digest, require, utcnow

BUCKET = 'evidence_inspections'
NOTICES = 'evidence_inspection_notices'


class EvidenceInspections:
    def __init__(self, store, inspector):
        self.store, self.inspector = store, inspector

    @staticmethod
    def binding(task, candidate, cwd):
        require(isinstance(task, dict) and type(task.get('id')) is str and type(task.get('generation')) is int
                and type(task.get('attempt')) is int, 'Evidence inspection requires a typed execution lease')
        require(isinstance(candidate, dict) and type(candidate.get('revision')) is str and candidate['revision'],
                'Evidence inspection requires the captured candidate revision')
        return {'task_id': task['id'], 'generation': task['generation'], 'attempt': task['attempt'],
                'owner': task.get('lease_owner'), 'source_revision': candidate['revision'],
                'base': candidate.get('base'), 'tree': candidate.get('tree'), 'workspace': str(cwd)}

    def inspect(self, task, candidate, claims, cwd):
        """Run the inspection and commit it; one row per (execution, revision, claims)."""
        bound = self.binding(task, candidate, cwd)
        key = digest(['evidence-inspection-v1', bound, list(claims)])
        with self.store.transaction() as tx:
            existing = tx.get(BUCKET, key)
        if existing is not None:
            return existing
        report = self.inspector.inspect(list(claims), cwd, bound)
        counts = denominator(report['findings'])
        row = {'id': key, 'binding': bound, 'policy_hash': report['policy_hash'], 'context': report['context'],
               'claims': list(claims), 'findings': report['findings'], 'denominator': counts,
               'verdict': verdict(report['findings']), 'recorded_at': utcnow(),
               'authority': 'deterministic inspection of claims; not historical truth, semantic review or human acceptance'}
        try:
            with self.store.transaction() as tx:
                previous = tx.get(BUCKET, key)
                if previous is not None:
                    return previous
                tx.put(BUCKET, key, row)
        except Exception as exc:
            # The inspection happened; the ledger did not take it. Say so, loudly and durably if possible.
            notice = {'id': digest([key, 'recording_failed']), 'inspection_id': key, 'reason': type(exc).__name__ + ': ' + str(exc)[:300],
                      'verdict': row['verdict'], 'denominator': counts, 'at': utcnow()}
            try:
                with self.store.transaction() as tx:
                    tx.put(NOTICES, notice['id'], notice)
            finally:
                raise ContractError('Evidence inspection could not be recorded: ' + notice['reason']) from exc
        return row

    def require_all_checked(self, tx, inspection_id):
        row = tx.get(BUCKET, inspection_id)
        require(row is not None, 'Evidence inspection missing')
        require(row['verdict'] == 'all_checked', 'Evidence inspection is ' + row['verdict'] + ': '
                + ', '.join(f"{state}={count}" for state, count in row['denominator'].items() if count and state != 'claims'))
        return row
