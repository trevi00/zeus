"""S9 X1b-1: RunTask emits `development.usage_split_recorded` (OBSERVABILITY-COVERAGE-20261002, DESIGN-s9-X §1.3).

- The event goes through the Observer spool right AFTER settlement, never the audit table
  (`test_observation_wiring:130` asserts that table's event-type SET) and never as a `development.provider_*`
  type (`test_council_input:694`).
- Absent usage is null, never 0. Claude's split is `usage["parts"]`; Codex's is the raw `usage["total"]` breakdown
  (`inputTokens`/`outputTokens`/`cachedInputTokens`/optional `cacheWriteInputTokens`; names from codex-cli 0.156.1
  `app-server generate-json-schema`, `v2/ThreadTokenUsageUpdatedNotification.json` `TokenUsageBreakdown`).
- The Claude path is proved on the extraction (`_usage_split`) with the shape `usage_record` produces; the M7-bound
  `test_claude_execution` drives the full Claude flow and stays unchanged.
Fixture proof only: both transports are stubbed (see test_s4_run_task).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_s4_run_task import build, submit, task_row  # noqa: E402

from codex_harness.execution.application.invocation_ledger import InvocationCapacityRefused
from codex_harness.execution.application.run_task import _usage_split  # noqa: E402
from codex_harness.execution.domain.invocation import usage_record
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.observation.domain.event_catalog import (  # noqa: E402
    check_catalog_attributes,
    load_catalog,
)

SPLIT = "development.usage_split_recorded"
NULLS = {"input_tokens": None, "output_tokens": None, "cache_read_tokens": None, "cache_write_tokens": None}


def run_plan(tmp_path, **extra):
    run_task, workflow, store, _, _ = build(tmp_path, extra=extra)
    submit(workflow)
    assert run_task.execute_one("lead:improvement")["status"] == "succeeded"
    return run_task, store


def spool(run_task):
    return list(run_task.observer.spool.records())


def splits(run_task):
    return [r for r in spool(run_task) if r["event_type"] == SPLIT]


def test_the_renamed_catalog_loads_as_v2():
    catalog = load_catalog()
    assert catalog["catalog_version"] == 2
    assert SPLIT in catalog["events"] and "development.provider_usage_split" not in catalog["events"]
    assert not SPLIT.startswith("development.provider_")


def test_codex_split_follows_settlement_with_the_exact_counts(tmp_path):
    usage = {"total": {"totalTokens": 321, "inputTokens": 200, "outputTokens": 100, "cachedInputTokens": 50,
                       "reasoningOutputTokens": 21, "cacheWriteInputTokens": 12}}
    run_task, store = run_plan(tmp_path, usage=usage)
    [event] = splits(run_task)
    with store.transaction() as tx:
        [settled] = [a for a in tx.scan("observation_audit") if a["event_type"] == "development.invocation_settled"]
    attributes = event["attributes"]
    assert attributes == {"reservation_id": settled["attributes"]["reservation_id"], "provider_session_ref": "th",
                          "input_tokens": 200, "output_tokens": 100, "cache_read_tokens": 50,
                          "cache_write_tokens": 12, "usage_source": "thread/tokenUsage/updated"}
    assert event["outcome"] == "observed"
    assert event["execution"] == settled["execution"]
    assert (event["correlation_id"], event["causation_id"]) == (settled["correlation_id"], settled["causation_id"])
    check_catalog_attributes(SPLIT, attributes)
    # after the provider's own events (finished precedes settlement, the split follows it)
    types = [r["event_type"] for r in spool(run_task)]
    assert types.index("development.provider_finished") < types.index(SPLIT)
    assert [t for t in types if t.startswith("development.provider_")] == ["development.provider_started",
                                                                           "development.provider_finished"]


def test_codex_unknown_usage_is_all_null_never_zero(tmp_path):
    run_task, _ = run_plan(tmp_path, usage=None)
    [event] = splits(run_task)
    assert event["attributes"] == {"reservation_id": event["attributes"]["reservation_id"], "provider_session_ref": "th",
                                   **NULLS, "usage_source": "unknown"}
    check_catalog_attributes(SPLIT, event["attributes"])


def test_codex_total_without_a_breakdown_keeps_the_fields_null(tmp_path):
    run_task, _ = run_plan(tmp_path, usage={"total": {"totalTokens": 7}})
    [event] = splits(run_task)
    assert {k: event["attributes"][k] for k in NULLS} == NULLS
    assert event["attributes"]["usage_source"] == "thread/tokenUsage/updated"


def test_the_split_is_never_written_to_the_audit_table(tmp_path):
    run_task, store = run_plan(tmp_path, usage={"total": {"totalTokens": 3, "inputTokens": 3}})
    with store.transaction() as tx:
        kinds = {a["event_type"] for a in tx.scan("observation_audit")}
    assert SPLIT not in kinds
    assert kinds <= {"development.invocation_reserved", "development.invocation_settled", "general.message_published"}
    assert {"development.invocation_reserved", "development.invocation_settled"} <= kinds
    assert len(splits(run_task)) == 1


def test_claude_split_reads_the_usage_parts(tmp_path):
    result = {"usage": {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": None,
                        "cache_read_input_tokens": 5}, "thread_id": "sess-1", "events": []}
    usage = usage_record(result, "claude_cli")
    assert _usage_split("r-1", result, usage, "claude_cli") == {
        "reservation_id": "r-1", "provider_session_ref": "sess-1", "input_tokens": 100, "output_tokens": 20,
        "cache_read_tokens": 5, "cache_write_tokens": None, "usage_source": "claude/result.usage"}
    written = _usage_split("r-1", {"usage": {"cache_creation_input_tokens": 9}}, usage_record(
        {"usage": {"cache_creation_input_tokens": 9}}, "claude_cli"), "claude_cli")
    assert written["cache_write_tokens"] == 9 and written["input_tokens"] is None


def test_claude_without_usage_is_all_null_and_unknown():
    result = {"events": []}
    split = _usage_split("r-1", result, usage_record(result, "claude_cli"), "claude_cli")
    assert split == {"reservation_id": "r-1", "provider_session_ref": None, **NULLS, "usage_source": "unknown"}
    check_catalog_attributes(SPLIT, split)


def test_a_malformed_count_is_null_not_zero():
    result = {"usage": {"total": {"inputTokens": -1, "outputTokens": "5", "cachedInputTokens": True}}}
    split = _usage_split("r-1", result, usage_record(result), "app_server")
    assert {k: split[k] for k in NULLS} == NULLS


def test_no_reservation_emits_nothing(tmp_path):
    run_task, workflow, store, _, calls = build(tmp_path)
    out = run_task._run("lead:improvement", "t-nolease", "objective", {}, str(tmp_path),
                        {"type": "object", "properties": {}}, True)
    assert calls and out
    assert [r for r in spool(run_task) if r["event_type"] == "development.provider_finished"]  # the flow ran
    assert splits(run_task) == []  # no lease, no reservation, nothing settled, nothing emitted


def test_an_event_the_registry_refuses_is_dropped_and_counted_never_the_task(tmp_path):
    run_task, store = run_plan(tmp_path, usage={"total": {"totalTokens": 3}}, thread_id=12345)
    assert splits(run_task) == []
    assert run_task.observer.counters["refused"] >= 1
    assert task_row(store)["status"] == "succeeded"


def test_a_capacity_refusal_is_observed_as_the_invocation_budget_and_still_refuses(tmp_path):
    run_task, workflow, store, _, calls = build(tmp_path)
    run_task.invocations.capacity = 0  # every reservation now meets the capacity refusal
    submit(workflow)
    seen = []
    original = run_task.invocations.reserve

    def reserve(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except ContractError as exc:
            seen.append(exc)
            raise

    run_task.invocations.reserve = reserve
    run_task.execute_one("lead:improvement")  # the ordinary failure disposition handles the refusal, as before
    assert not calls and len(seen) == 1 and type(seen[0]) is InvocationCapacityRefused
    assert isinstance(seen[0], ContractError) and "Invocation capacity is reserved by other executions" in str(seen[0])
    [event] = [r for r in spool(run_task) if r["event_type"] == "operations.capacity_refused"]
    assert event["attributes"] == {"scope": "invocation_budget", "refusal_reason": "budget_exhausted",
                                   "retry_after_seconds": None}
    assert event["severity"] == "warning" and event["outcome"] == "blocked"
    check_catalog_attributes("operations.capacity_refused", event["attributes"])
    assert splits(run_task) == []


def observer_for_catalog(tmp_path):
    return build(tmp_path)[0].observer


def test_the_observer_refuses_a_catalog_event_outside_the_catalog_and_leaves_other_events_alone(tmp_path):
    observer = observer_for_catalog(tmp_path)
    good = {"scope": "invocation_budget", "refusal_reason": "budget_exhausted", "retry_after_seconds": None}
    assert observer.emit("operations.capacity_refused", "blocked", attributes=good, severity="warning")
    before = observer.counters["refused"]
    for bad in ({**good, "scope": "made_up"}, {**good, "refusal_reason": "because"}, {**good, "extra": 1}):
        assert observer.emit("operations.capacity_refused", "blocked", attributes=bad, severity="warning") is None
    assert observer.counters["refused"] == before + 3
    opaque = {"reservation_id": "has a space", "provider_session_ref": None, **NULLS, "usage_source": "unknown"}
    assert observer.emit(SPLIT, "observed", attributes=opaque) is None
    # an event type outside the catalog is validated exactly as before
    assert observer.emit("general.process_started", "started", attributes={})


def test_the_observer_audit_checks_the_catalog_first_too(tmp_path):
    run_task, workflow, store, _, _ = build(tmp_path)
    bad = {"scope": "made_up", "refusal_reason": "budget_exhausted", "retry_after_seconds": None}
    with store.transaction() as tx:
        try:
            run_task.observer.audit(tx, "operations.capacity_refused", "blocked", identity=["t", "1"], attributes=bad,
                                    severity="warning")
        except ContractError:
            return
    raise AssertionError("a catalog-refused audit must raise")
