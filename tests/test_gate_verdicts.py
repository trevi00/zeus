"""INV-GATE-001: statement-attributed verdicts consumed through one fold."""
import json
from dataclasses import asdict, replace

import pytest
from test_sdd import SOURCE, spec_data

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.sdd import SDD
from codex_harness.application.tickets import Tickets
from codex_harness.bootstrap import organization
from codex_harness.domain.gate_verdicts import GateVerdict, compact, fold_verdicts, parse_verdict
from codex_harness.domain.model import ContractError

DEFINITION = {'a': 'a' * 64, 'b': 'b' * 64}
RECEIPT = 'sha256:' + 'c' * 64


def runner(statement, verdict, sequence, exit_status=0, **changes):
    fields = dict(statement_id=statement, stage='self_verification', run_id='run-1', cycle=1,
                  definition_hash=DEFINITION[statement], artifact_hash=None, environment_hash=None,
                  verdict=verdict, origin='runner_receipt', receipt_ref=RECEIPT, exit_status=exit_status,
                  actor=None, authority=None, sequence=sequence)
    fields.update(changes)
    return GateVerdict(**fields)


def reviewer(statement, verdict, sequence, authority='authenticated_provider', **changes):
    defaults = dict(exit_status=None, receipt_ref=None, origin='reviewer_decision', actor='qa-lead',
                    authority=authority)
    return runner(statement, verdict, sequence, **{**defaults, **changes})


def retraction(statement, target, sequence):
    return runner(statement, 'RETRACT', sequence, exit_status=None, receipt_ref=None, actor='operator',
                  retracts=target)


def test_fold_attributes_by_statement_and_keeps_planned_denominator():
    fold = fold_verdicts([runner('a', 'PASS', 1)], DEFINITION, 'run-1', 1)
    assert fold['statements']['a']['state'] == 'passed' and fold['statements']['b']['state'] == 'not_run'
    assert fold['counts'] == {'passed': 1, 'failed': 0, 'error': 0, 'pending': 0, 'not_run': 1}
    assert not fold['complete'] and fold['denominator'] == 2
    both = fold_verdicts([runner('a', 'PASS', 1), runner('b', 'PASS', 2)], DEFINITION, 'run-1', 1)
    assert both['complete']


def test_foreign_run_cycle_or_definition_is_counted_not_consumed():
    verdicts = [runner('a', 'PASS', 1, run_id='run-0'), runner('a', 'PASS', 2, cycle=0),
                runner('a', 'PASS', 3, definition_hash='d' * 64), runner('b', 'FAIL', 4)]
    fold = fold_verdicts(verdicts, DEFINITION, 'run-1', 1)
    assert fold['statements']['a']['state'] == 'not_run' and fold['foreign_verdicts'] == 3
    assert fold['ignored_sequences'] == [1, 2, 3] and fold['statements']['b']['state'] == 'failed'


def test_error_withdraws_pass_partial_stays_pending_and_latest_wins():
    fold = fold_verdicts([runner('a', 'PASS', 1), runner('a', 'ERROR', 2, exit_status=3)], DEFINITION, 'run-1', 1)
    assert fold['statements']['a'] == {'state': 'error', 'verdict': 'ERROR', 'sequence': 2, 'origin': 'runner_receipt'}
    fold = fold_verdicts([runner('a', 'FAIL', 1, exit_status=1), runner('a', 'PARTIAL', 2)], DEFINITION, 'run-1', 1)
    assert fold['statements']['a']['state'] == 'pending'
    fold = fold_verdicts([runner('a', 'PARTIAL', 1), runner('a', 'PASS', 2)], DEFINITION, 'run-1', 1)
    assert fold['statements']['a']['state'] == 'passed'


def test_retraction_removes_one_verdict_and_compaction_folds_identically():
    full = [runner('a', 'PASS', 1), runner('b', 'PASS', 2), retraction('a', 1, 3), runner('a', 'FAIL', 4, exit_status=2)]
    fold = fold_verdicts(full, DEFINITION, 'run-1', 1)
    assert fold['statements']['a']['state'] == 'failed' and fold['retracted_sequences'] == [1]
    assert fold_verdicts(compact(full), DEFINITION, 'run-1', 1)['statements'] == fold['statements']
    only_retracted = [runner('a', 'PASS', 1), retraction('a', 1, 2)]
    assert fold_verdicts(only_retracted, DEFINITION, 'run-1', 1)['statements']['a']['state'] == 'not_run'
    with pytest.raises(ContractError, match='live verdict of the same statement'):
        fold_verdicts([runner('a', 'PASS', 1), retraction('b', 1, 2)], DEFINITION, 'run-1', 1)
    with pytest.raises(ContractError, match='live verdict'):
        fold_verdicts([runner('a', 'PASS', 1), retraction('a', 1, 2), retraction('a', 2, 3)], DEFINITION, 'run-1', 1)
    with pytest.raises(ContractError, match='Duplicate gate verdict sequence'):
        fold_verdicts([runner('a', 'PASS', 1), runner('b', 'PASS', 1)], DEFINITION, 'run-1', 1)


