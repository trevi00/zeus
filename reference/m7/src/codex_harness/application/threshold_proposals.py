"""Archive proposal calculations for later review; never authorize activation."""
import json

from codex_harness.domain.model import ContractError, canonical, digest, require, utcnow
from codex_harness.domain.skill_history import MAX_EVENTS
from codex_harness.domain.skill_import import validate_source
from codex_harness.domain.threshold_proposals import propose_threshold_changes


class ThresholdProposals:
    def __init__(self, store, artifacts, policy_provider, native_replay=None):
        self.store, self.artifacts, self.policy_provider = store, artifacts, policy_provider
        self.native_replay = native_replay

    def collect(self, project, *, legacy_source=None, min_sample=10, evaluation_round=0):
        require(type(evaluation_round) is int and evaluation_round >= 0, 'Invalid evaluation round')
        if legacy_source is not None:
            validate_source(legacy_source)
        policy = self.policy_provider()
        bucket = 'legacy_skill_imports' if legacy_source is not None else 'skill_history'
        key = digest([project, legacy_source]) if legacy_source is not None else project
        with self.store.transaction() as tx:
            state = tx.get(bucket, key) or {'events': []}
        events = state['events'][-MAX_EVENTS:]
        basis = digest({'project': project, 'policy': policy, 'events': events, 'legacy_source': legacy_source,
                        'source_ref': state.get('source_ref'), 'min_sample': min_sample,
                        'native_evaluator': self.native_replay is not None, 'collection_version': 2,
                        'evaluation_round': evaluation_round})
        with self.store.transaction() as tx:
            previous = tx.get('threshold_collection_inputs', basis)
            if previous:
                return tx.get('threshold_proposal_runs', previous['run_id'])
        proposals = propose_threshold_changes(events_by_source={'skill-match': events},
            current_values=policy['values'], policy_revision=policy['revision'], min_sample=min_sample)
        document = {'project_key': project, 'legacy_source': legacy_source,
            'collection_basis': basis,
            'evaluation_round': evaluation_round,
            'source_ref': state.get('source_ref'), 'policy': policy, 'events': events,
            'min_sample': min_sample, 'proposals': proposals}
        values = sorted({policy['values']['skill_match.FULL_BODY_MIN_SCORE'],
                         *(row['value'] for proposal in proposals for row in proposal['alternatives'])})
        document['native_routing'] = (self.native_replay.evaluate(events, values) if self.native_replay else
            {'status': 'unavailable', 'reason': 'native_evaluator_not_configured', 'activation_ready': False})
        try:
            json.dumps(document, allow_nan=False)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ContractError('Proposal evidence must be finite JSON') from exc
        receipt = self.artifacts.put(canonical(document), 'threshold-proposal-corpus')
        run_id = digest([project, receipt['ref']])
        rows = []
        for proposal in proposals:
            partitions = proposal['report']['partitions']
            blockers = ['native_task_success_and_release_review_required']
            if document['native_routing'].get('status') != 'complete':
                blockers.append('native_replay_incomplete')
            if not proposal['reference_accepted']:
                blockers.append('reference_gate_rejected')
            if not partitions or any(part['proposed_admitted_entries'] == 0 for part in partitions.values()):
                blockers.append('empty_admission')
            if legacy_source is not None:
                blockers.append('historical_policy_and_skill_versions_unknown')
            rows.append({'id': digest([run_id, proposal['id']]), 'run_id': run_id,
                'project_key': project, 'proposal': proposal, 'evidence_ref': receipt['ref'],
                'status': 'calculated', 'activation_ready': False, 'activation_blockers': blockers})
        with self.store.transaction() as tx:
            # INV-NATIVE-REPLAY-001: first committed evaluation is immutable for this input basis.
            previous_input = tx.get('threshold_collection_inputs', basis)
            if previous_input:
                return tx.get('threshold_proposal_runs', previous_input['run_id'])
            previous = tx.get('threshold_proposal_runs', run_id)
            if previous:
                return previous
            run = {'id': run_id, 'project_key': project, 'policy_revision': policy['revision'],
                'evaluation_round': evaluation_round,
                'evidence_ref': receipt['ref'], 'proposals': rows, 'status': 'calculated',
                'activation_ready': False, 'created_at': utcnow()}
            tx.put('threshold_proposal_runs', run_id, run)
            tx.put('threshold_collection_inputs', basis, {'run_id': run_id})
            for row in rows:
                tx.put('threshold_proposals', row['id'], row)
        return run
