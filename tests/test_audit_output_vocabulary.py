"""One path-disposition vocabulary across provider output schema, packaged schema and domain.

2026-09-20 canary `8cf37c35-e374-4e5b-8bb6-a980b40afaf2`: the provider answered disposition
`partial`, the unconstrained schema accepted it and `parse_record` raised
`ContractError: Unknown disposition`, so the partition kept generation 0 and all 32 paths.
"""
import copy
import json
from dataclasses import asdict
from importlib.resources import files
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError, validate
from test_research_audits import (  # noqa: F401  `audit` is a pytest fixture: importing registers it
    FixtureRunner,
    activate_fixture,
    audit,
)

from codex_harness.adapters.audit_execution import AuditExecution, output_definitions
from codex_harness.domain.model import ContractError, canonical, envelope
from codex_harness.domain.research import PATH_DISPOSITIONS, PathDisposition, parse_record

REJECTED = ['partial', 'Partial', 'semantic ', 'complete', '', 'unreviewed_observed_asset']


def packaged_disposition():
    body = json.loads(files('codex_harness.resources').joinpath('research.schema.json').read_text())
    return body['$defs']['PathDisposition']['properties']['disposition']


def body(disposition, path='cGF0aA=='):
    return asdict(PathDisposition(path, disposition, [], [], '', [], '', []))


def wire(record, identity='path'):
    """A record body without its identity field: the assigned key carries that identity."""
    return {k: v for k, v in record.items() if k != identity}


def assigned(record, **fields):
    """The assigned wire shape: one nullable body per identity, the identity only in the key."""
    return {'paths': {record['path']: wire(record)}, 'subsystems': {},
            'open_questions': [], 'cursor': 'c', **fields}


def assigned_answer(part, paths=None, **fields):
    """Every assigned identity present exactly once: a body for analyzed work, null for the rest."""
    paths = paths or {}
    return {'paths': {key: paths.get(key) for key in part['paths']},
            'subsystems': {name: None for name in part['subsystems']},
            'open_questions': [], 'cursor': 'c', **fields}


def test_static_declaration_and_domain_authority_cannot_drift():
    expected = {'type': 'string', 'enum': list(PATH_DISPOSITIONS)}
    assert len(set(PATH_DISPOSITIONS)) == 6 and 'partial' not in PATH_DISPOSITIONS
    assert packaged_disposition() == expected
    assert output_definitions()['PathDisposition']['properties']['disposition'] == expected
    assert AuditExecution.typed_schema('PathDisposition')['properties']['disposition'] == expected
    # The nested definition actually consumed by partition output: the generic array definition
    # when unscoped, the assigned identity-keyed body when a partition is assigned.
    assert AuditExecution.partition_schema()['$defs']['PathDisposition']['properties'][
        'disposition'] == expected
    scoped = AuditExecution.partition_schema({'paths': ['cGF0aA=='], 'subsystems': ['core']})['$defs']
    assert scoped['AssignedPathDisposition']['properties']['disposition'] == expected
    assert 'path' not in scoped['AssignedPathDisposition']['properties']


@pytest.mark.parametrize('disposition', PATH_DISPOSITIONS)
def test_supported_values_pass_both_boundaries(disposition):
    record = body(disposition)
    validate(record, AuditExecution.typed_schema('PathDisposition'))
    validate({'paths': [record], 'subsystems': [], 'open_questions': [], 'cursor': 'c'},
             AuditExecution.partition_schema())
    validate(assigned(record),
             AuditExecution.partition_schema({'paths': [record['path']], 'subsystems': []}))


@pytest.mark.parametrize('disposition', REJECTED)
def test_unknown_values_are_rejected_and_never_normalized(disposition):
    record = body(disposition)
    scoped = AuditExecution.partition_schema({'paths': [record['path']], 'subsystems': []})
    with pytest.raises(ValidationError):
        validate(record, AuditExecution.typed_schema('PathDisposition'))
    with pytest.raises(ValidationError):
        validate({k: v for k, v in record.items() if k != 'path'},
                 {**scoped['$defs']['AssignedPathDisposition'], '$defs': scoped['$defs']})
    with pytest.raises(ValidationError):
        validate({'paths': [record], 'subsystems': [], 'open_questions': [], 'cursor': 'c'},
                 AuditExecution.partition_schema())
    with pytest.raises(ValidationError):
        validate(assigned(record), scoped)
    with pytest.raises(ContractError, match='Unknown disposition'):
        parse_record({'version': 1, 'kind': 'PathDisposition', 'record': record})


def test_regression_discriminates_the_pre_fix_declaration():
    """Control: the previous unconstrained string accepts exactly what is now refused."""
    document = {'paths': [body('partial')], 'subsystems': [], 'open_questions': [], 'cursor': 'c'}
    pre_fix = copy.deepcopy(AuditExecution.partition_schema())
    pre_fix['$defs']['PathDisposition']['properties']['disposition'] = {'type': 'string'}
    validate(document, pre_fix)  # the canary boundary: schema accepted, only the domain refused
    with pytest.raises(ValidationError):
        validate(document, AuditExecution.partition_schema())