def test_exit_status_and_reviewer_authority_are_part_of_the_verdict():
    with pytest.raises(ContractError, match='non-zero exit cannot be PASS'):
        runner('a', 'PASS', 1, exit_status=1).validate()
    with pytest.raises(ContractError, match='process exit status'):
        runner('a', 'PASS', 1, exit_status=None).validate()
    with pytest.raises(ContractError, match='immutable receipt'):
        runner('a', 'PASS', 1, receipt_ref=None).validate()
    claim = reviewer('a', 'PASS', 1, authority='unauthenticated_claim')
    assert fold_verdicts([claim], DEFINITION, 'run-1', 1)['statements']['a']['state'] == 'pending'
    assert fold_verdicts([reviewer('a', 'PASS', 1)], DEFINITION, 'run-1', 1)['statements']['a']['state'] == 'passed'
    with pytest.raises(ContractError, match='requires an actor'):
        reviewer('a', 'PASS', 1, actor=None).validate()
    with pytest.raises(ContractError, match='Unknown gate verdict'):
        runner('a', 'MAYBE', 1).validate()
    with pytest.raises(ContractError, match='Unknown gate verdict fields'):
        parse_verdict({**asdict(runner('a', 'PASS', 1)), 'human_approved': True})
    assert parse_verdict(asdict(runner('a', 'PASS', 1))) == runner('a', 'PASS', 1)
    with pytest.raises(ContractError, match='definition hash'):
        fold_verdicts([], {'a': 'not-a-hash'}, 'run-1', 1)


def registered_iteration(tmp_path):
    store = MemoryStore()
    tickets = Tickets(store, organization())
    ticket = tickets.create({'title': 'Gate contract', 'problem': 'Statement attribution', 'impact': 'Stale PASS',
                             'rollback': 'Keep prior snapshot', 'evidence_refs': ['contract-test-input'],
                             'scope': ['sdd'], 'acceptance_criteria': ['Latest statement verdict'],
                             'verification': ['Memory store integration']})
    service = SDD(store, FileArtifacts(tmp_path / 'artifacts'))
    row = service.register(spec_data(), ticket['id'], 1, SOURCE)
    return service, row


def runner_receipt(service, row, statement, exit_status=0, **changes):
    """A structured receipt naming exactly what the runner judged; free text is not a receipt."""
    stage = row['stage']
    body = {'run_id': row['id'], 'cycle': row['revision'], 'statement_id': statement,
            'definition_hash': service.statement_definitions(row, stage)[statement],
            'artifact_hash': None, 'environment_hash': None, 'exit_status': exit_status, 'stdout': 'runner output'}
    body.update(changes)
    return service.artifacts.put(json.dumps(body), 'runner-receipt')['ref']


