from datetime import datetime, timedelta, timezone

import pytest
from test_executor_research import setup as setup
from test_workflow import assignment

from codex_harness.application.breaker import DEFAULT_POLICY, Breaker, breaker_key
from codex_harness.application.invocation_ledger import InvocationLedger
from codex_harness.domain.model import ContractError

SCHEMA = {'type': 'object', 'properties': {'accepted': {'type': 'boolean'}}}
KEY = breaker_key('codex-app-server', 'final_validation')


def open_breaker(executor, lease, age):
    executor.breaker = Breaker(executor.service.store, {**DEFAULT_POLICY, 'failure_threshold': 1})
    before = datetime.now(timezone.utc) - timedelta(seconds=age)
    token = executor.breaker.admit(KEY, lease, now=before)
    executor.breaker.report(token, 'failure', now=before)


def test_capacity_refusal_does_not_take_a_half_open_probe(setup):
    executor = setup.executor
    lease = executor.workflow.claim('worker:github', 'integration-owner')
    executor.workflow.submit(assignment())
    other = executor.workflow.claim('worker:implementation', 'other-owner')
    executor.invocations = InvocationLedger(setup.service.store, capacity=1)
    executor.invocations.reserve(other, request={}, budget_seconds=60)
    open_breaker(executor, lease, age=150)
    with pytest.raises(ContractError, match='Invocation capacity'):
        executor._run('worker:github', lease['id'], 'Integration capacity check', {},
                      str(executor.git.repository), SCHEMA, lease=lease)
    state = executor.breaker.inspect(KEY)
    assert state['state'] == 'open' and state['reservation'] is None
    assert executor.invocations.summary()['by_status']['reserved'] == 1


def test_breaker_refusal_releases_the_invocation_reservation(setup):
    executor = setup.executor
    lease = executor.workflow.claim('worker:github', 'integration-owner')
    open_breaker(executor, lease, age=0)
    with pytest.raises(ContractError, match='Breaker refuses admission'):
        executor._run('worker:github', lease['id'], 'Integration breaker check', {},
                      str(executor.git.repository), SCHEMA, lease=lease)
    counts = executor.invocations.summary()['by_status']
    assert counts['reserved'] == 0 and counts['unsettled_unknown'] == 1
    assert executor.breaker.inspect(KEY)['state'] == 'open'
