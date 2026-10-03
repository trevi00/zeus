"""The metric families of the observation metrics projection and the total row-to-sample rule (DESIGN-s9-X §2.2).

Layer: domain
Context: observation
Owns: `Family`, `FAMILIES` (the six families of X2a, keyed by name), `DURATION_BUCKETS` and `samples`
Does not own: the stored documents or the projection transaction (`observation.application.metrics_projector`), the
    text rendering (`observation.adapters.metrics_exposition`)
Entry points: Family, FAMILIES, DURATION_BUCKETS, samples
Contracts: INV-OBSERVATION-001

Pure and total: `samples` maps one stored observation row to the samples it contributes, and names the family of any
sample it refuses (a label value outside its closed enum, a missing, mistyped, non-finite or negative attribute). It
never raises on any dict, and a refused family emits no sample, so no unbounded or hostile value becomes a label.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from codex_harness.observation.domain.observation import CATEGORIES, INVOCATION_OUTCOMES

DURATION_BUCKETS = (1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200, 14400, 43200, 86400)
RESULTS = ("inserted", "duplicate", "conflict", "corrupt", "refused")
QUEUES = ("outbox", "agent_stream")
REASONS = ("quarantined", "dead_letter", "rejected")

PROJECTED = "zeus_metrics_projected_observations_total"
RECORDS = "zeus_observation_records_total"
DURATION = "zeus_model_invocation_duration_seconds"
EXCEPTIONS = "zeus_model_invocation_exceptions_total"
QUEUE_DROPPED = "zeus_queue_dropped_or_dead_total"
REJECTIONS = "zeus_metrics_label_rejections_total"


@dataclass(frozen=True)
class Family:
    name: str
    type: str
    help: str
    labels: tuple
    buckets: tuple = ()


FAMILIES = {family.name: family for family in (
    Family(PROJECTED, "counter",
           "Observations projected into the metrics, by category, from every newly stored observation row.",
           ("category",)),
    Family(RECORDS, "counter",
           "Spool records by collection result, from operations.collection_completed.",
           ("result",)),
    Family(DURATION, "histogram",
           "Model invocation duration in seconds by provider and outcome, from development.provider_finished.",
           ("provider", "outcome"), DURATION_BUCKETS),
    Family(EXCEPTIONS, "counter",
           "Model invocations that raised, by provider and whether the provider was entered, from development.provider_failed.",
           ("provider", "provider_entered")),
    Family(QUEUE_DROPPED, "counter",
           "Messages quarantined, dead-lettered or rejected, from general.message_quarantined and general.message_rejected.",
           ("queue", "reason")),
    Family(REJECTIONS, "counter",
           "Samples refused by the projection, by metric, because a label value or attribute was outside its contract.",
           ("metric",)),
)}


def _count(value) -> bool:
    return type(value) is int and value >= 0


def _seconds(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def samples(row, *, providers):
    """(list of (family, label_values, value), list of refused family names) for one observation row."""
    out, refused = [], []
    if not isinstance(row, dict):
        return out, [PROJECTED]
    category = row.get("category")
    if type(category) is str and category in CATEGORIES:
        out.append((PROJECTED, (category,), 1))
    else:
        refused.append(PROJECTED)
    event_type = row.get("event_type")
    attributes = row.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    execution = row.get("execution")
    provider = execution.get("provider") if isinstance(execution, dict) else None
    provider_ok = type(provider) is str and provider in providers
    if event_type == "operations.collection_completed":
        keys = ("records", "inserted", "duplicates", "conflicts", "corrupt")
        values = [attributes.get(key) for key in keys]
        if all(_count(value) for value in values) and values[0] - sum(values[1:]) >= 0:
            records, inserted, duplicates, conflicts, corrupt = values
            for result, value in zip(RESULTS, (inserted, duplicates, conflicts, corrupt,
                                               records - inserted - duplicates - conflicts - corrupt)):
                out.append((RECORDS, (result,), value))
        else:
            refused.append(RECORDS)
    elif event_type == "development.provider_finished":
        outcome = attributes.get("invocation_outcome")
        elapsed = attributes.get("elapsed_seconds")
        if provider_ok and type(outcome) is str and outcome in INVOCATION_OUTCOMES and _seconds(elapsed):
            out.append((DURATION, (provider, outcome), elapsed))
        else:
            refused.append(DURATION)
    elif event_type == "development.provider_failed":
        entered = attributes.get("provider_entered")
        if provider_ok and type(entered) is bool:
            out.append((EXCEPTIONS, (provider, "true" if entered else "false"), 1))
        else:
            refused.append(EXCEPTIONS)
    elif event_type == "general.message_quarantined":
        out.append((QUEUE_DROPPED, ("outbox", "quarantined"), 1))
    elif event_type == "general.message_rejected":
        dead = attributes.get("dead_letter")
        if type(dead) is bool:
            out.append((QUEUE_DROPPED, ("agent_stream", "dead_letter" if dead else "rejected"), 1))
        else:
            refused.append(QUEUE_DROPPED)
    return out, refused
