"""Ported SOURCE M7 suite `tests/test_model_routing.py` run against the target (REBUILD-DESIGN-v2 §5.3 S2).

Import paths rewritten to the target modules; any other adaptation is named in place.

Not ported here (owning slice; carried forward, listed in the S2 coverage evidence):
- test_executor_sends_selection_and_seals_it_in_execution_receipt: S4 execution: needs RunTask (the M7 Executor)
- test_assignment_preserves_trusted_importance_into_implementation: S4 execution: needs RunTask (the M7 Executor)
- test_plan_passes_trusted_action_and_keeps_review_default: S4 execution: needs RunTask (the M7 Executor)
- test_rejection_preserves_simple_implementation_classification: S4 execution: needs RunTask (the M7 Executor)
- test_required_hook_plan_is_explicitly_important: S8 research: recurrence/hook lifecycle over the Harness
- test_lead_review_projects_only_importance_and_conductor_rework_preserves_it: S4 execution: needs RunTask (the M7 Executor)
"""

import pytest

from codex_harness.kernel.errors import ContractError
from codex_harness.routing.domain.model_selection import select_model


@pytest.mark.parametrize(('workload', 'importance', 'model'), [
    ('design', None, 'gpt-6-astra'),
    ('final_validation', None, 'gpt-6-astra'),
    ('implementation', 'simple', 'gpt-6-astra'),
    ('implementation', 'important', 'gpt-6-astra'),
    ('implementation', None, 'gpt-6-astra'),
    ('implementation', 'unknown', 'gpt-6-astra'),
])
def test_conservative_domain_routing(workload, importance, model):
    selection = select_model(workload, importance)
    assert selection.requested_model == model
    assert selection.importance == ('unknown' if workload == 'implementation' and importance is None
                                    else importance or 'not_applicable')


@pytest.mark.parametrize('importance', ['routine', [], 7])
def test_unknown_importance_never_falls_through_to_simple(importance):
    with pytest.raises(ContractError, match='Unknown implementation importance'):
        select_model('implementation', importance)












