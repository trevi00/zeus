"""S9 X5a: the feature registry, the feature-use counter, the instrumented gauge and the usage-state rule (DESIGN-s9-X §5)."""
import itertools

import pytest
from test_s9_x2a_metrics import PROVIDERS, series, snapshot

from codex_harness.observation.adapters.metrics_exposition import render
from codex_harness.observation.application.metrics_projector import METRICS_BUCKET, MetricsProjector
from codex_harness.observation.domain.feature_registry import (
    FEATURE_OF,
    FEATURES,
    STATES,
    feature_state,
    instrumented_rows,
)
from codex_harness.observation.domain.metric_families import FAMILIES, samples
from codex_harness.observation.domain.observation import REGISTRY
from codex_harness.storage.adapters.memory_store import MemoryStore

USES = "zeus_feature_uses_total"

# The REGISTRY types with no producer in the target, measured at ec681d20 (DESIGN-s9-X §5.1, 2026-10-03).
UNPRODUCED_AT_EC681D20 = frozenset({
    "development.evidence_inspection_finished", "development.evidence_inspection_started",
    "development.role_dispatch_decided", "development.skill_selected", "development.tool_call_completed",
    "general.process_idle_exit", "general.process_started",
    "operations.audit_progress_observed", "operations.audit_repair_admitted", "operations.audit_repair_settled",
    "operations.audit_service_scheduled", "operations.audit_service_started", "operations.audit_service_stopped",
    "operations.audit_service_task",
    "operations.backlog_observed", "operations.capacity_refused", "operations.ci_observed",
    "operations.cleanup_recorded", "operations.collector_started", "operations.maintenance_job",
    "operations.path_declined", "operations.queue_item_waited",
    "operations.supervisor_error", "operations.supervisor_tick", "operations.worker_replace_requested",
    "operations.worker_wake_requested"})

IDS = ("model_invocation", "task_execution", "worker_sessions", "message_relay", "message_intake", "fleet_backlog",
       "host_delivery", "continuation", "operation_finalization", "autonomous", "discovery_pressure",
       "observation_pipeline", "audit_service", "evidence_inspection", "supervisor", "process_lifecycle",
       "maintenance", "role_dispatch", "capacity_admission", "tool_calls", "skill_selection", "ci_checks", "cleanup",
       "queue_wait", "declined_paths")


def test_every_registry_type_is_in_exactly_one_feature_and_no_proof_event_is_outside_it():
    proofs = [event for feature in FEATURES.values() for event in feature.proof_events]
    assert len(proofs) == len(set(proofs))
    assert set(proofs) == set(REGISTRY) and len(REGISTRY) == 76
    assert FEATURE_OF == {event: feature.id for feature in FEATURES.values() for event in feature.proof_events}
    assert all(feature.id == key for key, feature in FEATURES.items())


def test_the_ids_are_the_25_of_the_table():
    assert set(FEATURES) == set(IDS) and len(FEATURES) == 25


def test_instrumented_is_false_exactly_when_every_proof_event_is_unproduced():
    assert UNPRODUCED_AT_EC681D20 <= set(REGISTRY) and len(UNPRODUCED_AT_EC681D20) == 26
    for feature in FEATURES.values():
        unproduced = set(feature.proof_events) <= UNPRODUCED_AT_EC681D20
        assert feature.instrumented is (not unproduced), feature.id
        assert (feature.seam is None) is feature.instrumented, feature.id


def rule(uses, instrumented, enabled, deployed, healthy, sampled):
    if not deployed:
        return "not_deployed"
    if not enabled:
        return "disabled"
    if not instrumented:
        return "uninstrumented"
    if uses > 0:
        return "used"
    if not healthy:
        return "collector_gap"
    return "sampled_away" if sampled else "unused_in_window"


def test_state_precedence_over_every_combination():
    seen = set()
    for uses, instrumented, enabled, deployed, healthy, sampled in itertools.product(
            (0, 1), *([(True, False)] * 5)):
        state = feature_state(uses_in_window=uses, instrumented=instrumented, enabled=enabled, deployed=deployed,
                              collector_healthy=healthy, sampled=sampled)
        assert state == rule(uses, instrumented, enabled, deployed, healthy, sampled)
        seen.add(state)
    assert seen == set(STATES)


def test_state_examples_and_defaults():
    assert feature_state(uses_in_window=0, instrumented=True, collector_healthy=False) == "collector_gap"
    assert feature_state(uses_in_window=0, instrumented=True, collector_healthy=True) == "unused_in_window"
    assert feature_state(uses_in_window=3, instrumented=True, collector_healthy=False) == "used"


def project(rows):
    base = MemoryStore()
    projector = MetricsProjector(providers=PROVIDERS)
    with base.transaction() as tx:
        projector.apply(tx, rows)
        assert tx.get(METRICS_BUCKET, "family:" + USES) is not None or not any(
            r["event_type"] in FEATURE_OF for r in rows)
    return base


def test_counter_samples_and_projection():
    assert FAMILIES[USES].type == "counter" and FAMILIES[USES].labels == ("feature",)
    mapped = {"category": "development", "event_type": "development.provider_finished",
              "attributes": {"invocation_outcome": "accepted", "elapsed_seconds": 1.0},
              "execution": {"provider": "codex-app-server"}}
    out, refused = samples(mapped, providers=PROVIDERS)
    assert (USES, ("model_invocation",), 1) in out and refused == []
    unmapped = {"category": "development", "event_type": "development.not_a_registered_type", "attributes": {}}
    out, refused = samples(unmapped, providers=PROVIDERS)
    assert [item for item in out if item[0] == USES] == [] and refused == []
    base = project([mapped, mapped, unmapped])
    rows = snapshot(base)
    assert series(rows, USES) == {("model_invocation",): 2}
    assert f'{USES}{{feature="model_invocation"}} 2\n' in render(rows)


def test_unmapped_row_alone_writes_no_feature_series():
    base = project([{"category": "development", "event_type": "development.nothing", "attributes": {}}])
    assert all(row["metric"] != USES for row in snapshot(base))


def test_instrumented_rows_render_25_series():
    rows = instrumented_rows()
    [row] = rows
    assert row["type"] == "gauge" and row["labels"] == ["feature"]
    assert [item["labels"] for item in row["series"]] == [[i] for i in sorted(FEATURES)]
    text = render(rows)
    lines = [x for x in text.splitlines() if x.startswith("zeus_feature_instrumented{")]
    assert len(lines) == 25
    assert 'zeus_feature_instrumented{feature="supervisor"} 0' in lines
    assert 'zeus_feature_instrumented{feature="model_invocation"} 1' in lines


@pytest.mark.parametrize("feature_id", sorted(FEATURES))
def test_every_feature_has_an_owner_and_proof_events(feature_id):
    feature = FEATURES[feature_id]
    assert feature.owner and feature.proof_events
