"""S9 X1b-2: `development.role_dispatch_decided` produced by RunTask at the admission boundary (DESIGN-s9-X §1.5 R1).

One event per leased run: `dispatched`/`eligible` after the breaker admits, `refused`/`provider_unavailable` when the
breaker refuses and `refused`/`no_capacity` when the reservation is refused. A refusal is observed and the SAME
exception object is re-raised, so the type, the message and the control flow are what they were before X1b-2. The
event goes through the spool (never the audit table). Every case stubs both transports (test_s4_run_task's build).
"""
import pytest
from test_s4_run_task import build, submit, task_row
from test_s9_x2a_metrics import PROVIDERS

from codex_harness.execution.application.invocation_ledger import InvocationLedger
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.adapters.observation_schema import validate_observation
from codex_harness.observation.domain import event_catalog
from codex_harness.observation.domain.event_catalog import check_catalog_attributes
from codex_harness.observation.domain.feature_registry import FEATURES
from codex_harness.observation.domain.metric_families import (
    DISPATCH_DECISIONS,
    DISPATCH_REASONS,
    FAMILIES,
    ROLE_DISPATCH,
    samples,
)

EVENT = "development.role_dispatch_decided"
AGENT = "lead:improvement"


def decided(run_task):
    return [r for r in run_task.observer.spool.records() if r["event_type"] == EVENT]


def audit_types(store):
    with store.transaction() as tx:
        return {a["event_type"] for a in tx.scan("observation_audit")}


def test_a_normal_execution_emits_one_dispatched_eligible_event_and_no_audit_row(tmp_path):
    run_task, workflow, store, _, calls = build(tmp_path)
    submit(workflow)
    assert run_task.execute_one(AGENT)["status"] == "succeeded" and len(calls) == 1
    [event] = decided(run_task)
    attributes = event["attributes"]
    assert event["outcome"] == "succeeded"
    assert attributes["role"] == AGENT and attributes["provider"] == event["execution"]["provider"]
    assert attributes["provider"] == "codex-app-server"
    assert (attributes["decision"], attributes["decision_reason"]) == ("dispatched", "eligible")
    assert type(attributes["latency_seconds"]) is float and attributes["latency_seconds"] >= 0
    assert audit_types(store) == {"development.invocation_reserved", "development.invocation_settled"}
    assert (event["event_type"], event["execution"]["role"]) == (EVENT, AGENT)


def test_a_refusing_breaker_emits_one_refused_event_and_the_same_contract_error(tmp_path, monkeypatch):
    run_task, workflow, store, _, calls = build(tmp_path)
    refusals = []
    real = run_task.admission.breaker.admit

    def refusing(key, lease, now=None):
        monkeypatch.setattr("codex_harness.coordination.application.breaker.decide",
                            lambda state, now, policy: ("refuse", "open"))
        try:
            return real(key, lease, now)
        except ContractError as exc:
            refusals.append(exc)
            raise

    monkeypatch.setattr(run_task.admission.breaker, "admit", refusing)
    submit(workflow)
    assert run_task.execute_one(AGENT)["status"] == "retry"  # the disposition measured at c5280646
    assert task_row(store)["error"].startswith("ContractError: Breaker refuses admission for breaker:")
    [refused] = refusals  # the one exception the breaker raised, whatever the disposition made of it
    assert type(refused) is ContractError and str(refused).startswith("Breaker refuses admission for breaker:")
    [event] = decided(run_task)
    assert event["outcome"] == "blocked"
    assert (event["attributes"]["decision"], event["attributes"]["decision_reason"]) == ("refused", "provider_unavailable")
    assert event["attributes"]["role"] == AGENT and not calls  # the provider was never called
    assert "development.provider_started" not in {r["event_type"] for r in run_task.observer.spool.records()}


def test_a_capacity_refusal_at_reserve_emits_refused_no_capacity_and_the_same_error(tmp_path):
    run_task, workflow, store, _, calls = build(tmp_path)
    ledger = InvocationLedger(store)
    ledger.capacity = 0  # the guard in the constructor is bypassed on purpose: every reservation is refused
    raised = []
    real = ledger.reserve

    def reserve(*args, **kwargs):
        try:
            return real(*args, **kwargs)
        except ContractError as exc:
            raised.append(exc)
            raise

    ledger.reserve = reserve
    run_task.invocations = ledger
    submit(workflow)
    assert run_task.execute_one(AGENT)["status"] == "retry"  # the disposition measured at c5280646
    assert task_row(store)["error"] == "ContractError: Invocation capacity is reserved by other executions"
    [refused] = raised
    assert type(refused) is ContractError and str(refused) == "Invocation capacity is reserved by other executions"
    [event] = decided(run_task)
    assert event["outcome"] == "blocked" and not calls
    assert (event["attributes"]["decision"], event["attributes"]["decision_reason"]) == ("refused", "no_capacity")
    assert event["execution"].get("invocation_id") is None


