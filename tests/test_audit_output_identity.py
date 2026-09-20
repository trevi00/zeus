"""One nullable result per immutable assigned identity (INV-RESEARCH-002).

2026-09-21 host canary task `d1133291-1151-4ffd-987a-6671cd0f34bd` stopped with
`retry/ContractError: Duplicate coverage`: output artifact
`sha256:0b573a6e14db5bd4534f4cdfb3f6f790722259e5e731eb0988073d0f412c43f4` carried five
`PathDisposition` rows, two of them for the identity
`ZG9jcy9jb250cmlidXRpbmcvcmV2aWV3LWNvbnZlbnRpb25zLm1k`. The enum-constrained array bound
membership but not ownership, so the partition kept generation 0 and all 32 paths.

Every execution here is the mocked model boundary of `AuditExecution` over a real `MemoryStore`
`ResearchAudits.checkpoint`; the runner receipts are `FixtureRunner` injections, not isolated or
Codex verification, and no provider was called.
"""
import base64
import json
from dataclasses import asdict

import pytest
from jsonschema import ValidationError, validate
from test_audit_output_vocabulary import partition_task
from test_research_audits import (  # noqa: F401  `audit` is a pytest fixture: importing registers it
    activate_fixture,
    audit,
)

from codex_harness.adapters.audit_execution import (
    STRINGS,
    TEXT,
    AuditExecution,
    output_definitions,
    schema,
)
from codex_harness.adapters.output_schema import preflight
from codex_harness.domain.model import ContractError
from codex_harness.domain.research import PathDisposition, SubsystemAnalysis

PATH = base64.b64encode(b'normal').decode()
OTHER = base64.b64encode(b'other').decode()


def legacy_partition_schema(partition):
    """The pre-fix assigned wire shape, reconstructed verbatim as the discriminating control.

    Identity membership was an enum inside an array item, which is exactly what let one identity
    appear twice in the observed canary output.
    """
    defs = output_definitions()
    result_schema = schema(paths={'type': 'array', 'items': {'$ref': '#/$defs/PathDisposition'}},
                           subsystems={'type': 'array', 'items': {'$ref': '#/$defs/SubsystemAnalysis'}},
                           open_questions=STRINGS, cursor=TEXT)
    result_schema['$defs'] = defs
    for field, kind, identity in [('paths', 'PathDisposition', 'path'),
                                  ('subsystems', 'SubsystemAnalysis', 'name')]:
        if partition[field]:
            defs[kind]['properties'][identity] = {'type': 'string', 'enum': list(partition[field])}
        else:
            result_schema['properties'][field]['maxItems'] = 0
    return result_schema


def path_body(ref, disposition='semantic', **fields):
    record = asdict(PathDisposition('', disposition, [ref], ['symbol'], 'traced', [], '', []))
    return {**{k: v for k, v in record.items() if k != 'path'}, **fields}


def subsystem_body(ref, **fields):
    record = asdict(SubsystemAnalysis('', [PATH], ['contract'], ['main'], ['impl'], ['caller'],
                                      ['config'], ['git'], ['failure'], [], [], [ref], [], [],
                                      [{'test': 'upstream suite', 'reason': 'dependencies unavailable',
                                        'follow_up': 'run in verified runner'}]))
    return {**{k: v for k, v in record.items() if k != 'name'}, **fields}


def answer_for(part, bodies=None, **fields):
    bodies = bodies or {}
    return {'paths': {key: bodies.get(key) for key in part['paths']},
            'subsystems': {name: bodies.get(name) for name in part['subsystems']},
            'open_questions': [], 'cursor': 'checkpoint', **fields}


def run_with(execution, monkeypatch, answer, validate_against=True):
    """Mock only the model turn: inspection planning, decoding and checkpointing stay real."""
    def run_model(task, objective, evidence, result_schema):
        if 'commands' in result_schema['properties']:
            return {'commands': []}
        assert 'null' in objective and 'partition.paths' in objective
        if validate_against:
            validate(answer, result_schema)
        return answer
    monkeypatch.setattr(execution, 'run_model', run_model)


# --- the assigned wire shape -------------------------------------------------------------

@pytest.mark.parametrize('partition', [
    {'paths': [PATH, OTHER], 'subsystems': []},
    {'paths': [], 'subsystems': ['core']},
    {'paths': [], 'subsystems': []},
], ids=['paths-only', 'subsystems-only', 'empty'])
def test_assigned_schema_binds_one_nullable_body_per_identity(partition):
    result_schema = AuditExecution.partition_schema(partition)
    preflight(result_schema)
    ref = 'sha256:' + '0' * 64
    for field, identity, body in [('paths', 'path', path_body(ref)),
                                  ('subsystems', 'name', subsystem_body(ref))]:
        declared = result_schema['properties'][field]
        assert declared['type'] == 'object' and declared['additionalProperties'] is False
        assert list(declared['properties']) == partition[field] == declared['required']
        for key in partition[field]:
            assert declared['properties'][key] == {'anyOf': [
                {'type': 'null'}, {'$ref': '#/$defs/Assigned' + (
                    'PathDisposition' if field == 'paths' else 'SubsystemAnalysis')}]}
        if not partition[field]:
            continue
        key = partition[field][0]
        document = {**answer_for(partition), field: {**answer_for(partition)[field], key: body}}
        validate(document, result_schema)
        for invalid in ({**document, field: {}},
                        {**document, field: {**document[field], 'unassigned': None}},
                        {**document, field: {key: {**body, identity: key}}},
                        {**document, field: [{**body, identity: key}]},
                        {**document, field: {key: {k: v for k, v in body.items() if k != identity}
                                             | {'extra': 'field'}}}):
            with pytest.raises(ValidationError):
                validate(invalid, result_schema)
    # Nothing analyzed at all is a valid, truthful answer.
    validate(answer_for(partition), result_schema)


