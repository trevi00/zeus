import copy
import json
from dataclasses import asdict

import pytest
from jsonschema import ValidationError, validate

from codex_harness.adapters.app_server import AppServer
from codex_harness.adapters.audit_execution import AuditExecution
from codex_harness.adapters.output_schema import CAUSE, preflight
from codex_harness.domain.model import ContractError
from codex_harness.domain.research import PATH_DISPOSITIONS, SourceIdentity, parse_record


@pytest.mark.parametrize('kind', ['AdaptationProposal', 'IndependentReview'])
def test_complete_generated_schema_preserves_types_and_constraints(kind):
    schema = AuditExecution.typed_schema(kind)
    preflight(schema)
    assert schema['properties']['version'] == {'type': 'integer', 'const': 1}
    for definition in schema['$defs'].values():
        if 'version' in definition.get('properties', {}):
            assert definition['properties']['version'] == {'type': 'integer', 'const': 1}
    assert schema['additionalProperties'] is False
    assert set(schema['required']) == set(schema['properties'])
    broken = copy.deepcopy(schema)
    del broken['properties']['version']['type']
    with pytest.raises(ContractError, match=CAUSE):
        preflight(broken)
    nested = copy.deepcopy(schema)
    del nested['$defs']['SourceIdentity']['properties']['version']['type']
    with pytest.raises(ContractError, match=r'\$defs.*SourceIdentity.*version'):
        preflight(nested)


def test_existing_record_parsing_and_invalid_versions():
    record = asdict(SourceIdentity('https://github.com/a/b', 'a' * 40, 'b' * 40, 'sha256:' + 'c' * 64))
    document = {'version': 1, 'kind': 'SourceIdentity', 'record': record}
    assert asdict(parse_record(document)) == record
    schema = AuditExecution.typed_schema('SourceIdentity')
    validate(record, schema)
    for value in [0, 2, True, '1', None, 1.5]:
        with pytest.raises(ValidationError):
            validate({**record, 'version': value}, schema)
        with pytest.raises(ContractError):
            parse_record({**document, 'record': {**record, 'version': value}})


@pytest.mark.parametrize('schema', [
    {'properties': {'version': {'anyOf': [{'const': 1}, {'type': 'null'}]}}},
    {'$defs': {'nested': {'items': {'properties': {'version': {'const': 1}}}}}},
    {'properties': {'version': {'$ref': '#/$defs/v'}}, '$defs': {'v': {'const': 1}}},
])
def test_schema_nodes_and_version_reference_are_checked(schema):
    with pytest.raises(ContractError, match="missing-type"):
        preflight(schema)


@pytest.mark.parametrize('schema', [None, [], {'type': 'bogus'}, {'properties': []},
                                    {'anyOf': {}}, {'properties': {'version': None}}])
def test_malformed_schema_rejected_before_send(monkeypatch, schema):
    server = AppServer(executable='fixture')
    sent = []
    monkeypatch.setattr(server, 'send', sent.append)
    with pytest.raises(ContractError):
        server.request('turn/start', {'outputSchema': schema})
    assert sent == [] and server.sequence == 0


def test_valid_references_unions_and_annotations_forwarded_unchanged(monkeypatch):
    schema = {'type': 'object', 'additionalProperties': False, 'properties': {'version': {'$ref': '#/$defs/v'}},
              '$defs': {'v': {'anyOf': [{'type': 'integer', 'const': 1}, {'type': 'null'}]}},
              'examples': [{'properties': {'version': {'const': 1}}}],
              'description': 'properties.version missing type'}
    before = copy.deepcopy(schema)
    server = AppServer(executable='fixture')
    sent = []
    monkeypatch.setattr(server, 'send', sent.append)
    server.incoming.put({'id': 1, 'result': {'turn': {'id': 'fixture'}}})
    server.request('turn/start', {'outputSchema': schema, 'input': [
        {'type': 'text', 'text': json.dumps({'properties': {'version': {'const': 1}}})}]})
    assert schema == before
    assert sent[0]['params']['outputSchema'] is schema


@pytest.mark.parametrize('kind', ['AdaptationProposal', 'IndependentReview'])
def test_defective_turn_never_transmitted(monkeypatch, kind):
    server = AppServer(executable='fixture')
    schema = AuditExecution.typed_schema(kind)
    del schema['properties']['version']['type']
    sent = []
    monkeypatch.setattr(server, 'send', sent.append)
    with pytest.raises(ContractError, match=CAUSE):
        server.request('turn/start', {'outputSchema': schema})
    assert sent == []



