"""Evidence inspections as ledger rows bound to the execution that produced the claims.

Each row names the task, generation, attempt and owner, the candidate source revision and
base, the workspace, the policy hash and every finding with its state, cause and raw output
references. The verdict is `all_checked` only when every claim was checked and agreed;
otherwise `incomplete`, and a failed recording is a named state, never a silent success.
Consumers that need proof call `require_all_checked`.
"""
from inspect import Parameter, signature

from codex_harness.domain.evidence import denominator, verdict
from codex_harness.domain.model import ContractError, digest, require, utcnow

BUCKET = 'evidence_inspections'
NOTICES = 'evidence_inspection_notices'


def forwards_progress(call) -> bool:
    """Whether this inspector takes the caller's per-call progress check.

    The check is a capability of the adapter, not a global: an adapter that does not declare
    `progress` keeps its exact previous signature and call, and the caller's boundary checks around
    the inspection still apply - it simply cannot be stopped between its own replays.
    """
    try:
        parameters = signature(call).parameters
    except (TypeError, ValueError):  # a callable that cannot be described is treated as legacy
        return False
    return 'progress' in parameters or any(p.kind is Parameter.VAR_KEYWORD for p in parameters.values())


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

    def inspect(self, task, candidate, claims, cwd, progress=None, guard=None):
        """Run the inspection and commit it; one row per (execution, revision, claims, policy, host).

        `progress` is the caller's own per-call ownership and cancellation check (research-dispatch-001).
        It is called before anything is read or replayed and again before the row is written, and it
        is handed to an inspector that declares it so the replays themselves stay inside the caller's
        lease. Whatever it raises ends this inspection: a caller that no longer owns its execution
        neither starts new commands nor records a result. `progress=None` is the previous behaviour.

        `guard` is that same caller's ownership check taken INSIDE this ledger's own transactions: it
        receives the open transaction (never opening one of its own) and runs before a cached row is
        returned and before the final row is looked up and written, so neither a cache hit nor a
        publication escapes the fence. Its refusal is the CALLER's failure and is raised unchanged -
        no row, and no inspection-recording-failure notice, because the ledger did not fail. A caller
        that supplies no guard keeps its previous contract, including its transaction count.
        """
        # Bound to this call like `progress`: nothing about the guard is stored on the ledger.
        refusals = []

        def fence(tx):
            if guard is None:
                return
            try:
                guard(tx)
            except BaseException as exc:
                refusals.append(exc)
                raise

        if progress is not None:
            progress('inspection_start')
        bound = self.binding(task, candidate, cwd)
        # The policy and the host that decide the result are part of the identity: a stricter policy or
        # another environment never reads back an older all_checked (review, PR #54). The snapshot is
        # taken for this workspace, so the trusted interpreter, the normalized cwd and the candidate-bound
        # PYTHONPATH are in the key too, and a changed one is a new inspection (review-contract-001).
        snapshot = self.inspector.snapshot(cwd)
        identity = snapshot['identity'] if isinstance(snapshot, dict) else None
        require(isinstance(identity, dict) and type(identity.get('policy_hash')) is str and identity['policy_hash']
                and type(identity.get('environment_digest')) is str and type(identity.get('interpreter')) is str
                and identity['interpreter'] and isinstance(snapshot.get('environment'), dict),
                'Inspector snapshot requires an identity with policy_hash, environment_digest and interpreter, '
                'and the environment values')
        # v4: the identity gained interpreter and cwd; rows keyed under v3 stay untouched and unread.
        key = digest(['evidence-inspection-v4', bound, identity, list(claims)])
        with self.store.transaction() as tx:
            # A cache hit is still a publication to this caller: it is read under the same fence.
            fence(tx)
            existing = tx.get(BUCKET, key)
        if existing is not None:
            return existing
        # The replays run under the very environment and interpreter the identity was taken from.
        # INV-PROJECT-EVIDENCE-001: a profile-aware snapshot carries its resolved project contexts; they
        # reach the adapter exactly as keyed, never re-resolved or dropped. Without them the call is legacy.
        project = snapshot.get('project')
        require(project is None or (isinstance(project, dict) and isinstance(identity.get('project'), dict)
                                    and type(project.get('digest')) is str and project['digest'] == identity['project'].get('digest')),
                'Inspector project snapshot is not the one its identity names')
        optional = {} if project is None else {'project': project}
        if progress is not None and forwards_progress(self.inspector.inspect):
            # An adapter that declares the check is given it, so the caller keeps its turn between
            # the adapter's own replays; one that does not is called exactly as it always was.
            optional['progress'] = progress
        report = self.inspector.inspect(list(claims), cwd, bound, environment=snapshot['environment'],
                                        interpreter=identity['interpreter'], **optional)
        counts = denominator(report['findings'])
        require(report['policy_hash'] == identity['policy_hash'], 'Inspector reported a different policy than its identity')
        absent = bool(report['findings']) and report['findings'][0].get('cause') == 'workspace directory does not exist'
        require(project is None or absent or report['context'].get('project_digest') == project['digest'],
                'Inspector replayed under a different project context than its identity')
        require(absent or (report['context'].get('environment_digest') == identity['environment_digest']
                           and report['context'].get('interpreter') == identity['interpreter']),
                'Inspector replayed under a different environment or interpreter than its identity')
        # The last check before the ledger: the inspection ran, and only an owner that still holds
        # this execution writes its verdict. A stale owner leaves the row unwritten, not a success.
        if progress is not None:
            progress('inspection_end')
        row = {'id': key, 'binding': bound, 'policy_hash': report['policy_hash'], 'inspector': identity, 'context': report['context'],
               'claims': list(claims), 'findings': report['findings'], 'denominator': counts,
               'verdict': verdict(report['findings']), 'recorded_at': utcnow(),
               'authority': 'deterministic inspection of claims; not historical truth, semantic review or human acceptance'}
        try:
            with self.store.transaction() as tx:
                fence(tx)
                previous = tx.get(BUCKET, key)
                if previous is not None:
                    return previous
                tx.put(BUCKET, key, row)
        except Exception as exc:
            if any(exc is refusal for refusal in refusals):
                # The owner ended, not the store: the transaction rolled back, so there is no row -
                # and a lost lease is not a recording failure, so it gets no notice either.
                raise
            # The inspection happened; the ledger did not take it. Say so, loudly and durably if possible.
            notice = {'id': digest([key, 'recording_failed']), 'inspection_id': key, 'reason': type(exc).__name__ + ': ' + str(exc)[:300],
                      'verdict': row['verdict'], 'denominator': counts, 'at': utcnow()}
            try:
                with self.store.transaction() as tx:
                    tx.put(NOTICES, notice['id'], notice)
            finally:
                raise ContractError('Evidence inspection could not be recorded: ' + notice['reason']) from exc
        return row

    def require_all_checked(self, tx, inspection_id, *, policy_hash=None, binding=None):
        """The consumer names the policy (and optionally the execution) it requires; a row for another is refused."""
        row = tx.get(BUCKET, inspection_id)
        require(row is not None, 'Evidence inspection missing')
        require(policy_hash is None or row['policy_hash'] == policy_hash, 'Evidence inspection was made under another policy')
        require(binding is None or all(row['binding'].get(k) == v for k, v in binding.items()),
                'Evidence inspection is bound to another execution or revision')
        require(row['verdict'] == 'all_checked', 'Evidence inspection is ' + row['verdict'] + ': '
                + ', '.join(f"{state}={count}" for state, count in row['denominator'].items() if count and state != 'claims'))
        return row