def test_empty_assignment_is_an_empty_object():
    result_schema = AuditExecution.partition_schema({'paths': [], 'subsystems': []})
    assert result_schema['properties']['paths'] == {
        'type': 'object', 'additionalProperties': False, 'properties': {}, 'required': []}
    validate({'paths': {}, 'subsystems': {}, 'open_questions': [], 'cursor': 'c'}, result_schema)
    for invalid in ({'paths': [], 'subsystems': {}, 'open_questions': [], 'cursor': 'c'},
                    {'paths': {'any': None}, 'subsystems': {}, 'open_questions': [], 'cursor': 'c'}):
        with pytest.raises(ValidationError):
            validate(invalid, result_schema)


def test_assigned_bodies_keep_the_domain_vocabulary_and_conditional_rules():
    partition = {'paths': [PATH], 'subsystems': ['core']}
    defs = AuditExecution.partition_schema(partition)['$defs']
    packaged = output_definitions()
    for kind, identity in [('PathDisposition', 'path'), ('SubsystemAnalysis', 'name')]:
        body = defs['Assigned' + kind]
        assert identity not in body['properties'] and identity not in body['required']
        assert body['properties'] == {k: v for k, v in packaged[kind]['properties'].items()
                                      if k != identity}
        assert set(body['required']) == set(body['properties'])
        assert body['additionalProperties'] is False
    assert defs['AssignedPathDisposition']['properties']['disposition']['enum'] == [
        'unreviewed', 'semantic', 'generated', 'duplicate', 'binary', 'unavailable']


# --- the old repeated array versus the new boundary --------------------------------------

def test_the_old_schema_accepts_two_rows_for_one_identity_and_the_new_shape_cannot():
    """The canary's own shape: accepted by the former assigned schema, refused by this one."""
    partition = {'paths': [PATH, OTHER], 'subsystems': []}
    ref = 'sha256:' + '0' * 64
    repeated = [{**path_body(ref), 'path': PATH},
                {**path_body(ref, 'unreviewed'), 'path': PATH}]
    document = {'paths': repeated, 'subsystems': [], 'open_questions': [], 'cursor': 'c'}
    validate(document, legacy_partition_schema(partition))  # membership bound, ownership not
    assert len({row['path'] for row in repeated}) == 1 and len(repeated) == 2
    with pytest.raises(ValidationError):
        validate(document, AuditExecution.partition_schema(partition))
    with pytest.raises(ContractError, match='Assigned output identities changed'):
        AuditExecution.decode_assigned('PathDisposition', 'path', partition['paths'], repeated)
    # The new wire shape cannot express a second record for a key: a repeated JSON key is resolved
    # by the parser before this boundary exists, so no contradictory second body ever arrives, and
    # the boundary itself never merges, drops or reorders decoded records.
    wire = json.loads('{"paths": {"%s": %s, "%s": %s}, "subsystems": {}}'
                      % (PATH, json.dumps(path_body(ref)), PATH,
                         json.dumps(path_body(ref, 'unreviewed'))))
    assert list(wire['paths']) == [PATH] and wire['paths'][PATH]['disposition'] == 'unreviewed'


@pytest.mark.parametrize('results, message', [
    ({}, 'Assigned output identities changed'),
    ({PATH: None}, 'Assigned output identities changed'),
    ({PATH: None, OTHER: None, 'foreign': None}, 'Assigned output identities changed'),
    ([], 'Assigned output identities changed'),
    (None, 'Assigned output identities changed'),
    ({PATH: [], OTHER: None}, 'Invalid assigned output record'),
    ({PATH: 'semantic', OTHER: None}, 'Invalid assigned output record'),
])
def test_malformed_assigned_results_are_refused_never_normalized(results, message):
    with pytest.raises(ContractError, match=message):
        AuditExecution.decode_assigned('PathDisposition', 'path', [PATH, OTHER], results)


def test_a_body_may_not_carry_its_own_identity_or_a_malformed_field():
    ref = 'sha256:' + '0' * 64
    for body, message in [({**path_body(ref), 'path': OTHER}, 'Invalid assigned output record'),
                          ({**path_body(ref), 'path': PATH}, 'Invalid assigned output record'),
                          (path_body(ref, 'partial'), 'Unknown disposition'),
                          ({k: v for k, v in path_body(ref).items() if k != 'method'},
                           'Invalid typed audit fields'),
                          ({**path_body(ref), 'symbols': 'symbol'}, 'Expected audit list')]:
        with pytest.raises(ContractError, match=message):
            AuditExecution.decode_assigned('PathDisposition', 'path', [PATH], {PATH: body})


