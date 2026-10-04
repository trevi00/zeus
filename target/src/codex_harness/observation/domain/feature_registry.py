"""The feature registry, the feature-use partition of the event types and the usage-state rule (DESIGN-s9-X §5, §5.1).

Layer: domain
Context: observation
Owns: `Feature`, `FEATURES`, `FEATURE_OF`, `STATES`, `feature_state` and `instrumented_rows`
Does not own: the event types (`observation.domain.observation.REGISTRY`), the counter family
    (`observation.domain.metric_families`) or the text rendering (`observation.adapters.metrics_exposition`)
Entry points: Feature, FEATURES, FEATURE_OF, STATES, feature_state, instrumented_rows
Contracts: INV-OBSERVATION-001

Every REGISTRY event type is the proof event of exactly one feature. A feature whose proof events have no producer in
the target is not instrumented, and names the module that will instrument it as its seam.
"""
from __future__ import annotations

from dataclasses import dataclass

INSTRUMENTED = "zeus_feature_instrumented"
INSTRUMENTED_HELP = "Whether a producer of the feature's proof events exists in the target, 1 or 0, by feature."
STATES = ("used", "unused_in_window", "disabled", "not_deployed", "uninstrumented", "collector_gap", "sampled_away")


@dataclass(frozen=True)
class Feature:
    id: str
    owner: str
    proof_events: tuple
    instrumented: bool
    seam: str | None = None


def _events(prefix, *names):
    return tuple(f"{prefix}.{name}" for name in names)


_D, _G, _O = "development", "general", "operations"

FEATURES = {feature.id: feature for feature in (
    Feature("model_invocation", "execution", _events(
        _D, "provider_started", "provider_finished", "provider_failed", "invocation_reserved", "invocation_settled",
        "invocation_abandoned", "output_evaluated", "usage_split_recorded", "termination_recorded",
        "progress_recorded", "reconciliation_required", "reconciliation_resolved"), True),
    Feature("task_execution", "coordination", (*_events(_D, "task_completed", "task_failed"),
                                                *_events(_O, "lease_renewed")), True),
    Feature("worker_sessions", "execution", (*_events(_D, "worker_session_transition"),
                                              *_events(_O, "worker_session_blocked"),
                                              *_events(_D, "checkpoint_recorded")), True),
    Feature("message_relay", "coordination", _events(
        _G, "message_published", "message_delivery_retry", "message_delivery_error", "message_quarantined"), True),
    Feature("message_intake", "coordination", _events(
        _G, "message_received", "message_accepted", "message_acknowledged", "message_rejected"), True),
    Feature("fleet_backlog", "coordination", (*_events(_D, "backlog_item_admitted"),
                                               *_events(_O, "backlog_item_refused", "backlog_recovered",
                                                        "backlog_unavailable")), True),
    Feature("host_delivery", "delivery", (*_events(_D, "delivery_check_observed"),
                                           *_events(_G, "delivery_stage_entered"),
                                           *_events(_O, "delivery_blocked", "delivery_rollback",
                                                    "delivery_switched")), True),
    Feature("continuation", "coordination", _events(_O, "continuation_blocked", "continuation_transition"), True),
    Feature("operation_finalization", "coordination",
            _events(_O, "operation_finalized", "operation_message_parked"), True),
    Feature("autonomous", "coordination", _events(_O, "autonomous_stage"), True),
    Feature("discovery_pressure", "research", _events(_O, "discovery_pressure_changed"), True),
    Feature("observation_pipeline", "observation", _events(
        _O, "collection_completed", "observation_conflict", "observation_refused", "sink_unavailable",
        "sink_recovered", "spool_saturated", "spool_append_failed", "alert_pending", "alert_suppressed",
        "collector_started"), True),
    Feature("audit_service", "research", _events(
        _O, "audit_progress_observed", "audit_repair_admitted", "audit_repair_settled", "audit_service_scheduled",
        "audit_service_started", "audit_service_stopped", "audit_service_task"), False, "entry.cli.audit_service"),
    Feature("evidence_inspection", "evidence", _events(_D, "evidence_inspection_started",
                                                       "evidence_inspection_finished"), False,
            "composition (OWNER-DECISIONS-S10 #7 EvidenceGate)"),
    Feature("supervisor", "coordination", _events(
        _O, "supervisor_tick", "supervisor_error", "worker_wake_requested", "worker_replace_requested",
        "backlog_observed"), True),
    Feature("process_lifecycle", "coordination", _events(_G, "process_started", "process_idle_exit"), False,
            "entry.cli / entry.processes.supervisor"),
    Feature("maintenance", "storage", _events(_O, "maintenance_job"), False, "none (no producer even in SOURCE)"),
    Feature("role_dispatch", "execution", _events(_D, "role_dispatch_decided"), True),
    Feature("capacity_admission", "coordination", _events(_O, "capacity_refused"), True),
    Feature("tool_calls", "execution", _events(_D, "tool_call_completed"), False, "open (pairing decision, §1.5)"),
    Feature("skill_selection", "context", _events(_D, "skill_selected"), True),
    Feature("ci_checks", "delivery", _events(_O, "ci_observed"), True),
    Feature("cleanup", "execution", _events(_O, "cleanup_recorded"), False,
            "execution.adapters.containers.cleanup_ledger observer= seam (retire/hold/reconcile); no caller holds an observer"),
    Feature("queue_wait", "coordination", _events(_O, "queue_item_waited"), True),
    Feature("declined_paths", "observation", _events(_O, "path_declined"), True),
)}

FEATURE_OF = {event_type: feature.id for feature in FEATURES.values() for event_type in feature.proof_events}


def feature_state(*, uses_in_window: int, instrumented: bool, enabled: bool = True, deployed: bool = True,
                  collector_healthy: bool, sampled: bool = False) -> str:
    """The usage state of one feature in a window, by a fixed precedence (DESIGN-s9-X §5.1).

    Not deployed, then disabled, then uninstrumented, then used (observed use beats a collector gap), then collector
    gap, then sampled away, otherwise unused in the window. Zero use is never a removal authority: only `used` is a
    positive observation, and `unused_in_window` says nothing beyond the window.
    """
    if not deployed:
        return "not_deployed"
    if not enabled:
        return "disabled"
    if not instrumented:
        return "uninstrumented"
    if uses_in_window > 0:
        return "used"
    if not collector_healthy:
        return "collector_gap"
    if sampled:
        return "sampled_away"
    return "unused_in_window"


def instrumented_rows() -> list:
    """The renderer rows of `zeus_feature_instrumented{feature}` (gauge, 1 or 0), in id order."""
    return [{"metric": INSTRUMENTED, "type": "gauge", "help": INSTRUMENTED_HELP, "labels": ["feature"], "buckets": [],
             "series": [{"labels": [feature_id], "value": 1 if FEATURES[feature_id].instrumented else 0}
                        for feature_id in sorted(FEATURES)]}]