def test_the_event_passes_the_registry_and_the_catalog_checks(tmp_path):
    run_task, workflow, store, _, calls = build(tmp_path)
    submit(workflow)
    run_task.execute_one(AGENT)
    [event] = decided(run_task)
    validate_observation(event)
    assert check_catalog_attributes(EVENT, event["attributes"]) == event["attributes"]
    catalog = event_catalog.load_catalog()["events"][EVENT]
    assert catalog["owner_context"] == "execution"


def row_for(decision, reason):
    return {"category": "development", "event_type": EVENT, "execution": {"provider": "codex-app-server"},
            "attributes": {"role": AGENT, "provider": "codex-app-server", "decision": decision,
                           "decision_reason": reason, "latency_seconds": 0.0}}


def test_the_counter_enums_are_exactly_the_catalogs():
    declared = event_catalog.load_catalog()["events"][EVENT]["attributes"]
    assert DISPATCH_DECISIONS == tuple(declared["decision"]["enum"])
    assert DISPATCH_REASONS == tuple(declared["decision_reason"]["enum"])
    family = FAMILIES[ROLE_DISPATCH]
    assert (family.name, family.type, family.labels) == ("zeus_role_dispatch_decisions_total", "counter",
                                                         ("decision", "decision_reason"))


@pytest.mark.parametrize("decision, reason", [("dispatched", "eligible"), ("refused", "provider_unavailable"),
                                              ("refused", "no_capacity"), ("other", "other")])
def test_samples_count_one_per_event(decision, reason):
    out, refused = samples(row_for(decision, reason), providers=PROVIDERS)
    assert (ROLE_DISPATCH, (decision, reason), 1) in out and ROLE_DISPATCH not in refused


@pytest.mark.parametrize("decision, reason", [("bogus", "eligible"), ("dispatched", "bogus"), (None, "eligible"),
                                              ("refused", ["no_capacity"])])
def test_an_out_of_enum_value_refuses_the_family_and_adds_no_sample(decision, reason):
    out, refused = samples(row_for(decision, reason), providers=PROVIDERS)
    assert refused == [ROLE_DISPATCH] and all(item[0] != ROLE_DISPATCH for item in out)


def test_the_counter_series_through_the_projection(tmp_path):
    from test_s9_x2a_metrics import file_observer, projecting, series, snapshot

    from codex_harness.observation.adapters.observation_spool import SpoolDirectory
    from codex_harness.observation.application.observations import Collector
    from codex_harness.storage.adapters.memory_store import MemoryStore

    base = MemoryStore()
    _, store = projecting(base)
    observer = file_observer(tmp_path / "obs", base)
    for decision, reason in (("dispatched", "eligible"), ("dispatched", "eligible"), ("refused", "no_capacity")):
        assert observer.emit(EVENT, "succeeded", attributes=row_for(decision, reason)["attributes"]) is not None
    Collector(store, SpoolDirectory(tmp_path / "obs"), validate=validate_observation, observer=observer).collect()
    rows = snapshot(base)
    assert series(rows, "zeus_role_dispatch_decisions_total") == {("dispatched", "eligible"): 2,
                                                                  ("refused", "no_capacity"): 1}


def test_role_dispatch_is_instrumented_with_no_seam():
    feature = FEATURES["role_dispatch"]
    assert feature.instrumented is True and feature.seam is None and feature.proof_events == (EVENT,)


@pytest.mark.parametrize("site", ["reserve", "admit"])
def test_any_other_refusal_is_reported_as_other_with_the_same_error(tmp_path, monkeypatch, site):
    """Owner correction (int21): only the two fixed refusal texts name a reason; every other ContractError is `other`."""
    run_task, workflow, store, _, calls = build(tmp_path)
    message = "Reservation budget must be positive" if site == "reserve" else "Admission requires a typed execution lease"

    def refusing(*args, **kwargs):
        raise ContractError(message)

    if site == "reserve":
        monkeypatch.setattr(run_task.invocations, "reserve", refusing)
    else:
        monkeypatch.setattr(run_task.admission.breaker, "admit", refusing)
    submit(workflow)
    run_task.execute_one(AGENT)
    assert task_row(store)["error"] == "ContractError: " + message and not calls
    [event] = decided(run_task)
    assert (event["attributes"]["decision"], event["attributes"]["decision_reason"]) == ("refused", "other")
