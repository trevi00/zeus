"""FA-023: structural validation names its subset and its checks; ownership and observation are separate
(INV-OUTPUT-001).

The upstream validator reported "ok" when no check ran, accepted unknown keywords silently,
folded configuration-owner errors into agent failures and let a self-reported tool list stand
for observed tool use.
"""
import copy
import json

import pytest
from test_executor_research import setup as setup  # noqa: F401

from codex_harness.adapters.audit_execution import AuditExecution
from codex_harness.adapters.execution_output import completed_output, tool_usage
from codex_harness.adapters.executor import (
    DIAGNOSIS,
    IMPLEMENTATION,
    PLAN,
    RESEARCH,
    SHORTLIST,
    VERDICT,
)
from codex_harness.adapters.output_schema import (
    CHECKS,
    DIALECT,
    MAX_DEPTH,
    SUPPORTED_KEYWORDS,
    preflight,
)
from codex_harness.domain.model import ContractError

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['summary'],
          'properties': {'summary': {'type': 'string'}}}


def test_every_schema_zeus_sends_is_inside_the_subset_and_gets_a_receipt():
    for schema in (VERDICT, PLAN, IMPLEMENTATION, RESEARCH, SHORTLIST, DIAGNOSIS,
                   AuditExecution.typed_schema('AdaptationProposal'), AuditExecution.typed_schema('IndependentReview')):
        receipt = preflight(schema)
        assert receipt['dialect'] == DIALECT and receipt['subset_version'] == 1 and receipt['checks'] == list(CHECKS)
        assert set(receipt['keywords']) <= SUPPORTED_KEYWORDS and receipt['schema_hash'].startswith('sha256:')
        assert 0 < receipt['max_depth'] <= MAX_DEPTH and receipt['bytes'] > 0


def test_unknown_keywords_are_configuration_errors_not_silent_no_ops():
    typo = {**SCHEMA, 'requried': ['summary']}  # a misspelled keyword used to mean "no check"
    with pytest.raises(ContractError, match='unsupported-keyword.*requried'):
        preflight(typo)
    nested = copy.deepcopy(SCHEMA)
    nested['properties']['summary']['minLenght'] = 3
    with pytest.raises(ContractError, match=r'unsupported-keyword.*\["properties"\]\["summary"\].*minLenght'):
        preflight(nested)
    with pytest.raises(ContractError, match='enum-missing-type'):
        preflight({'type': 'object', 'properties': {'level': {'enum': [1, 2]}}})
    with pytest.raises(ContractError, match='required-undeclared.*extra'):
        preflight({'type': 'object', 'additionalProperties': False, 'properties': {'a': {'type': 'string'}},
                   'required': ['a', 'extra']})
    deep = {'type': 'object'}
    for _ in range(MAX_DEPTH + 1):
        deep = {'type': 'object', 'properties': {'child': deep}}
    with pytest.raises(ContractError, match='too-deep'):
        preflight(deep)
    with pytest.raises(ContractError, match='expected JSON'):
        preflight({'type': 'number', 'minimum': float('nan')})
    # Annotations are not schemas: an example that looks like a defective schema is not walked.
    annotated = {**SCHEMA, 'examples': [{'properties': {'version': {'const': 1}}}], 'description': 'x', 'title': 't'}
    assert 'examples' in preflight(annotated)['keywords']


def test_declared_dialect_is_the_validating_dialect():
    # Review counterexample (PR #55): a draft-07 `$schema` made jsonschema.validate pick draft-07 and
    # ignore prefixItems while the receipt claimed 2020-12.
    schema = {'$schema': 'http://json-schema.org/draft-07/schema#', 'type': 'array', 'prefixItems': [{'type': 'integer'}]}
    result = completed_output('["not-an-integer"]', schema)
    assert result['answer'] is None and result['failure']['owner'] == 'configuration'
    assert result['structural']['checks']['schema'] == 'configuration_error' and 'draft-07' in result['structural']['schema']['configuration_error']
    declared = {**schema, '$schema': 'https://json-schema.org/draft/2020-12/schema'}
    rejected = completed_output('["not-an-integer"]', declared)
    assert rejected['failure']['output_reason'] == 'schema_mismatch' and rejected['structural']['checks']['schema'] == 'failed'
    accepted = completed_output('[3]', declared)
    assert accepted['answer'] == [3] and accepted['structural']['schema']['dialect'] == accepted['structural']['schema']['dialect']
    assert accepted['structural']['schema']['validator'] == 'jsonschema.Draft202012Validator'
    assert accepted['structural']['schema']['format'].startswith('annotation only')
    # `format` is an annotation: a value that violates the named format still passes, and the receipt says so.
    formatted = completed_output('{"when": "not-a-date"}', {'type': 'object', 'properties': {'when': {'type': 'string', 'format': 'date-time'}}})
    assert formatted['answer'] == {'when': 'not-a-date'} and formatted['structural']['checks']['schema'] == 'checked'
    # A transport event with params=None is neither a tool item nor a crash.
    usage = tool_usage({'events': [{'method': 'item/completed', 'params': None}, {'method': 'item/completed'}], 'answer': {}})
    assert usage['runner_observed']['commandExecution']['count'] == 0 and usage['comparison'] == 'not_declared'


