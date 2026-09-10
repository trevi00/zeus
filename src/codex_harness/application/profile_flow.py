"""Profile flow: consent before collection, minimization before model input, checked rendering, bound receipts.

Nothing here collects a real conversation or calls a model. It records the consent a user gave to
one policy version, turns records into a model-input bundle where every record is either ready
(minimized and scanned), blocked, out of scope, not consented or a named read/parse failure, keeps
only counts and kinds in the ledger (never the matched text), verifies a rendered profile field by
field and binds the whole run to its revision and environment.
"""
from codex_harness.domain.model import digest, require, utcnow
from codex_harness.domain.profile_privacy import check_render, minimize, parse_consent, parse_policy

CONSENTS = 'profile_consents'
RUNS = 'profile_runs'


def _revision(value, name):
    require(type(value) is str and (len(value) == 40 and all(c in '0123456789abcdef' for c in value) or value == 'unversioned'),
            f'{name} must be a Git commit hash or "unversioned"')


class ProfileFlow:
    def __init__(self, store, scratch):
        self.store, self.scratch = store, scratch

    def record_consent(self, policy, consent):
        policy = parse_policy(policy)
        consent = parse_consent(consent, policy)
        key = digest(['profile-consent-v1', consent['user'], consent['policy_hash'], consent['at'], consent['choice']])
        row = {'id': key, **consent, 'policy': policy, 'recorded_at': utcnow()}
        with self.store.transaction() as tx:
            existing = tx.get(CONSENTS, key)
            if existing is not None:
                return existing
            tx.put(CONSENTS, key, row)
        return row

    def latest_consent(self, tx, user, policy_hash):
        rows = [r for r in tx.scan(CONSENTS) if r['user'] == user and r['policy_hash'] == policy_hash]
        return max(rows, key=lambda r: r['at']) if rows else None

    def prepare_model_input(self, run_id, *, owner, user, policy, records, binding, lease_until):
        """Records become a bundle only under a current grant; the ledger keeps counts and kinds, never text."""
        policy = parse_policy(policy)
        require(isinstance(binding, dict) and set(binding) == {'source_revision', 'environment'}, 'Binding requires source_revision and environment')
        _revision(binding['source_revision'], 'source_revision')
        require(type(binding['environment']) is str and binding['environment'], 'environment must be a label')
        require(isinstance(records, list), 'Records must be a list')
        with self.store.transaction() as tx:
            consent = self.latest_consent(tx, user, policy['policy_hash'])
        require(consent is not None, 'No consent recorded for this user and policy version')
        if not consent['collect']:
            row = self._run(run_id, owner, user, policy, consent, binding, status='not_consented', results=[], bundle=None)
            return row
        results = [minimize(record, policy, consent) for record in records[:policy['read_scope']['max_records']]]
        counts = {}
        for result in results:
            counts[result['status']] = counts.get(result['status'], 0) + 1
        ready = [{**r['input'], 'sequence': i} for i, r in enumerate(r for r in results if r['status'] == 'ready')]
        bundle = None
        if ready and policy['retention']['temporary'] == 'run':
            bundle = self.scratch.write(run_id, owner, lease_until, {'policy_hash': policy['policy_hash'], 'model': policy['model'], 'records': ready})
        row = self._run(run_id, owner, user, policy, consent, binding, status='ready' if ready else 'empty',
                        results=[{k: v for k, v in r.items() if k != 'input'} for r in results], bundle=bundle,
                        counts=counts, skipped=max(0, len(records) - policy['read_scope']['max_records']))
        if ready and policy['retention']['temporary'] == 'none':
            # No temporary storage under this policy: the input exists only in this return value,
            # never on disk and never in the ledger row (review, PR #63).
            return {**row, 'input_records': ready, 'temporary_storage': 'none'}
        return row

    def _run(self, run_id, owner, user, policy, consent, binding, *, status, results, bundle, counts=None, skipped=0):
        findings = {}
        for result in results:
            for kind, n in result.get('findings', {}).items():
                findings[kind] = findings.get(kind, 0) + n
        row = {'id': run_id, 'owner': owner, 'user': user, 'policy_hash': policy['policy_hash'], 'consent_id': consent['id'],
               'model': policy['model'], 'binding': binding, 'status': status, 'counts': counts or {}, 'records_offered': len(results) + skipped,
               'records_skipped_by_cap': skipped, 'findings': findings, 'results': results, 'bundle': bundle,
               'note': 'the model input is the bundle file; this row holds statuses, counts and kinds, no record text',
               'authority': 'not a user acceptance, not a model qualification, not deployment', 'recorded_at': utcnow()}
        with self.store.transaction() as tx:
            require(tx.get(RUNS, run_id) is None, f'Run {run_id} already recorded')
            tx.put(RUNS, run_id, row)
        return row

    def render(self, run_id, profile):
        """A rendered profile is bound to its run; the verdict names unchecked fields and never says none for them."""
        report = check_render(profile)
        with self.store.transaction() as tx:
            row = tx.get(RUNS, run_id)
            require(row is not None, 'Run missing')
            require(row['status'] == 'ready', f'Run {run_id} produced no model input; nothing to render')
            row = {**row, 'render': {'verdict': report['verdict'], 'findings': report['findings'], 'unchecked': report['unchecked'],
                                     'checked_at': utcnow(), 'redaction_scope': 'every rendered field of every dimension'}}
            tx.put(RUNS, run_id, row)
        return {**report, 'run_id': run_id, 'renderable': report['verdict'] == 'none_detected_in_checked_fields'}

    def finish(self, run_id, owner):
        """The owner deletes its temporary bundle; the ledger keeps the run and the deletion."""
        receipt = self.scratch.cleanup(run_id, owner)
        with self.store.transaction() as tx:
            row = tx.get(RUNS, run_id)
            require(row is not None, 'Run missing')
            require(row['owner'] == owner, 'Only the owning worker finishes a run')
            tx.put(RUNS, run_id, {**row, 'finished_at': utcnow(), 'cleanup': receipt})
        return receipt
