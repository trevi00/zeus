"""S10 #18b: `composition.invocation_budget.CapacityObservingLedger` (OWNER-DECISIONS-S10 #18(b)).

`operations.capacity_refused` is emitted on exactly the invocation-capacity refusal and the SAME exception object is
re-raised; any other refusal and every success emit nothing; the other ledger methods forward unchanged.
"""
import pytest
from test_s4_run_task import build

from codex_harness.composition.invocation_budget import CapacityObservingLedger
from codex_harness.execution.application.invocation_ledger import InvocationLedger
from codex_harness.execution.domain.invocation import parse_request
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.adapters.observation_schema import validate_observation
from codex_harness.observation.application.catalog_observer import CatalogCheckingObserver
from codex_harness.observation.domain.event_catalog import check_catalog_attributes
from codex_harness.storage.adapters.memory_store import MemoryStore

EVENT = "operations.capacity_refused"
ATTRIBUTES = {"scope": "invocation_budget", "refusal_reason": "budget_exhausted", "retry_after_seconds": None}
MESSAGE = "Invocation capacity is reserved by other executions"
REQUEST = parse_request("app_server", {"model": "gpt-5-codex", "timeout": 30})
USAGE = {"source": "unknown", "total_tokens": None, "last_tokens": None}


def running_lease(store, task_id, owner):
    """A running task row with a live lease: the only state in which its open reservation keeps counting."""
    lease = {"id": task_id, "generation": 1, "attempt": 1, "lease_owner": owner}
    with store.transaction() as tx:
        tx.put("tasks", task_id, {**lease, "status": "running", "lease_until": "2999-01-01T00:00:00+00:00"})
    return lease


def undated(summary):
    return {k: v for k, v in summary.items() if k != "as_of"}  # the wall clock is the only difference


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event_type, outcome, **fields):
        self.events.append((event_type, outcome, fields.get("attributes")))


def held(ledger_of):
    """A store with one open reservation (capacity 1) and a second running lease waiting behind it."""
    store = MemoryStore()
    lease, other = running_lease(store, "t1", "owner-1"), running_lease(store, "t2", "owner-2")
    ledger = ledger_of(store)
    row = ledger.reserve(lease, request=REQUEST, budget_seconds=30)
    return store, ledger, row, lease, other


def decorated(observer):
    return lambda store: CapacityObservingLedger(InvocationLedger(store, capacity=1), observer)


def test_the_capacity_refusal_emits_one_event_and_raises_the_same_error():
    recorder = Recorder()
    _, ledger, _, _, other = held(decorated(recorder))
    assert recorder.events == []  # the successful first reserve emitted nothing
    _, plain, _, _, plain_other = held(lambda store: InvocationLedger(store, capacity=1))
    with pytest.raises(ContractError) as plain_raised:
        plain.reserve(plain_other, request=REQUEST, budget_seconds=30)
    with pytest.raises(ContractError) as raised:
        ledger.reserve(other, request=REQUEST, budget_seconds=30)
    assert type(raised.value) is type(plain_raised.value) and str(raised.value) == str(plain_raised.value) == MESSAGE
    assert recorder.events == [(EVENT, "blocked", ATTRIBUTES)]


def test_the_event_passes_the_registry_and_the_catalog_checks(tmp_path):
    observer = build(tmp_path)[0].observer
    _, ledger, _, _, other = held(decorated(observer))
    with pytest.raises(ContractError):
        ledger.reserve(other, request=REQUEST, budget_seconds=30)
    [event] = [r for r in observer.spool.records() if r["event_type"] == EVENT]
    validate_observation(event)
    assert check_catalog_attributes(EVENT, event["attributes"]) == event["attributes"] == ATTRIBUTES
    assert event["outcome"] == "blocked"


def test_another_contract_error_is_re_raised_with_no_event():
    recorder = Recorder()
    ledger = decorated(recorder)(MemoryStore())
    with pytest.raises(ContractError) as raised:
        ledger.reserve({"id": "x"}, request=REQUEST, budget_seconds=30)
    with pytest.raises(ContractError) as plain_raised:
        InvocationLedger(MemoryStore(), capacity=1).reserve({"id": "x"}, request=REQUEST, budget_seconds=30)
    assert str(raised.value) == str(plain_raised.value) == "Reservation requires a typed execution lease"
    assert recorder.events == []


def test_the_other_methods_forward_and_equal_the_undecorated_ledger():
    results = []
    for ledger_of in (decorated(Recorder()), lambda store: InvocationLedger(store, capacity=1)):
        _, ledger, row, lease, _ = held(ledger_of)
        outcome = {"reclaim": ledger.reclaim(), "summary_open": undated(ledger.summary())}
        settled = ledger.settle(row["id"], outcome="accepted", usage=USAGE)
        outcome["settled"] = {k: v for k, v in settled.items() if not k.endswith("_at") and k != "elapsed_seconds"}
        outcome["summary_settled"] = undated(ledger.summary())
        outcome["abandoned_unknown"] = ledger.abandon(row["id"], "late")["status"]
        outcome["capacity"] = ledger.capacity
        results.append(outcome)
    assert results[0] == results[1] and results[0]["capacity"] == 1
    with pytest.raises(ContractError, match="Unknown invocation reservation"):
        decorated(Recorder())(MemoryStore()).abandon("missing", "why")


def test_the_event_reaches_the_spool_through_the_catalog_checking_observer(tmp_path):
    observer = CatalogCheckingObserver(build(tmp_path)[0].observer)
    _, ledger, _, _, other = held(decorated(observer))
    with pytest.raises(ContractError):
        ledger.reserve(other, request=REQUEST, budget_seconds=30)
    [event] = [r for r in observer.spool.records() if r["event_type"] == EVENT]
    assert event["attributes"] == ATTRIBUTES and observer.counters["refused"] == 0
