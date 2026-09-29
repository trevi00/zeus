"""Ported from SOURCE M7 `tests/test_invocation_ledger.py` (the pure request-matrix and probe tests).

Unchanged test bodies; imports point at the target (`execution.domain.invocation`, `kernel.errors`).
The ledger/executor tests of that file need the M7 workflow and executor (S4 RunTask / S5) and are
compared differentially instead (`compare:execution.ledger`, `compare:execution.run_task`).
"""

import pytest

from codex_harness.execution.domain.invocation import availability, parse_request
from codex_harness.kernel.errors import ContractError

SCHEMA = {'type': 'object', 'properties': {'accepted': {'type': 'boolean'}}, 'required': ['accepted']}


def test_request_matrix_refuses_unknown_and_unsupported_options_before_execution():
    accepted = parse_request('app_server', {'model': 'gpt-5-codex', 'timeout': 30, 'output_schema': SCHEMA,
                                            'read_only': False})
    assert accepted['options'] == {'model': 'gpt-5-codex', 'timeout': 30, 'output_schema': SCHEMA, 'read_only': False}
    assert set(accepted['unsupported']) == {'system', 'temperature', 'max_output_tokens', 'response_format'}
    with pytest.raises(ContractError, match='Options not supported by app_server \\(not ignored\\): max_output_tokens, temperature'):
        parse_request('app_server', {'model': 'x', 'temperature': 0.2, 'max_output_tokens': 10})
    with pytest.raises(ContractError, match='Unknown invocation options: top_p'):
        parse_request('app_server', {'model': 'x', 'top_p': 1})
    for bad in ({'model': ''}, {'model': 7}, {'timeout': 0}, {'timeout': float('nan')}, {'timeout': '30'},
                {'output_schema': {}}, {'output_schema': 'schema'}, {'read_only': 'no'}):
        with pytest.raises(ContractError):
            parse_request('app_server', bad)
    with pytest.raises(ContractError, match='Unknown invocation transport'):
        parse_request('anthropic_sdk', {'model': 'x'})
    # Explicitly null unsupported options are not "set"; they are still not applied.
    assert 'system' not in parse_request('app_server', {'system': None})['options']


def test_probe_is_never_model_readiness_or_qualification():
    assert availability({'executable': '/bin/codex', 'passed': True, 'version': '0.1.0'})['state'] == 'version_confirmed'
    assert availability({'executable': '/bin/codex', 'passed': False, 'version': ''})['state'] == 'executable_found'
    assert availability({})['state'] == availability(None)['state'] == 'executable_missing'
    for probe in ({'executable': '/bin/codex', 'passed': True, 'version': '0.1.0'}, {}):
        report = availability(probe)
        assert report['model_ready'] == 'unknown' and report['qualified'] is False
