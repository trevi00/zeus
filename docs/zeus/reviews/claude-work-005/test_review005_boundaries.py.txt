from copy import deepcopy

import pytest
from test_completion_authority import SCENARIOS, Case

from codex_harness.adapters.output_schema import preflight
from codex_harness.adapters.store import MemoryStore
from codex_harness.domain.model import ContractError


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
@pytest.mark.parametrize('field,value', [('approved_by', 'human:forged'), ('revision', 'b' * 40), ('reason', 'different approval')])
def test_exclusion_provenance_cannot_be_rewritten(backend, field, value, request, tmp_path):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    case = Case(store, tmp_path)
    case.finish()
    produced = {'expected': SCENARIOS, 'passed': ['login'], 'excluded': [
        {'id': 'checkout', 'approved_by': 'human:owner', 'revision': 'd' * 40, 'reason': 'reviewed exclusion'}]}
    evaluation = case.evaluation(evaluated=case.evaluated(case.task, scenarios=produced))
    altered = deepcopy(produced)
    altered['excluded'][0][field] = value
    case.record(case.verdict(evaluation=evaluation, scenarios=altered))
    assert case.inspect(expected_scenarios=SCENARIOS)['state'] == 'verdict_mismatch'


@pytest.mark.parametrize('name', ['description', 'default', 'examples'])
def test_schema_names_are_not_annotation_locations(name):
    schema = {'type': 'object', '$defs': {name: {'type': 'integer'}},
              'properties': {'value': {'$ref': '#/$defs/' + name}}}
    assert preflight(schema)['dialect'].endswith('2020-12/schema')


def test_active_reference_into_annotation_still_refused():
    schema = {'type': 'object', 'examples': [{'type': 'integer'}],
              'properties': {'value': {'$ref': '#/examples/0'}}}
    with pytest.raises(ContractError):
        preflight(schema)


@pytest.mark.parametrize('produced', [
    {'expected': [{'id': 'login'}], 'passed': [], 'excluded': []},
    {'expected': SCENARIOS, 'passed': SCENARIOS, 'excluded': ['untyped exclusion']},
])
def test_malformed_reviewer_results_are_named_refusals(produced, tmp_path):
    case = Case(MemoryStore(), tmp_path)
    case.finish()
    evaluation = case.evaluation(evaluated=case.evaluated(case.task, scenarios=produced))
    case.record(case.verdict(evaluation=evaluation))
    assert case.inspect()['state'] == 'verdict_mismatch'