def test_decoding_injects_the_trusted_key_and_omits_nulls():
    ref = 'sha256:' + '0' * 64
    decoded = AuditExecution.decode_assigned('PathDisposition', 'path', [PATH, OTHER],
                                             {PATH: path_body(ref), OTHER: None})
    assert [record.path for record in decoded] == [PATH]
    assert decoded[0].disposition == 'semantic'
    assert AuditExecution.decode_assigned('SubsystemAnalysis', 'name', [], {}) == []


# --- the real checkpoint boundary ---------------------------------------------------------

def test_one_partial_record_with_nulls_preserves_the_remaining_scope(
        audit, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = partition_task(service, record, 'assigned-partial')
    assert len(part['paths']) > 1
    ref = service.artifacts.put('one traced path', 'fixture')['ref']
    analyzed = part['paths'][0]
    answer = answer_for(part, {analyzed: path_body(ref)},
                        open_questions=['the remaining assigned paths are not read'], cursor='1')
    run_with(execution, monkeypatch, answer)
    saved = execution.execute(task)
    assert saved['generation'] == part['generation'] + 1
    assert saved['remaining_paths'] == sorted(set(part['paths']) - {analyzed})
    assert saved['open_questions'] == answer['open_questions']
    with service.store.transaction() as tx:
        stored = [r['record'] for r in tx.scan('research_paths')]
        assert [r['path'] for r in stored] == [analyzed], 'nulls credit nothing'
        assert stored[0]['disposition'] == 'semantic'
    coverage = service.coverage(record['id'])
    assert len(coverage['remaining_paths']) == len(record['inventory']) - 1
    assert not coverage['adoption_eligible'] and not coverage['whole_analysis_complete']


def test_all_null_results_advance_the_generation_without_any_coverage(
        audit, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = partition_task(service, record, 'assigned-null')
    run_with(execution, monkeypatch, answer_for(part, open_questions=['nothing analyzed yet']))
    saved = execution.execute(task)
    assert saved['remaining_paths'] == part['remaining_paths']
    assert saved['generation'] == part['generation'] + 1
    with service.store.transaction() as tx:
        assert tx.scan('research_paths') == []


@pytest.mark.parametrize('shape', ['legacy_array', 'foreign_key', 'missing_key', 'inner_identity'],)
def test_invalid_assigned_output_fails_before_the_checkpoint(
        audit, monkeypatch, shape):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """A bypassed output schema still cannot reach `ResearchAudits.checkpoint`."""
    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, execution = partition_task(service, record, 'assigned-invalid-' + shape)
    ref = service.artifacts.put('one traced path', 'fixture')['ref']
    analyzed = part['paths'][0]
    valid = answer_for(part, {analyzed: path_body(ref)})
    bodies = {'legacy_array': [{**path_body(ref), 'path': analyzed},
                               {**path_body(ref, 'unreviewed'), 'path': analyzed}],
              'foreign_key': {**valid['paths'], 'Zm9yZWlnbg==': path_body(ref)},
              'missing_key': {analyzed: path_body(ref)} if len(part['paths']) > 1 else {},
              'inner_identity': {**valid['paths'],
                                 analyzed: {**path_body(ref), 'path': analyzed}}}[shape]
    expected = ('Invalid assigned output record' if shape == 'inner_identity'
                else 'Assigned output identities changed')
    run_with(execution, monkeypatch, {**valid, 'paths': bodies}, validate_against=False)
    with pytest.raises(ContractError, match=expected):
        execution.execute(task)
    with service.store.transaction() as tx:
        assert tx.scan('research_paths') == []
        assert tx.get('research_partitions', part['partition_id']) == part
    assert service.coverage(record['id'])['reviewed_paths'] == 0


def test_the_checkpoint_duplicate_guard_is_still_authoritative(
        audit, monkeypatch):  # noqa: F811  the parameter is pytest's injection of the imported fixture
    """The application guard that refused the canary is unchanged and still independent."""
    from dataclasses import replace

    from codex_harness.domain.research import PartitionCheckpoint

    service, record, _, _, _ = audit
    activate_fixture(service)
    part, task, _ = partition_task(service, record, 'assigned-duplicate-guard')
    ref = service.artifacts.put('one traced path', 'fixture')['ref']
    repeated = [PathDisposition(**{**path_body(ref), 'path': part['paths'][0]}),
                PathDisposition(**{**path_body(ref, 'unreviewed'), 'path': part['paths'][0]})]
    with pytest.raises(ContractError, match='Duplicate coverage'):
        service.checkpoint(task, replace(PartitionCheckpoint(**part), cursor='next'), repeated, [])
    with service.store.transaction() as tx:
        assert tx.get('research_partitions', part['partition_id']) == part