def test_iteration_records_verdicts_in_the_journal_and_advance_consumes_the_fold(tmp_path):
    service, row = registered_iteration(tmp_path)
    stage = row['stage']
    definitions = service.statement_definitions(row, stage)
    statement = 'spec_integrity'
    receipt = runner_receipt(service, row, statement)
    document = {'statement_id': statement, 'stage': stage, 'artifact_hash': None, 'environment_hash': None,
                'verdict': 'PASS', 'origin': 'runner_receipt', 'receipt_ref': receipt, 'exit_status': 0,
                'actor': None, 'authority': None}
    first = service.record_gate_verdict(row['id'], document)
    assert first['verdict']['definition_hash'] == definitions[statement] and first['verdict']['run_id'] == row['id']
    assert first['gate']['statements'][statement]['state'] == 'passed' and not first['release_authorized']
    status = service.status(row['id'])
    assert status['gates'][stage]['statements'][statement]['state'] == 'passed'
    assert status['gates'][stage]['counts']['not_run'] == len(definitions) - 1
    assert json.dumps(status['gates'])  # the fold is plain data for the review view
    blocked = service.request_advance(row['id'], status['sequence'])
    assert blocked['status'] == 'blocked' and 'not passed' in blocked['reason'] and statement not in blocked['reason']
    # A later ERROR for the same statement withdraws the PASS on every read path.
    service.record_gate_verdict(row['id'], {**document, 'verdict': 'ERROR', 'exit_status': 2,
                                            'receipt_ref': runner_receipt(service, row, statement, 2)})
    assert service.status(row['id'])['gates'][stage]['statements'][statement]['state'] == 'error'
    later = service.request_advance(row['id'], service.status(row['id'])['sequence'])
    assert f'{statement}=error' in later['reason']
    # Unauthenticated reviewer claims and unknown statements never settle anything.
    claim = {**document, 'origin': 'reviewer_decision', 'receipt_ref': None, 'exit_status': None,
             'actor': 'someone', 'authority': 'unauthenticated_claim', 'verdict': 'PASS'}
    assert service.record_gate_verdict(row['id'], claim)['gate']['statements'][statement]['state'] == 'pending'
    with pytest.raises(ContractError, match='configured decision provider'):
        service.record_gate_verdict(row['id'], {**claim, 'authority': 'authenticated_provider'})
    with pytest.raises(ContractError, match='not part of this stage'):
        service.record_gate_verdict(row['id'], {**document, 'statement_id': 'human_approved'})
    with pytest.raises(ContractError, match='non-zero exit'):
        service.record_gate_verdict(row['id'], {**document, 'exit_status': 1})
    with pytest.raises(ContractError, match='Human statements accept only reviewer decisions'):
        service.record_gate_verdict(row['id'], {**document, 'statement_id': 'human_scope',
                                                'receipt_ref': runner_receipt(service, row, 'human_scope')})
    with pytest.raises((ContractError, FileNotFoundError, ValueError)):
        service.record_gate_verdict(row['id'], {**document, 'receipt_ref': 'sha256:' + 'f' * 64})
    with pytest.raises(ContractError, match='live verdict'):
        # Sequence 1 is the spec registration event, not a verdict of this statement.
        service.record_gate_verdict(row['id'], {**document, 'verdict': 'RETRACT', 'receipt_ref': None,
                                                'exit_status': None, 'actor': 'operator', 'retracts': 1})
    with pytest.raises(ContractError, match='retraction target'):
        service.record_gate_verdict(row['id'], {**document, 'verdict': 'RETRACT', 'receipt_ref': None,
                                                'exit_status': None, 'actor': 'operator', 'retracts': 99})
    events = service.status(row['id'])['events']
    assert [e['kind'] for e in events][-3:] == ['gate_verdict_recorded', 'transition_blocked', 'gate_verdict_recorded']
    assert replace(parse_verdict(events[-1]['details']['verdict']), sequence=1).sequence == 1


class FixtureDecisionProvider:
    """Stands in for an authenticated decision channel; it verifies the exact statement it is asked about."""

    def __init__(self, authenticated, actor='qa-lead'):
        self.authenticated, self.actor, self.calls = authenticated, actor, []

    def verify(self, claim):
        self.calls.append(claim)
        return {**claim, 'authenticated': self.authenticated and claim['actor'] == self.actor}


def test_runner_receipt_must_bind_the_verdict_it_supports(tmp_path):
    # Review counterexample (PR #46): free text with a caller-written exit_status is not evidence.
    service, row = registered_iteration(tmp_path)
    stage = row['stage']
    base = {'statement_id': 'spec_integrity', 'stage': stage, 'artifact_hash': None, 'environment_hash': None,
            'verdict': 'PASS', 'origin': 'runner_receipt', 'exit_status': 0, 'actor': None, 'authority': None}
    before = service.status(row['id'])['sequence']
    free_text = service.artifacts.put('runner output', 'fixture')['ref']
    with pytest.raises((ContractError, ValueError)):
        service.record_gate_verdict(row['id'], {**base, 'receipt_ref': free_text})
    for drift in ({'exit_status': 1}, {'statement_id': 'human_scope'}, {'run_id': 'other-run'},
                  {'cycle': row['revision'] + 1}, {'definition_hash': 'e' * 64}, {'artifact_hash': 'a' * 64}):
        receipt = runner_receipt(service, row, 'spec_integrity', **drift)
        with pytest.raises(ContractError, match='Runner receipt does not bind this verdict'):
            service.record_gate_verdict(row['id'], {**base, 'receipt_ref': receipt})
    assert service.status(row['id'])['sequence'] == before, 'refused receipts leave no journal event'
    recorded = service.record_gate_verdict(row['id'], {**base, 'receipt_ref': runner_receipt(service, row, 'spec_integrity')})
    assert recorded['gate']['statements']['spec_integrity']['state'] == 'passed'
    event = service.status(row['id'])['events'][-1]
    assert event['details']['receipt_binding']['statement_id'] == 'spec_integrity'
    assert event['details']['receipt_binding']['exit_status'] == 0