def test_baseline_reconstruction_and_semantic_preservation():
    import subprocess
    from importlib.resources import files

    current = json.loads(files('codex_harness.resources').joinpath('research.schema.json').read_text())
    # The single accepted delta since the baseline: PathDisposition.disposition was an
    # unconstrained string that let `partial` through (2026-09-20 canary). Nothing else may
    # differ, so only this exact enum is removed before the historical comparison below.
    assert current['$defs']['PathDisposition']['properties']['disposition'] == {
        'type': 'string', 'enum': list(PATH_DISPOSITIONS)}
    old = json.loads(subprocess.check_output([
        'git', 'show', '09c1d58298b22337125f29842382d2aef960c7d2:'
        'src/codex_harness/resources/research.schema.json']))
    assert sum('version' in d['properties'] for d in old['$defs'].values()) == 5
    for kind, definition in old['$defs'].items():
        if 'version' in definition['properties']:
            with pytest.raises(ContractError, match=CAUSE):
                preflight({**definition, '$defs': old['$defs']})
    def strip_added_types(node):
        if isinstance(node, dict):
            return {k: strip_added_types(v) for k, v in node.items()
                    if not (k == 'type' and 'const' in node)}
        if isinstance(node, list):
            return [strip_added_types(v) for v in node]
        return node
    reconstructed = copy.deepcopy(current)
    del reconstructed['$defs']['PathDisposition']['properties']['disposition']['enum']
    assert strip_added_types(reconstructed) == old
    preflight(current)


def research_outputs():
    definitions = AuditExecution.typed_schema('AdaptationProposal')['$defs']
    return [AuditExecution.typed_schema(k) for k in definitions] + [AuditExecution.partition_schema()]


@pytest.mark.parametrize('output_schema', research_outputs())
def test_provider_open_object_reproduction_and_projection(output_schema):
    from importlib.resources import files

    definitions = json.loads(files('codex_harness.resources').joinpath('research.schema.json').read_text())['$defs']
    historical = definitions['SubsystemAnalysis']['properties']['tests_not_run']['items']
    generated = output_schema['$defs']['SubsystemAnalysis']['properties']['tests_not_run']['items']
    # Actual provider failure: tests_not_run.items requires additionalProperties:false.
    assert historical == {'type': 'object'}
    entry = {'test': 'pytest', 'reason': 'service unavailable', 'follow_up': 'retry with service'}
    validate(entry, generated)
    validate({**entry, 'legacy_metadata': 'preserved'}, historical)
    for invalid in ({}, {**entry, 'extra': True}, {**entry, 'reason': None}):
        with pytest.raises(ValidationError):
            validate(invalid, generated)

    def closed(node):
        if isinstance(node, dict):
            if node.get('type') == 'object':
                assert node.get('additionalProperties') is False
                assert set(node.get('required', [])) == set(node.get('properties', {}))
            for value in node.values():
                closed(value)
        elif isinstance(node, list):
            for value in node:
                closed(value)
    closed(output_schema)


@pytest.mark.parametrize('output_schema', research_outputs())
def test_all_outputs_reach_both_transport_boundaries(monkeypatch, output_schema, tmp_path):
    from pathlib import Path
    from types import SimpleNamespace

    import codex_harness.adapters.codex as cli
    from codex_harness.adapters.codex import CodexRuntime

    server = AppServer(executable='fixture')
    sent = []
    monkeypatch.setattr(server, 'send', sent.append)
    server.incoming.put({'id': 1, 'result': {}})
    server.request('turn/start', {'outputSchema': output_schema})
    assert sent[0]['params']['outputSchema'] == output_schema
    def run(argv, **kwargs):
        actual = json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text())
        assert actual == output_schema
        assert 'invalid_json_schema' in kwargs['input_text']
        return SimpleNamespace(returncode=1, stderr='fixture transport reached')
    monkeypatch.setattr(cli, 'run_process', run)
    with pytest.raises(ContractError, match='fixture transport reached'):
        CodexRuntime('fixture').run('invalid_json_schema properties.version', str(tmp_path), output_schema)


@pytest.mark.parametrize('bad', [None, {'properties': {'version': {'const': 1}}},
                                  {'$defs': {'kind': {'const': 'AdaptationProposal'}}}])
def test_cli_preflight_blocks_before_process(monkeypatch, bad, tmp_path):
    import codex_harness.adapters.codex as cli

    calls = []
    monkeypatch.setattr(cli, 'run_process', lambda *a, **kw: calls.append(a))
    with pytest.raises(ContractError, match='sha256:'):
        cli.CodexRuntime('fixture').run('prompt', str(tmp_path), bad)
    assert not calls


def test_preflight_hash_is_bound_to_original_schema():
    import hashlib

    bad = {'properties': {'version': {'const': 1}}}
    expected = hashlib.sha256(json.dumps(bad, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with pytest.raises(ContractError, match=expected):
        preflight(bad)
    assert bad == {'properties': {'version': {'const': 1}}}
