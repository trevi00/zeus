"""S9 X2b: six event-derived metric families from producers that exist today (DESIGN-s9-X §2.2, §2.3).

Per-family sample rules through `samples`, the Observer -> spool -> Collector -> ProjectingStore -> render path, rows
built as RunTask builds them, and the rejection counter. The X2a tests and golden are untouched.
"""
import json

import pytest
from test_s9_x2a_metrics import PROVIDERS, file_observer, series, snapshot

from codex_harness.delivery.domain.host_delivery import HALTED_STAGES, STAGE_ORDER
from codex_harness.execution.domain.worker_sessions import STATES
from codex_harness.observation.adapters.metrics_exposition import render
from codex_harness.observation.adapters.observation_schema import validate_observation
from codex_harness.observation.adapters.observation_spool import SpoolDirectory
from codex_harness.observation.application.metrics_projector import MetricsProjector, ProjectingStore
from codex_harness.observation.application.observations import Collector
from codex_harness.observation.domain.metric_families import FAMILIES, samples
from codex_harness.observation.domain.observation import INVOCATION_OUTCOMES
from codex_harness.storage.adapters.memory_store import MemoryStore

CANARY = "CANARY-x2b-4f1e8a7c"
PROVIDER = "codex-app-server"
REJECTIONS = "zeus_metrics_label_rejections_total"
NEW = ("zeus_outbox_delivery_attempts_total", "zeus_invocation_settlements_total", "zeus_invocation_abandoned_total",
       "zeus_delivery_stage_entries_total", "zeus_worker_session_transitions_total", "zeus_backlog_transitions_total")


def row(event_type, attributes=None, provider=PROVIDER, category="general"):
    return {"category": category, "event_type": event_type, "attributes": attributes if attributes is not None else {},
            "execution": {"provider": provider}}


def run(r):
    out, refused = samples(r, providers=PROVIDERS)
    return [item for item in out if item[0] in NEW], [name for name in refused if name in NEW]


def test_the_new_families_are_registered_with_counter_type_and_labels():
    assert len(FAMILIES) == 12
    assert {name: FAMILIES[name].labels for name in NEW} == {
        NEW[0]: ("result",), NEW[1]: ("provider", "outcome", "within_budget"), NEW[2]: ("provider",),
        NEW[3]: ("stage",), NEW[4]: ("state",), NEW[5]: ("transition",)}
    assert all(FAMILIES[name].type == "counter" and FAMILIES[name].help.endswith(".") for name in NEW)


@pytest.mark.parametrize("event_type,result", (("general.message_published", "published"),
                                               ("general.message_delivery_retry", "retry"),
                                               ("general.message_delivery_error", "error")))
def test_outbox_attempts(event_type, result):
    assert run(row(event_type)) == ([(NEW[0], (result,), 1)], [])


def test_settlements_samples_and_refusals():
    good = {"invocation_outcome": "empty_answer", "within_budget": False}
    assert run(row("development.invocation_settled", good)) == (
        [(NEW[1], (PROVIDER, "empty_answer", "false"), 1)], [])
    assert run(row("development.invocation_settled", {**good, "within_budget": True}))[0] == [
        (NEW[1], (PROVIDER, "empty_answer", "true"), 1)]
    for outcome in INVOCATION_OUTCOMES:
        assert run(row("development.invocation_settled", {**good, "invocation_outcome": outcome}))[1] == []
    bad = (row("development.invocation_settled", {**good, "invocation_outcome": "bogus"}),
           row("development.invocation_settled", {"within_budget": True}),
           row("development.invocation_settled", {**good, "invocation_outcome": 7}),
           row("development.invocation_settled", {"invocation_outcome": "accepted"}),
           row("development.invocation_settled", {**good, "within_budget": "false"}),
           row("development.invocation_settled", {**good, "within_budget": 0}),
           row("development.invocation_settled", good, provider="unknown-provider"),
           row("development.invocation_settled", good, provider=None))
    for r in bad:
        assert run(r) == ([], [NEW[1]])
    assert run({"event_type": "development.invocation_settled", "attributes": good}) == ([], [NEW[1]])


def test_abandoned_samples_and_refusals_never_use_the_reason():
    attributes = {"reservation_id": "r1", "reason": "exception:" + CANARY}
    assert run(row("development.invocation_abandoned", attributes)) == ([(NEW[2], (PROVIDER,), 1)], [])
    assert run(row("development.invocation_abandoned", attributes, provider="other")) == ([], [NEW[2]])
    assert run(row("development.invocation_abandoned", attributes, provider=5)) == ([], [NEW[2]])


def test_delivery_stages():
    for stage in (*STAGE_ORDER, *sorted(HALTED_STAGES)):
        assert run(row("general.delivery_stage_entered", {"stage": stage})) == ([(NEW[3], (stage,), 1)], [])
    assert "rolled_back" in HALTED_STAGES
    for attributes in ({"stage": "deploying"}, {}, {"stage": None}, {"stage": 3}, {"stage": ["verifying"]},
                       {"previous_stage": "verifying"}):
        assert run(row("general.delivery_stage_entered", attributes)) == ([], [NEW[3]])


def test_worker_session_states():
    for state in STATES:
        assert run(row("development.worker_session_transition", {"state": state})) == ([(NEW[4], (state,), 1)], [])
    for attributes in ({"state": "dormant"}, {}, {"state": None}, {"state": 1}, {"previous_state": "active"}):
        assert run(row("development.worker_session_transition", attributes)) == ([], [NEW[4]])