def test_human_statements_settle_only_through_the_provider_verification(tmp_path):
    service, row = registered_iteration(tmp_path)
    stage = row['stage']
    claim = {'statement_id': 'human_scope', 'stage': stage, 'artifact_hash': None, 'environment_hash': None,
             'verdict': 'PASS', 'origin': 'reviewer_decision', 'receipt_ref': None, 'exit_status': None,
             'actor': 'qa-lead', 'authority': 'authenticated_provider'}
    # A provider object that cannot verify is not a provider; configuring `object()` grants nothing.
    service.human_provider = object()
    with pytest.raises(ContractError, match='Decision provider must verify'):
        service.record_gate_verdict(row['id'], claim)
    # The provider says this actor is not authenticated: the claim is kept, pending, never passed.
    service.human_provider = FixtureDecisionProvider(authenticated=False)
    kept = service.record_gate_verdict(row['id'], claim)
    assert kept['verdict']['authority'] == 'unauthenticated_claim'
    assert kept['gate']['statements']['human_scope']['state'] == 'pending'
    # Authenticated for another actor only: the impersonating claim stays pending.
    service.human_provider = FixtureDecisionProvider(authenticated=True, actor='someone-else')
    assert service.record_gate_verdict(row['id'], claim)['gate']['statements']['human_scope']['state'] == 'pending'
    # A provider whose answer names a different statement or verdict is refused outright.
    class Drifting(FixtureDecisionProvider):
        def verify(self, claim):
            return {**super().verify(claim), 'verdict': 'FAIL'}
    service.human_provider = Drifting(authenticated=True)
    with pytest.raises(ContractError, match='does not bind this reviewer decision'):
        service.record_gate_verdict(row['id'], claim)
    provider = FixtureDecisionProvider(authenticated=True)
    service.human_provider = provider
    passed = service.record_gate_verdict(row['id'], claim)
    assert passed['gate']['statements']['human_scope']['state'] == 'passed' and not passed['release_authorized']
    assert provider.calls[-1]['statement_id'] == 'human_scope' and provider.calls[-1]['run_id'] == row['id']
    event = service.status(row['id'])['events'][-1]
    assert event['details']['provider_decision'] == {'authenticated': True, 'provider': 'FixtureDecisionProvider'}


def test_retraction_is_bound_to_run_cycle_stage_and_definition():
    # Review counterexample (PR #46): a foreign run's RETRACT must not remove this run's PASS.
    foreign = retraction('a', 1, 2)
    foreign = GateVerdict(**{**asdict(foreign), 'run_id': 'run-9'})
    fold = fold_verdicts([runner('a', 'PASS', 1), foreign], DEFINITION, 'run-1', 1)
    assert fold['statements']['a']['state'] == 'passed' and fold['foreign_verdicts'] == 1
    assert fold['ignored_sequences'] == [2] and fold['retracted_sequences'] == []
    other_cycle = GateVerdict(**{**asdict(retraction('a', 1, 2)), 'cycle': 2})
    assert fold_verdicts([runner('a', 'PASS', 1), other_cycle], DEFINITION, 'run-1', 1)['statements']['a']['state'] == 'passed'
    # Same run and cycle but a retraction aimed at a verdict of another definition or stage is malformed.
    for change in ({'definition_hash': 'd' * 64}, {'stage': 'qa_evidence'}):
        with pytest.raises(ContractError, match='same statement and binding'):
            fold_verdicts([runner('a', 'PASS', 1), GateVerdict(**{**asdict(retraction('a', 1, 2)), **change})],
                          DEFINITION, 'run-1', 1)
    # Compaction keeps the foreign retraction out of the picture as well.
    assert fold_verdicts(compact([runner('a', 'PASS', 1), foreign]), DEFINITION, 'run-1', 1)['statements'] == fold['statements']