def test_output_validation_names_what_it_checked_and_who_owns_a_failure():
    ok = completed_output(json.dumps({'summary': 'done'}), SCHEMA)
    assert ok['answer'] == {'summary': 'done'} and 'failure' not in ok
    assert ok['structural']['checks'] == {'text': 'checked', 'json': 'checked', 'finite': 'checked', 'schema': 'checked'}
    assert ok['structural']['schema']['schema_hash'].startswith('sha256:')
    mismatch = completed_output(json.dumps({'summary': 7}), SCHEMA)
    assert mismatch['failure']['owner'] == 'agent_output' and mismatch['failure']['output_reason'] == 'schema_mismatch'
    assert mismatch['structural']['checks']['schema'] == 'failed'
    broken = completed_output('{', SCHEMA)
    assert broken['structural']['checks'] == {'text': 'checked', 'json': 'failed', 'finite': 'unchecked', 'schema': 'unchecked'}
    assert broken['failure']['owner'] == 'agent_output'
    # The schema itself is wrong: a configuration-owner error, and the valid-looking answer is not accepted.
    misconfigured = completed_output(json.dumps({'summary': 'done'}), {**SCHEMA, 'requried': ['summary']})
    assert misconfigured['answer'] is None and misconfigured['failure']['owner'] == 'configuration'
    assert misconfigured['failure']['cause'] == 'codex-output-schema-configuration'
    assert misconfigured['structural']['checks']['schema'] == 'configuration_error'
    assert 'unsupported-keyword' in misconfigured['structural']['schema']['configuration_error']
    assert misconfigured['structural']['checks']['json'] == 'checked', 'the checks that could run still ran'
    empty = completed_output('   ', SCHEMA)
    assert empty['structural']['checks']['text'] == 'failed' and empty['failure']['output_reason'] == 'empty'
    nan = completed_output('{"summary": NaN}', SCHEMA)
    assert nan['failure']['output_reason'] == 'invalid_json' and nan['structural']['checks']['json'] == 'failed'


def test_observed_tool_use_is_recorded_beside_any_self_report():
    events = [{'method': 'item/completed', 'params': {'item': {'id': 'c1', 'type': 'commandExecution'}}},
              {'method': 'item/completed', 'params': {'item': {'id': 'f1', 'type': 'fileChange'}}},
              {'method': 'item/completed', 'params': {'item': {'id': 'm1', 'type': 'agentMessage'}}},
              {'method': 'item/started', 'params': {'item': {'id': 'c2', 'type': 'commandExecution'}}},
              'not-an-event']
    silent = tool_usage({'events': events, 'answer': {'summary': 'x'}})
    assert silent['runner_observed']['commandExecution'] == {'count': 1, 'ids': ['c1']}
    assert silent['runner_observed']['fileChange']['count'] == 1 and silent['runner_observed']['mcpToolCall']['count'] == 0
    assert silent['self_reported'] is None and silent['comparison'] == 'not_declared'
    honest = tool_usage({'events': events, 'answer': {'summary': 'x', 'tool_calls': ['ran tests', 'edited a file']}})
    assert honest['comparison'] == 'consistent' and honest['self_reported'] == ['ran tests', 'edited a file']
    understated = tool_usage({'events': events, 'answer': {'summary': 'x', 'tool_calls': []}})
    assert understated['comparison'] == 'differs', 'a self-report never certifies the absence of tool use'
    assert tool_usage({'events': [], 'answer': None})['runner_observed']['commandExecution']['count'] == 0
    assert 'certifies nothing' in honest['source']


def test_executor_result_carries_observed_tool_use(setup, monkeypatch):
    from test_app_server import finish, replay
    s = setup
    lease = s.executor.workflow.claim('worker:github', 'tools-owner')
    tool_event = {'method': 'item/completed', 'params': {'threadId': 'thread', 'turnId': 'turn',
                                                         'item': {'id': 'cmd-1', 'type': 'commandExecution', 'status': 'completed'}}}

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, cwd, schema, timeout, **kwargs):
            result, *_ = replay(monkeypatch, [tool_event, *finish()])
            return result

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    schema = {'type': 'object', 'properties': {'accepted': {'type': 'boolean'}}, 'required': ['accepted']}
    answer = s.executor._run('worker:github', lease['id'], 'Tool usage', {}, str(s.executor.git.repository), schema, lease=lease)
    assert answer['accepted'] is True
    with s.service.store.transaction() as tx:
        evidence_ref = tx.get('sessions', 'worker:github')['checkpoint']['evidence_ref']
    evidence = json.loads(s.artifacts.text(evidence_ref, 400000))
    assert evidence['tool_usage']['runner_observed']['commandExecution'] == {'count': 1, 'ids': ['cmd-1']}
    assert evidence['tool_usage']['comparison'] == 'not_declared'