@pytest.mark.parametrize("event_type,transition", (("development.backlog_item_admitted", "admitted"),
                                                   ("operations.backlog_recovered", "recovered"),
                                                   ("operations.backlog_unavailable", "unavailable"),
                                                   ("operations.backlog_item_refused", "refused")))
def test_backlog_transitions(event_type, transition):
    assert run(row(event_type)) == ([(NEW[5], (transition,), 1)], [])


def collect(tmp_path, emit):
    base = MemoryStore()
    store = ProjectingStore(base, MetricsProjector(providers=PROVIDERS))
    o = file_observer(tmp_path / "obs", base)
    emit(o, base)
    collector = Collector(store, SpoolDirectory(tmp_path / "obs"), validate=validate_observation, observer=o)
    result = collector.collect()
    return base, result


def test_end_to_end_through_the_observer_spool_collector_and_render(tmp_path):
    def emit(o, base):
        with base.transaction() as tx:
            o.audit(tx, "general.message_published", "succeeded", identity=["outbox_attempt", "a1", "published"],
                    attributes={"outbox_id": "o1", "attempt_id": "a1", "attempt_number": 1, "stream_entry_id": "1-0",
                                "message_type": "task", "recipient": "worker"})
            o.audit(tx, "general.message_delivery_retry", "failed", identity=["outbox_attempt", "a2", "retry"],
                    attributes={"outbox_id": "o1", "attempt_id": "a2", "attempt_number": 2, "error_type": "OSError"})
            o.audit(tx, "general.message_delivery_error", "unknown", identity=["outbox_attempt", "a3", "error"],
                    attributes={"outbox_id": "o1", "attempt_id": "a3", "attempt_number": 3, "error_type": "OSError"})
        assert o.emit("general.delivery_stage_entered", "observed",
                      attributes={"plan_id": "p1", "release_id": "r1", "target_id": "t1", "stage": "verifying",
                                  "previous_stage": "awaiting_review"}) is not None
        assert o.emit("development.worker_session_transition", "observed",
                      attributes={"task_id": "t1", "session_id": "s1", "state": STATES[0], "previous_state": None,
                                  "version": 1, "mode": None, "checkpoints": 0, "candidates": 0,
                                  "owner_execution": None, "next_owner": "worker", "next_action": "continue"}) is not None
        assert o.emit("development.backlog_item_admitted", "observed",
                      attributes={"plan_id": "p1", "item_id": "i1", "lane": "1", "job_id": "j1",
                                  "cached": False, "linked": True}) is not None

    base, result = collect(tmp_path, emit)
    assert result["inserted"] == 6 and result["corrupt"] == 0
    rows = snapshot(base)
    assert series(rows, NEW[0]) == {("published",): 1, ("retry",): 1, ("error",): 1}
    assert series(rows, NEW[3]) == {("verifying",): 1}
    assert series(rows, NEW[4]) == {(STATES[0],): 1}
    assert series(rows, NEW[5]) == {("admitted",): 1}
    assert REJECTIONS not in {r["metric"] for r in rows}
    text = render(rows)
    assert 'zeus_outbox_delivery_attempts_total{result="retry"} 1' in text
    assert 'zeus_delivery_stage_entries_total{stage="verifying"} 1' in text
    assert "# TYPE zeus_backlog_transitions_total counter" in text


def apply(base, rows):
    projector = MetricsProjector(providers=PROVIDERS)
    with base.transaction() as tx:
        projector.apply(tx, rows)
    return snapshot(base)


def test_settlements_and_abandonments_as_run_task_builds_them():
    reason = "exception:" + CANARY

    def settled(outcome, within):
        return row("development.invocation_settled", {
            "reservation_id": "r1", "invocation_outcome": outcome, "usage_source": "provider", "total_tokens": 10,
            "within_budget": within}, category="development")

    rows = apply(MemoryStore(), [
        settled("empty_answer", False), settled("empty_answer", False), settled("accepted", True),
        row("development.invocation_abandoned", {"reservation_id": "r2", "reason": reason}, provider="claude-code-cli",
            category="development")])
    assert series(rows, NEW[1]) == {(PROVIDER, "empty_answer", "false"): 2, (PROVIDER, "accepted", "true"): 1}
    assert series(rows, NEW[2]) == {("claude-code-cli",): 1}
    assert CANARY not in json.dumps(rows) and CANARY not in render(rows)
    assert 'zeus_invocation_settlements_total{provider="codex-app-server",outcome="empty_answer",within_budget="false"} 2' in render(rows)


def test_an_out_of_enum_value_counts_a_rejection_per_family():
    good_settled = {"invocation_outcome": "accepted", "within_budget": True}
    bad_rows = [
        (NEW[1], row("development.invocation_settled", {**good_settled, "invocation_outcome": "bogus"})),
        (NEW[2], row("development.invocation_abandoned", {"reason": "x"}, provider="unlisted")),
        (NEW[3], row("general.delivery_stage_entered", {"stage": "deploying"})),
        (NEW[4], row("development.worker_session_transition", {"state": "dormant"}))]
    base = MemoryStore()
    rows = apply(base, [r for _, r in bad_rows])
    assert series(rows, REJECTIONS) == {(name,): 1 for name, _ in bad_rows}
    assert not set(NEW) & {r["metric"] for r in rows}
    assert "deploying" not in render(rows)