def test_conditional_evidence_rules_survive_the_named_constant():
    ref = 'sha256:' + '0' * 64
    for record, message in [
            (body('semantic'), 'Missing path evidence'),
            (asdict(PathDisposition('p', 'generated', [ref], [], 'why', [], '', [])),
             'Missing generator/original link'),
            (asdict(PathDisposition('p', 'binary', [ref], [], 'why', [], '', [])),
             'Missing binary inspection receipt')]:
        with pytest.raises(ContractError, match=message):
            PathDisposition(**record).validate()
    # Unreviewed and unavailable remain representable without evidence or justification.
    for disposition in ('unreviewed', 'unavailable'):
        PathDisposition(**body(disposition)).validate()


def partition_task(service, record, name='partial-vocabulary'):
    part = next(p for p in service.partition(record['id']) if p['paths'])
    message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_partition',
                       {'audit_id': record['id'], 'partition_id': part['partition_id'],
                        'generation': part['generation']}, name)
    service.workflow.submit(message)
    task = service.workflow.claim('worker:github', 'fixture')
    executor = SimpleNamespace(service=SimpleNamespace(store=service.store),
                               artifacts=service.artifacts, workflow=service.workflow)
    # Fixture receipts, not actual isolated or Codex verification.
    return part, task, AuditExecution(executor, FixtureRunner(service.artifacts))


def test_partial_inspection_checkpoints_as_unreviewed_without_review_credit(
        audit, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = partition_task(service, record)
    partial = body('unreviewed', part['paths'][0])
    partial['justification'] = 'read lines 0-40 of 900; the remaining body is not inspected'
    answer = assigned_answer(part, {partial['path']: wire(partial)},
                             open_questions=['Finish reading the remaining body of the assigned path'],
                             cursor='40')

    def run_model(task, objective, evidence, result_schema):
        if 'commands' in result_schema['properties']:
            return {'commands': []}
        assert 'partial is not a disposition' in objective
        validate(answer, result_schema)
        with pytest.raises(ValidationError):
            validate({**answer, 'paths': {**answer['paths'],
                partial['path']: {**wire(partial), 'disposition': 'partial'}}}, result_schema)
        return answer

    monkeypatch.setattr(execution, 'run_model', run_model)
    saved = execution.execute(task)
    assert saved['generation'] == part['generation'] + 1
    assert saved['remaining_paths'] == part['remaining_paths'], 'unreviewed earns no coverage'
    assert saved['open_questions'] == answer['open_questions'] and saved['cursor'] == '40'
    coverage = service.coverage(record['id'])
    assert len(coverage['remaining_paths']) == len(record['inventory'])
    assert coverage['remaining_subsystems'] == ['core']
    assert not coverage['adoption_eligible'] and not coverage['whole_analysis_complete']
    with service.store.transaction() as tx:
        stored = [r['record'] for r in tx.scan('research_paths')]
        assert stored == [partial], 'the explanation is persisted verbatim'
        assert any(r['record'] == partial for r in tx.scan('research_evidence_history'))


def test_provider_partial_answer_still_fails_closed_in_the_application_path(
        audit, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """The observed canary shape: schema bypassed, domain refuses, nothing is credited.

    The domain vocabulary is unchanged by the 2026-09-21 reframe; only the disposition of the
    refused draft changed, from a stopped execution to retained `analysis_rejected` work.
    """
    from codex_harness.domain.model import digest

    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = partition_task(service, record, 'partial-refusal')
    refused = body('partial', part['paths'][0])
    refused['justification'] = 'partially read'
    answer = assigned_answer(part, {refused['path']: wire(refused)}, cursor='partially read')
    draft = service.artifacts.put('the refused draft, retained verbatim', 'fixture')['ref']

    def run_model(task, objective, evidence, result_schema):
        if 'commands' in result_schema['properties']:
            return {'commands': []}
        # Deliberately unvalidated output, as the provider actually returned, with the executor's
        # own artifact reference added after validation exactly as `Executor._run` adds it.
        return {**answer, 'execution_ref': draft}

    monkeypatch.setattr(execution, 'run_model', run_model)
    analysis = execution.execute(task)['analysis']
    assert analysis['outcome'] == 'analysis_rejected' and analysis['execution_ref'] == draft
    assert analysis['error_digest'] == digest('Unknown disposition')
    assert 'partial' not in canonical(analysis) and 'partially read' not in canonical(analysis)
    with service.store.transaction() as tx:
        assert tx.scan('research_paths') == []
        assert tx.get('research_partitions', part['partition_id']) == part
